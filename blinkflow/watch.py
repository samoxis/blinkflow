"""BlinkFlow watches: it notices an incident on its own, with no one telling it.

Muse Glimmer, on this PC, looks at the newest frame of the capture buffer as often as it can (about
once a second), and answers yes/no against a JSON schema: is the robot in view, touching something,
close to touching it, fallen; one look in PAIR_EVERY also gets the frame from STUCK_DT earlier and is
asked whether the robot is stuck in place. A yes only raises a hand. SAM 3.1 confirms: the BEFORE + AFTER seconds around the raised
frame are cut from the buffer, blinkflow.see follows the robot and the nearest object through them,
and only what the proof would also call an incident counts: a contact (the reading prove.verdict
trusts), a fall (pixels, or the brain's own log), or a robot whose mask stays the same for STUCK_S
after it has moved; and only if what SAM followed as the robot moved at all in the window. A raise
SAM does not confirm is written down and watching goes on. The first
confirmed incident ends the watch; with --loop the existing loop (blinkflow.fix) starts on it, with
the window as its snapshot (the moment is the raised frame's, on BlinkFlow's clock) and see's
evidence reused, so nothing is seen twice. The loop proves contacts and falls; a stuck robot is
reported, and the loop is not started, because the proof has no verdict for it.

Glimmer never holds up the capture: the sidecar records on Windows on its own, and here one worker
takes the newest frame whenever it is free; frames that arrive meanwhile are dropped, not queued.
The calls use the context size of every other Glimmer call, so the copy already in VRAM serves them
(another num_ctx would make Ollama load a second one).

    python3 -m blinkflow.watch live [--brain DIR] [--seconds 20] [--loop]   # simulator + sidecar
    python3 -m blinkflow.watch clip <twin meta.json | sidecar clip .json> [--loop]

A clip is played on the wall clock as if it were the buffer: watching starts when its brain starts
(as live, where it starts with the brain), a frame appears LAG after its time (as from /frame), and
the brain log handed on is cut at the window's end, so nothing from the future is read. The
simulator's contact log, the scene files and the twin's truth.json are never read.
"""
import argparse
import bisect
import collections
import concurrent.futures
import gzip
import json
import os
import pathlib
import signal
import statistics
import subprocess
import sys
import threading
import time

from . import TARGET, events, models, prove, sam, see, sim
from .capture import Sidecar

HOME = pathlib.Path.home()
REPO = pathlib.Path(__file__).resolve().parent.parent
RUNS = HOME / "blinkflow-runs" / "watch"
WIDTH = 448              # Glimmer's frames (640 is slower, with the same answers)
PERIOD = 0.5             # at most two looks a second
STUCK_DT = 2.0           # the earlier frame of a pair look
PAIR_EVERY = 2           # every other look is a pair (now and STUCK_DT before; it alone is asked about
                         # stuck), the others see one frame (0.9 s instead of 1.25). Around the incidents
                         # of the suite the pair sees the low cube better (9/11 frames vs 3/11), the
                         # single frame the box (b11 6/11 vs 0/11, live 61/77 vs 29/77); as often on controls
LAG = 0.08               # a clip's frame appears this late (live /frame: median 0.078 s, max 0.14)
BEFORE, AFTER = 6.0, 1.0 # the window SAM 3.1 confirms on, around the raised frame
STUCK_S = 4.0            # stuck: the robot's mask unchanged this long (the good brain's longest
STILL_IOU = 0.8          # standstill, at its start, is 2.9 s)...
STUCK_GRACE = 2.0        # ...all of it after the brain's first STUCK_GRACE s (it holds 1.5 s at start),
MOVED_IOU = 0.3          # and after it has moved; Glimmer raises it only after STUCK_LOOKS pair looks in a row
STUCK_LOOKS = 2          # (it said "stuck" on every look of a good run's first 7 s, where the robot is slow)
MAX_CONFIRM = 4          # SAM confirmations per watch (~$0.09 each)

LOOK_PROMPT = (
    "Two frames from a fixed camera watching a small two-legged walking robot in a simulator; the second "
    "frame is now, the first is {dt:.1f} s earlier. Answer about NOW: robot_visible: is the robot in the "
    "frame; touching: is any part of the robot touching or pressed against an object (box, cube, wall, "
    "furniture); close: is any part of the robot, its feet included, touching an object or nearly touching it, "
    "closer than the width of one foot; fallen: is the robot lying on its side or back, or fallen into a pit or off an edge; "
    "stuck: is the robot in exactly the same place and pose in both frames. Reply only with JSON.")
LOOK_SCHEMA = {"type": "object",
               "properties": {k: {"type": "boolean"} for k in ("robot_visible", "touching", "close", "fallen", "stuck")},
               "required": ["robot_visible", "touching", "close", "fallen", "stuck"]}
ONE_PROMPT = (
    "One frame from a fixed camera watching a small two-legged walking robot in a simulator. robot_visible: is "
    "the robot in the frame; touching: is any part of the robot touching or pressed against an object (box, cube, "
    "wall, furniture); close: is any part of the robot, its feet included, touching an object or nearly touching "
    "it, closer than the width of one foot; fallen: is the robot lying on its side or back, or fallen into a pit "
    "or off an edge. Reply only with JSON.")
ONE_SCHEMA = {"type": "object", "properties": {k: LOOK_SCHEMA["properties"][k] for k in LOOK_SCHEMA["required"][:4]},
              "required": LOOK_SCHEMA["required"][:4]}
SIGNS = ("touching", "close", "fallen", "stuck")   # close: from above, a foot brushing a box is a few pixels;
                                                   # Glimmer said "touching" in 3 of 9 live contacts, "close" in 9


def cut_record(record, until, out):
    """The brain log up to brain time `until` (s after its first tick), as a new .jsonl.gz."""
    with gzip.open(record, "rt") as f, gzip.open(out, "wt") as g:
        g.write(next(f))
        t0 = None
        for line in f:
            t = json.loads(line)["t"]
            t0 = t if t0 is None else t0
            if t - t0 > until:
                break
            g.write(line)
    return str(out)


def jpegs(clip, width=WIDTH):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", clip, "-vf", f"scale={width}:-2", "-c:v", "mjpeg",
                          "-q:v", "3", "-f", "image2pipe", "-"], capture_output=True, check=True).stdout
    return [j + b"\xff\xd9" for j in raw.split(b"\xff\xd9") if j.startswith(b"\xff\xd8")]


# ── feeds: where the newest frame comes from, on whose clock ─────────────────
def tell_feed(feed):
    """The feed, in the event stream: a clip's video and when its brain time 0 is played (the console plays
    the same clip alongside)."""
    t = feed.times
    events.emit("feed", kind="clip", clock="brain", t_start=feed.t_start, clip=str(feed.clip), times0=t[0],
                fps=round((len(t) - 1) / (t[-1] - t[0]), 3), frames=len(t), end=t[-1], lag=feed.lag, buffer_s=60)


class ClipFeed:
    """A recorded clip played back as if it were the buffer. Clock: brain time (s after its first tick)."""

    def __init__(self, path, lag=LAG):
        self.path = pathlib.Path(path).expanduser().resolve()
        self.meta = json.loads(self.path.read_text())
        snap = see.load_snapshot(self.path)
        self.clip, self.record = snap["clip"], snap["record"]
        self.frames = jpegs(self.clip)
        self.times = snap["brain_time"][:len(self.frames)]
        self.lag, self.t_start = lag, None

    def start(self):
        self.t_start = time.time()

    def now(self):
        return time.time() - self.t_start

    def brain_s(self, t):
        return t

    def latest(self):
        i = bisect.bisect_right(self.times, self.now() - self.lag) - 1
        return (self.times[i], self.frames[i]) if i >= 0 else None

    def done(self):
        return self.now() - self.lag > self.times[-1]

    def window(self, t0, t1, out):
        """The buffer's frames from t0 to t1 as a snapshot, once t1 has been played."""
        while self.now() - self.lag < t1 and not self.done():
            time.sleep(0.05)
        out.mkdir(parents=True, exist_ok=True)
        i0, i1 = bisect.bisect_left(self.times, t0), bisect.bisect_right(self.times, t1)
        clip = out / "window.mp4"
        see.trim(self.clip, i0, clip, i1)
        until = self.times[i1 - 1]
        m = dict(self.meta, seconds=round(until, 3), watched_from=str(self.path), window=[i0, i1])
        m["record"] = self.record and cut_record(self.record, until, out / "run.jsonl.gz")
        if "video_times" in m:
            m.update(video=str(clip), video_times=self.meta["video_times"][i0:i1])
        else:
            m.update(path=str(clip), frames=i1 - i0, t0_epoch=self.meta["t0_epoch"] + i0 / self.meta["fps"])
            m.pop("cursor", None)
        snap = out / "snapshot.json"
        snap.write_text(json.dumps(m))
        return snap


class LiveFeed:
    """The sidecar's ring while the brain runs. Clock: the WSL epoch."""

    def __init__(self, cap, brain, proc, launched):
        self.cap, self.brain, self.proc = cap, brain, proc
        self.brain_start = launched          # until the brain's log can be read; corrected after it stops
        self.skew = cap.skew()
        self.lags, self.last, self.fetched = [], None, 0.0

    def start(self):
        pass

    def now(self):
        return time.time()

    def brain_s(self, t):
        return t - self.brain_start

    def latest(self):
        # each /frame is an ffmpeg decode on the Windows side: at most every PERIOD / 2
        if self.last and time.time() - self.fetched < PERIOD / 2:
            return self.last
        self.fetched = time.time()
        try:
            t, j = self.cap.frame(WIDTH, self.skew)
        except (OSError, ValueError, KeyError):
            return self.last
        self.lags.append(time.time() - t)
        self.last = (t, j)
        return self.last

    def done(self):
        return self.proc.poll() is not None

    def window(self, t0, t1, out):
        while time.time() < t1:
            time.sleep(0.05)
        m = self.cap.snapshot(t1 - t0, out, end=t1)
        # the log is read only once the brain has stopped and closed it (finish_live)
        m.update(brain=str(self.brain), record=None, brain_start=self.brain_start,
                 seconds=round(m["t1_epoch"] - self.brain_start, 3))
        snap = out / "snapshot.json"
        snap.write_text(json.dumps(m))
        return snap


# ── the watcher ──────────────────────────────────────────────────────────────
def iou(a, b):
    return (a & b).sum() / max((a | b).sum(), 1)


def motion(evdir, snap):
    """How the followed robot moved in the window: `moved`, its mask somewhere overlapping its mask
    elsewhere by less than MOVED_IOU; `still_s`, the longest time its mask stays within STILL_IOU of
    itself after it has moved, all after STUCK_GRACE s of brain. A box SAM was sent to follow as the
    robot (Glimmer named the robot "purple pillar" once) never moves, nor does a robot that has not started."""
    ev = json.loads((evdir / "evidence.json").read_text())
    s = see.load_snapshot(snap)
    w, h = ev["shot"]["size"]
    start = ev["shot"]["first_frame"]
    frames = sam.load_raw(evdir / "sam-robot.txt")
    seen = [(s["brain_time"][start + f], see.union(frames[f], (w, h))) for f in range(ev["shot"]["frames"])
            if frames.get(f)]
    seen = [(t, m) for t, m in seen if m.any()]
    some = seen[::5]
    moved = any(iou(a, b) < MOVED_IOU for i, (_, a) in enumerate(some) for _, b in some[i + 1:])
    late = [(t, m) for t, m in seen if t >= STUCK_GRACE]
    best, i = 0.0, 0
    while i < len(late):
        ref = late[i][1]
        j = i
        while j + 1 < len(late) and iou(late[j + 1][1], ref) >= STILL_IOU:
            j += 1
        if any(iou(m, ref) < MOVED_IOU for _, m in late[:i:3]):
            best = max(best, late[j][0] - late[i][0])
        i = j + 1
    return {"moved": moved, "still_s": round(best, 2)}


class Watcher:
    def __init__(self, feed, out):
        self.feed, self.out = feed, pathlib.Path(out)
        self.looks, self.raises, self.confirms = [], [], []
        self.glimmer = models.Ledger()

    def look(self, before, now):
        """One frame, or a pair with `before` (only a pair is asked whether the robot is stuck)."""
        dt = before and now[0] - before[0]
        schema = LOOK_SCHEMA if before else ONE_SCHEMA
        t = time.time()
        try:
            a = json.loads(models.glimmer(LOOK_PROMPT.format(dt=dt) if before else ONE_PROMPT,
                                          [before[1], now[1]] if before else [now[1]], self.glimmer,
                                          "watch", schema=schema))
        except (OSError, ValueError) as e:
            return {"t": now[0], "error": str(e)}
        r = {"t": round(now[0], 3), "dt": dt and round(dt, 2), "asked_at": round(self.feed.now(), 3),
             "seconds": round(time.time() - t, 2), **{k: bool(a.get(k)) for k in schema["required"]}}
        events.emit("look", **r)
        return r

    def confirm(self, raised):
        """SAM 3.1 on the window around a raised frame: the incident it shows, if any."""
        k = len(self.confirms) + 1
        d = self.out / f"confirm-{k}"
        t = raised["t"]
        t0 = time.time()
        snap = self.feed.window(t - BEFORE, t + AFTER, d)
        evdir = d / "evidence"
        events.emit("confirm.start", n=k, raised=raised, window=[t - BEFORE, t + AFTER])
        ev = see.see(snap, evdir, tag=f"confirm-{k}")
        cost = json.loads((evdir / "models.json").read_text())["total_cost_usd"]
        mo = motion(evdir, snap)
        names = [ev["names"]["robot"], ev["names"]["object"]]
        # what SAM followed as the robot must be one, and it must have moved: else nothing is confirmed
        # (Glimmer sometimes names the purple box as the robot; Muse Spark, asked again, does the same)
        robot_ok = mo["moved"] and names[0] != names[1]
        reading, hit = prove.contact_of(ev)
        fall = ev["fall"]["first"]
        kind = None if not robot_ok else "fall" if fall else "contact" if hit else \
            "stuck" if mo["still_s"] >= STUCK_S else None
        at = fall or hit
        return {"n": k, "raised": raised, "window": [round(t - BEFORE, 3), round(t + AFTER, 3)],
                "snapshot": str(snap), "evidence": str(evdir), "kind": kind,
                "confirmed": kind is not None, "names": names, "robot_moved": mo["moved"],
                "incident_s": round(at["brain_s"], 3) if at else None,
                "reading": (fall or {}).get("reading") if fall else reading if hit else None,
                "still_s": mo["still_s"], "seconds": round(time.time() - t0, 1), "done_at": round(self.feed.now(), 3),
                "cost_usd": cost}

    def run(self):
        """Watch until a confirmed incident or the end of the feed. Returns the confirmation, or None."""
        self.feed.start()
        if isinstance(self.feed, ClipFeed):
            tell_feed(self.feed)
        history = collections.deque()
        pool = concurrent.futures.ThreadPoolExecutor(2)
        looking = confirming = None
        streak = 0
        covered = float("-inf")             # raises before this were inside a window SAM already saw
        found = None
        tick = time.time()
        while True:
            if looking and looking.done():
                r = looking.result()
                looking = None
                self.looks.append(r)
                # a robot fallen into a pit may be out of sight now; the others need it in view,
                # and stuck cannot be confirmed before STUCK_S of brain past the grace, nor raised on one look
                if "stuck" in r:
                    streak = streak + 1 if r["stuck"] else 0
                signs = [s for s in SIGNS if r.get(s) and (s == "fallen" or r["robot_visible"])
                         and (s != "stuck" or (r["t"] >= STUCK_GRACE + STUCK_S and streak >= STUCK_LOOKS))]
                if signs:
                    self.raises.append({**r, "signs": signs, "wall": round(time.time(), 3)})
                    events.emit("raise", t=r["t"], signs=signs)
            if confirming and confirming.done():
                try:
                    c = confirming.result()
                except Exception as e:          # an API error is a confirmation that did not happen
                    c = {"n": len(self.confirms) + 1, "kind": None, "confirmed": False, "incident_s": None,
                         "window": None, "names": None, "seconds": None, "cost_usd": 0.0, "done_at": self.feed.now(),
                         "error": f"{type(e).__name__}: {e}"}
                confirming = None
                self.confirms.append(c)
                print(json.dumps({k: c[k] for k in ("n", "kind", "incident_s", "window", "names", "seconds")}),
                      flush=True)
                events.emit("confirmed", **{k: c.get(k) for k in ("n", "kind", "confirmed", "names", "incident_s",
                                                                  "reading", "evidence", "snapshot", "window")})
                if c["confirmed"]:
                    found = c
                    events.clock_start(c["raised"]["wall"], "the watcher raised a hand")
                    break
            if not confirming and len(self.confirms) < MAX_CONFIRM:
                nxt = next((r for r in self.raises if r["t"] > covered), None)
                if nxt:
                    covered = nxt["t"] + AFTER
                    confirming = pool.submit(self.confirm, nxt)
            if self.feed.done():
                if not (looking or confirming):
                    break
            else:
                f = self.feed.latest()
                if f and (not history or f[0] > history[-1][0]):
                    history.append(f)
                    while history[0][0] < f[0] - STUCK_DT - 1.0:
                        history.popleft()
                if not looking and history and history[-1][0] > (self.looks[-1]["t"] if self.looks else -1e18):
                    now = history[-1]
                    before = None
                    if len(self.looks) % PAIR_EVERY == PAIR_EVERY - 1 and now[0] - history[0][0] >= STUCK_DT:
                        before = min(history, key=lambda h: abs(h[0] - (now[0] - STUCK_DT)))
                    looking = pool.submit(self.look, before, now)
            tick += PERIOD / 5
            time.sleep(max(0.0, tick - time.time()))
        pool.shutdown(wait=True, cancel_futures=True)
        return found

    def summary(self):
        secs = [l["seconds"] for l in self.looks if "seconds" in l]
        ts = [l["t"] for l in self.looks if "seconds" in l]
        gaps = [b - a for a, b in zip(ts, ts[1:])]
        return {"looks": len(self.looks), "look_errors": sum("error" in l for l in self.looks),
                "look_s_median": secs and round(statistics.median(secs), 2),
                "look_s_max": secs and round(max(secs), 2),
                "frame_gap_s_median": gaps and round(statistics.median(gaps), 2),
                "frame_gap_s_max": gaps and round(max(gaps), 2),
                "raises": len(self.raises), "confirmations": len(self.confirms),
                "sam_cost_usd": round(sum(c["cost_usd"] for c in self.confirms), 4)}

    def write(self, extra=None):
        doc = {**(extra or {}), "summary": self.summary(), "confirmations": self.confirms,
               "raises": self.raises, "looks": self.looks,
               "settings": {"width": WIDTH, "period_s": PERIOD, "stuck_dt_s": STUCK_DT, "window_s": [BEFORE, AFTER],
                            "pair_every": PAIR_EVERY, "stuck_s": STUCK_S, "still_iou": STILL_IOU, "stuck_grace_s": STUCK_GRACE,
                            "lag_s": getattr(self.feed, "lag", None)}}
        n, tok_in, tok_out, secs = 0, 0, 0, 0.0
        for c in self.glimmer.calls:
            n, secs = n + 1, secs + c["seconds"]
            tok_in, tok_out = tok_in + (c["input_tokens"] or 0), tok_out + (c["output_tokens"] or 0)
        doc["models"] = {"model": models.GLIMMER, "where": "local", "purpose": "watch: one look per frame pair",
                         "calls": n, "seconds": round(secs, 1), "input_tokens": tok_in, "output_tokens": tok_out,
                         "cost_usd": 0.0}
        (self.out / "watch.json").write_text(json.dumps(doc, indent=1))
        return doc


def loop(found, brain, out):
    """The existing loop on a confirmed incident: blinkflow.fix on the window, see's evidence reused."""
    if found["kind"] == "stuck":
        return {"started": False, "why": "a stuck robot is reported; the proof has no verdict for it"}
    env = {**os.environ, "BLINKFLOW_TARGET": str(brain)}
    t = time.time()
    with open(out / "fix.log", "w") as log:
        rc = subprocess.run([sys.executable, "-m", "blinkflow.fix", found["snapshot"], "--auto", "--evidence",
                             found["evidence"], "--out", str(out / "fix")], cwd=REPO, env=env,
                            stdout=log, stderr=subprocess.STDOUT).returncode
    done = out / "fix" / "fix.json"
    r = {"started": True, "rc": rc, "seconds": round(time.time() - t, 1), "run": str(out / "fix")}
    if done.exists():
        d = json.loads(done.read_text())
        r.update(fixed=d.get("fixed"), attempts=len(d.get("attempts", [])), stopped=d.get("stopped"))
    return r


# ── live ─────────────────────────────────────────────────────────────────────
def vram(samples, stop):
    """Used GPU memory (MiB) once a second, from the Windows driver, until `stop`."""
    while not stop.is_set():
        r = subprocess.run(["nvidia-smi.exe", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                           capture_output=True, text=True)
        if r.returncode == 0 and r.stdout.strip():
            samples.append((round(time.time(), 2), int(r.stdout.split()[0])))
        stop.wait(1.0)


def finish_live(found, feed, record):
    """With the brain stopped and its log closed: the window gets the true brain start and the log
    (cut at the window's end), and see's measurements are redone on the same SAM replies."""
    start = sim.brain_start(record)
    snap = pathlib.Path(found["snapshot"])
    m = json.loads(snap.read_text())
    m.update(brain_start=start, seconds=round(m["t1_epoch"] - start, 3))
    m["record"] = cut_record(record, m["seconds"], snap.parent / "run.jsonl.gz")
    snap.write_text(json.dumps(m))
    evdir = pathlib.Path(found["evidence"])
    spent = (evdir / "models.json").read_text()       # reuse books the calls at $0; they were paid
    ev = see.see(snap, evdir, reuse=True)
    (evdir / "models.json").write_text(spent)
    reading, hit = prove.contact_of(ev)
    at = ev["fall"]["first"] or hit
    found.update(incident_s=at and round(at["brain_s"], 3), brain_start_correction_s=round(start - feed.brain_start, 3))
    return start


def live(brain, seconds, cam, out, with_loop, port=8090, settle=10):
    env = sim.sim_env(cam, port)
    out.mkdir(parents=True)
    events.begin(out, "watch", feed="live", brain=str(brain))
    record = sim.RUNS / f"run-{time.strftime('%Y%m%d-%H%M%S')}.jsonl.gz"
    samples, stop = [], threading.Event()
    threading.Thread(target=vram, args=(samples, stop), daemon=True).start()
    t_warm = models.warm_glimmer()
    subprocess.run([str(sim.SIM / "scripts" / "duck-sim")], cwd=sim.SIM, env=env, check=True, stdout=subprocess.DEVNULL)
    cap = Sidecar()
    proc = None
    try:
        sim.open_viser(port)
        cap.start()
        events.emit("feed", kind="live", clock="epoch", sidecar=cap.base, buffer_s=60)
        time.sleep(settle)                       # scene loaded, duck standing
        launched = time.time()
        proc = subprocess.Popen(["uv", "run", "-q", "microduck-brain", "--duration", str(seconds), "--record",
                                 str(record)], cwd=brain, env=env, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, start_new_session=True)
        events.emit("brain.start", at=launched, seconds=seconds)
        feed = LiveFeed(cap, brain, proc, launched)
        w = Watcher(feed, out)
        found = w.run()
        stopped_at = time.time()
        if proc.poll() is None:                  # an incident: the robot is stopped, as a person would
            os.killpg(proc.pid, signal.SIGINT)
        proc.wait(30)
        whole = cap.snapshot(time.time() - launched + 1.0, out / "whole")
    finally:
        if proc and proc.poll() is None:
            os.killpg(proc.pid, signal.SIGTERM)
        cap.stop(close_window=True)
        subprocess.run([str(sim.SIM / "scripts" / "duck-sim"), "down"], cwd=sim.SIM, env=env,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        stop.set()
    start = sim.brain_start(record)
    if found:
        finish_live(found, feed, record)
    span = whole["t1_epoch"] - whole["t0_epoch"]
    extra = {"feed": "live", "brain": str(brain), "record": str(record), "brain_start": start,
             "glimmer_warm_s": round(t_warm, 2), "incident": found,
             "stopped_brain_s": found and round(stopped_at - start, 3),
             "frame_lag_s": feed.lags and {"median": round(statistics.median(feed.lags), 3),
                                           "max": round(max(feed.lags), 3), "n": len(feed.lags)},
             "capture": {"clip": whole["path"], "seconds": round(span, 2), "frames": whole["frames"],
                         "frames_expected": round(span * whole["fps"])},
             "vram_mib": samples and {"peak": max(v for _, v in samples), "min": min(v for _, v in samples),
                                      "total": 24564, "samples": len(samples)}}
    doc = w.write(extra)
    if found and with_loop:
        doc["loop"] = loop(found, brain, out)
        (out / "watch.json").write_text(json.dumps(doc, indent=1))
    return doc


def clip(path, out, with_loop, lag=LAG):
    feed = ClipFeed(path, lag)
    out.mkdir(parents=True)
    events.begin(out, "watch", feed="clip", clip=str(path), brain=feed.meta.get("brain"))
    models.warm_glimmer()
    w = Watcher(feed, out)
    found = w.run()
    doc = w.write({"feed": "clip", "clip": str(feed.path), "brain": feed.meta.get("brain"), "incident": found})
    if found and with_loop:
        doc["loop"] = loop(found, pathlib.Path(feed.meta["brain"]), out)
        (out / "watch.json").write_text(json.dumps(doc, indent=1))
    return doc


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    a_live = sub.add_parser("live", help="simulator + sidecar, the brain started and watched")
    a_live.add_argument("--brain", default=str(TARGET))
    a_live.add_argument("--seconds", type=float, default=20)
    a_live.add_argument("--cam", default=f"{sim.CAM_DIR}/shots_incident.json")
    a_clip = sub.add_parser("clip", help="a recorded clip played back as the buffer")
    a_clip.add_argument("snapshot")
    a_clip.add_argument("--lag", type=float, default=LAG)
    for p in (a_live, a_clip):
        p.add_argument("--loop", action="store_true", help="start blinkflow.fix on a confirmed incident")
        p.add_argument("--out", help=f"run folder (default: {RUNS}/<stamp>)")
    a = ap.parse_args()
    out = pathlib.Path(a.out).expanduser() if a.out else RUNS / time.strftime("%Y%m%d-%H%M%S")
    if a.cmd == "live":
        doc = live(pathlib.Path(a.brain).expanduser(), a.seconds, a.cam, out, a.loop)
    else:
        doc = clip(a.snapshot, out, a.loop, a.lag)
    print(json.dumps({"out": str(out), "incident": doc["incident"] and {k: doc["incident"][k] for k in (
        "kind", "incident_s", "reading", "names")}, "summary": doc["summary"], "loop": doc.get("loop")}, indent=1))


if __name__ == "__main__":
    main()
