"""BlinkFlow listens: the person says what they saw, and the loop starts from that moment.

Push-to-talk, in the sidecar: F9 held anywhere on the desktop records the microphone. The moment is the
press of the key, on BlinkFlow's clock, minus the time said in the sentence ("three seconds ago"): the
key carries the clock, the words carry the delay, and how long the person takes to speak does not matter.

  1. Muse Voice Transcribe (PUSH_TO_TALK: the key held down is the whole turn) -> the sentence;
  2. Muse Glimmer, on this PC, reads from it how long ago it happened, what happened (touched, fell) and
     what the robot touched, against a JSON schema; Muse Spark if Glimmer's answer cannot be used;
  3. the buffer from BEFORE s before that moment to AFTER s after it (never past the press + 1 s) is the
     snapshot; blinkflow.see names the robot and the object with the sentence as a hint, SAM 3.1 follows
     them, and only what the proof would also call an incident counts (prove.contact_of, or a fall), and
     only if what SAM followed as the robot moved (watch.motion): the watcher's rules;
  4. the existing loop (blinkflow.fix) on that snapshot, see's evidence reused, which asks the person
     "Fix it?" and "Keep the fix?" (--auto: no one is asked).

Typing is the fallback (--type): Enter is the key press, then the sentence is typed.

    python3 -m blinkflow.voice live [--brain DIR] [--seconds 30] [--type] [--auto] [--no-loop] [--mic NAME]
    python3 -m blinkflow.voice clip <snapshot> --press T (--wav FILE | --text "...") [--brain DIR] [--auto] [--no-loop]

clip: a recorded clip played on the wall clock as if it were the buffer (watch.ClipFeed); the key goes
down at brain time T and stays down for the length of the recording, which is then handled exactly as
one from the sidecar. Nothing past the window is read; nor are the simulator's contact log, the scene
files or the twin's own record.
"""
import argparse
import io
import json
import os
import pathlib
import signal
import subprocess
import sys
import threading
import time
import wave

from . import TARGET, events, fix, models, prove, see, sim, watch
from .capture import Sidecar

HOME = pathlib.Path.home()
REPO = pathlib.Path(__file__).resolve().parent.parent
RUNS = HOME / "blinkflow-runs" / "voice"
BEFORE, AFTER = 5.0, 3.0  # the window around the moment said; a person's "three seconds ago" is off by a second or two
MAX_AGO = 40.0            # the buffer keeps 60 s, a snapshot at most 50
KEY = "F9"

PARSE_PROMPT = (
    "A person watching a small walking robot in a simulator held down a key and said: \"{said}\". "
    "seconds_ago: how long before the key was pressed it happened, in seconds, a number: \"just now\", "
    "\"right now\" or no time said = 0, \"a second ago\" = 1, \"a couple of seconds ago\" = 2, \"about five "
    "seconds ago\" = 5. event: \"contact\" if the robot or a part of it touched, hit, bumped or kicked "
    "something; \"fall\" if it fell, tipped over, or fell into or off something; otherwise \"other\". "
    "robot: what they called the robot or the part of it they named. object: what it touched or fell "
    "into or off, in their words, or \"\" if they did not say. Reply only with JSON.")
PARSE_SCHEMA = {"type": "object",
                "properties": {"seconds_ago": {"type": "number"},
                               "event": {"type": "string", "enum": ["contact", "fall", "other"]},
                               "robot": {"type": "string"}, "object": {"type": "string"}},
                "required": ["seconds_ago", "event", "robot", "object"]}


def wav_seconds(data):
    with wave.open(io.BytesIO(data)) as w:
        return w.getnframes() / w.getframerate()


# ── what was said, and when ──────────────────────────────────────────────────
def parse(text, ledger):
    """The sentence -> (seconds_ago, event, robot, object), its reader, and what each reader answered."""
    tried = []
    prompt = PARSE_PROMPT.format(said=text.replace('"', "'"))
    for reader in ("glimmer", "spark"):
        purpose = "when it happened and what it touched, from the person's words"
        try:
            reply = (models.glimmer(prompt, [], ledger, purpose, PARSE_SCHEMA) if reader == "glimmer"
                     else models.spark(prompt, [], ledger, purpose))
            d = json.loads(reply)
            ago = float(d["seconds_ago"])
        except (OSError, ValueError, KeyError, TypeError) as e:
            tried.append({"reader": reader, "rejected": f"{type(e).__name__}: {e}"})
            continue
        if not 0 <= ago <= MAX_AGO:
            tried.append({"reader": reader, "reply": reply, "rejected": f"seconds_ago {ago} not in 0..{MAX_AGO}"})
            continue
        tried.append({"reader": reader, "reply": reply, "rejected": None})
        return {"seconds_ago": ago, "event": d.get("event", "other"), "robot": str(d.get("robot", "")).strip(),
                "object": str(d.get("object", "")).strip()}, reader, tried
    raise RuntimeError(f"could not read when it happened: {tried}")


def hear(u, ledger, out=None):
    """An utterance ({press, release, wav} or {press, release, text}) -> what was said and when it happened.
    None if nothing was said. The recording is kept in `out` as said.wav (the console draws it)."""
    t = time.time()
    events.emit("key", press=u["press"], release=u["release"], typed="text" in u)
    audio = None
    if "text" in u:
        text, audio_s, how = u["text"].strip(), None, "typed"
    else:
        if out:
            audio = pathlib.Path(out) / "said.wav"
            audio.write_bytes(u["wav"])
        text, audio_s = models.transcribe(u["wav"], ledger, "what the person said (push-to-talk)")
        how = models.VOICE
    t_heard = time.time()
    events.emit("said", text=text, heard_by=how, audio_s=audio_s, seconds=round(t_heard - t, 2),
                audio=audio and str(audio))
    if not text:
        return None
    p, reader, tried = parse(text, ledger)
    events.emit("read", **p, read_by=reader, seconds=round(time.time() - t_heard, 2),
                moment=round(u["press"] - p["seconds_ago"], 3))
    return {"said": text, "heard_by": how, "audio_s": audio_s, **p, "read_by": reader, "read_attempts": tried,
            "press": u["press"], "release": u["release"], "moment": round(u["press"] - p["seconds_ago"], 3),
            "transcribe_s": round(t_heard - t, 2), "read_s": round(time.time() - t_heard, 2)}


def window(h):
    return h["moment"] - BEFORE, min(h["moment"] + AFTER, h["press"] + 1.0)


# ── see it, and start the loop ───────────────────────────────────────────────
def confirm(snap, evdir, h, ledger):
    """blinkflow.see on the window, with the sentence as the namer's hint; the incident, by the watcher's
    rules, or None. The voice calls join the incident's models.json, so the loop's manifest has them."""
    t = time.time()
    ev = see.see(snap, evdir, said=h["said"])
    mfile = evdir / "models.json"
    calls = json.loads(mfile.read_text())["calls"]
    both = models.Ledger()
    both.calls = ledger.calls + calls
    both.write(mfile)
    mo = watch.motion(evdir, snap)
    names = [ev["names"]["robot"], ev["names"]["object"]]
    robot_ok = mo["moved"] and names[0] != names[1]
    reading, hit = prove.contact_of(ev)
    fall = ev["fall"]["first"]
    kind = None if not robot_ok else "fall" if fall else "contact" if hit else None
    at = fall or hit
    spoken = set(h["object"].lower().split()) - {"the", "a", "an", "its", "that", "this"}
    events.emit("confirmed", kind=kind, confirmed=kind is not None, names=names, robot_moved=mo["moved"],
                incident_s=at and round(at["brain_s"], 3), evidence=str(evdir), snapshot=str(snap))
    return {"kind": kind, "confirmed": kind is not None, "names": names, "robot_moved": mo["moved"],
            "object_as_said": h["object"], "names_agree": bool(spoken & set(names[1].split())) if spoken else None,
            "incident_s": round(at["brain_s"], 3) if at else None,
            "reading": (fall["reading"] if fall else reading) if at else None,
            "seconds": round(time.time() - t, 1), "evidence": str(evdir), "snapshot": str(snap),
            "see_cost_usd": round(sum(c["cost_usd"] or 0 for c in calls), 4)}


def loop(c, brain, out, auto, tty=None):
    """The existing loop on the snapshot, see's evidence reused. Asking: it runs on the terminal `tty`."""
    env = {**os.environ, "BLINKFLOW_TARGET": str(brain)}
    cmd = [sys.executable, "-m", "blinkflow.fix", c["snapshot"], "--evidence", c["evidence"], "--out", str(out / "fix")]
    t = time.time()
    if auto:
        with open(out / "fix.log", "w") as log:
            rc = subprocess.run(cmd + ["--auto"], cwd=REPO, env=env, stdout=log, stderr=subprocess.STDOUT).returncode
    else:
        rc = subprocess.run(cmd, cwd=REPO, env=env, stdin=tty).returncode
    r = {"started": True, "asked": not auto, "rc": rc, "seconds": round(time.time() - t, 1), "run": str(out / "fix")}
    done = out / "fix" / "fix.json"
    if done.exists():
        d = json.loads(done.read_text())
        r.update(fixed=d.get("fixed"), kept=d.get("kept"), attempts=len(d.get("attempts", [])),
                 answers=d.get("answers"), stopped=d.get("stopped"))
    return r


def tell(h, c):
    """What BlinkFlow understood, in two lines on the terminal."""
    print(f"heard: \"{h['said']}\" -> {h['event']}, {h['seconds_ago']:g} s before the key", flush=True)
    if c is None:
        return
    if c["confirmed"]:
        print(f"seen: the {c['names'][0]} {'fell off' if c['kind'] == 'fall' else 'touched'} the {c['names'][1]} at "
              f"t = {c['incident_s']:.2f} s ({c['reading']} reading; you said t = {h['moment_brain_s']:.2f} s)", flush=True)
    else:
        print(f"seen: SAM 3.1 shows no contact or fall of the {c['names'][0]} and the {c['names'][1]} between "
              f"t = {c['window_brain_s'][0]:.2f} and {c['window_brain_s'][1]:.2f} s; nothing to fix", flush=True)


def finish(out, doc, h, c, brain, with_loop, auto, tty=None):
    doc.update(heard=h, incident=c)
    if c and c["confirmed"] and with_loop:
        (out / "voice.json").write_text(json.dumps(doc, indent=1))
        doc["loop"] = loop(c, brain, out, auto, tty)
    (out / "voice.json").write_text(json.dumps(doc, indent=1))
    return doc


# ── a recorded clip as the buffer ────────────────────────────────────────────
def clip(path, press, out, wav=None, text=None, with_loop=True, auto=False, brain=None, tty=None):
    """`brain`: the loop's target (default: the clip's own brain)."""
    out.mkdir(parents=True)
    events.begin(out, "voice", feed="clip", clip=str(path), brain=str(brain or ""))
    ledger = models.Ledger()
    models.warm_glimmer()
    feed = watch.ClipFeed(path)
    data = wav and pathlib.Path(wav).read_bytes()
    release = press + (wav_seconds(data) if data else 0.0)
    if release > feed.times[-1]:
        raise SystemExit(f"the clip ends at {feed.times[-1]:.2f} s, before the key is let go ({release:.2f} s)")
    feed.start()
    watch.tell_feed(feed)
    events.emit("listen", key=KEY, typed=not data)
    while feed.now() - feed.lag < release:
        time.sleep(0.02)
    u = {"press": press, "release": release, **({"wav": data} if data else {"text": text})}
    t = feed.now()
    events.clock_start(feed.t_start + release, "the person let go of the key")
    h = hear(u, ledger, out)
    doc = {"feed": "clip", "clip": str(feed.path), "brain": feed.meta.get("brain"), "clock": "brain time",
           "window_s": [BEFORE, AFTER]}
    if not h:
        print("heard nothing", flush=True)
        return finish(out, doc, None, None, None, False, auto)
    h.update(moment_brain_s=h["moment"], heard_after_release_s=round(feed.now() - t, 2))
    t0, t1 = window(h)
    events.emit("rewind", moment=h["moment"], window=[t0, t1], press=h["press"], release=h["release"])
    snap = feed.window(t0, t1, out / "window")
    events.emit("snapshot", snapshot=str(snap), video=str(out / "window" / "window.mp4"), window=[t0, t1])
    if brain:                       # a copy of the clip's brain: the loop reads and fixes that one
        m = json.loads(snap.read_text())
        m.update(recorded_brain=m.get("brain"), brain=str(pathlib.Path(brain).expanduser().resolve()))
        snap.write_text(json.dumps(m))
    c = confirm(snap, out / "window" / "evidence", h, ledger)
    c["window_brain_s"] = [round(t0, 3), round(t1, 3)]
    tell(h, c)
    return finish(out, doc, h, c, pathlib.Path(brain or feed.meta["brain"]).expanduser(), with_loop, auto, tty)


# ── live: the simulator, the sidecar's key ───────────────────────────────────
def typed(box, stop, tty):
    """The fallback: Enter is the key press, then the sentence."""
    print("Press Enter the moment you see it go wrong... ", end="", flush=True)
    tty.readline()
    press = time.time()
    print("What did you see? ", end="", flush=True)
    text = tty.readline()
    if not stop.is_set():
        box.append({"press": press, "release": time.time(), "text": text})


def live(brain, seconds, cam, out, with_loop=True, auto=False, type_=False, mic=None, port=8090, settle=10, tty=None):
    env = sim.sim_env(cam, port)
    out.mkdir(parents=True)
    events.begin(out, "voice", feed="live", brain=str(brain))
    ledger = models.Ledger()
    record = sim.RUNS / f"run-{time.strftime('%Y%m%d-%H%M%S')}.jsonl.gz"
    models.warm_glimmer()
    subprocess.run([str(sim.SIM / "scripts" / "duck-sim")], cwd=sim.SIM, env=env, check=True, stdout=subprocess.DEVNULL)
    cap = Sidecar()
    proc, h, snap, u = None, None, None, None
    try:
        sim.open_viser(port)
        health = cap.start(listen=not type_, mic=mic, key=KEY)
        if not type_ and not health.get("listening"):
            raise RuntimeError(f"the sidecar is not listening: {health}")
        skew = cap.skew()
        events.emit("feed", kind="live", clock="epoch", sidecar=cap.base, buffer_s=60)
        time.sleep(settle)
        launched = time.time()
        proc = subprocess.Popen(["uv", "run", "-q", "microduck-brain", "--duration", str(seconds), "--record",
                                 str(record)], cwd=brain, env=env, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, start_new_session=True)
        events.emit("brain.start", at=launched, seconds=seconds)
        events.emit("listen", key=KEY, typed=type_)
        print(f"The robot is walking ({seconds:g} s). " + ("Type what you see." if type_ else
              f"When it goes wrong, hold {KEY} and say what you saw and when, e.g. "
              "\"two seconds ago its right leg hit the purple box\"."), flush=True)
        box, stop = [], threading.Event()
        if type_:
            threading.Thread(target=typed, args=(box, stop, tty), daemon=True).start()
        last = 0
        while proc.poll() is None and not h:
            if type_:
                time.sleep(0.1)
                u = box.pop() if box else None
            else:
                u = cap.listen(last, timeout=1, skew=skew)
                if u:
                    last = u["id"]
                    u["wav"] = cap.utterance(u["id"])
            if u:
                events.clock_start(u["release"], "the person let go of the key" if not type_ else "the person typed it")
                h = hear(u, ledger, out)
                if not h:
                    print("heard nothing; hold the key and speak again", flush=True)
        stop.set()
        if h:
            t0, t1 = window(h)
            events.emit("rewind", moment=h["moment"], window=[t0, t1], press=h["press"], release=h["release"])
            snap_meta = cap.snapshot(t1 - t0, out / "window", end=t1)
            snap = out / "window" / "snapshot.json"
            snap.write_text(json.dumps(snap_meta))
            events.emit("snapshot", snapshot=str(snap), video=snap_meta["path"], window=[t0, t1],
                        t0_epoch=snap_meta["t0_epoch"], fps=snap_meta["fps"])
        if proc.poll() is None:               # heard: the robot is stopped, as a person would
            os.killpg(proc.pid, signal.SIGINT)
        proc.wait(30)
        events.emit("brain.stop", at=time.time())
    finally:
        if proc and proc.poll() is None:
            os.killpg(proc.pid, signal.SIGTERM)
        cap.stop(close_window=True)
        subprocess.run([str(sim.SIM / "scripts" / "duck-sim"), "down"], cwd=sim.SIM, env=env,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    start = sim.brain_start(record)
    doc = {"feed": "live", "brain": str(brain), "record": str(record), "brain_start": start, "clock": "WSL epoch",
           "heard_by": "typed" if type_ else f"push-to-talk ({KEY}), {health.get('mic')}", "window_s": [BEFORE, AFTER]}
    if not h:
        print("nothing was said", flush=True)
        return finish(out, doc, None, None, brain, False, auto, tty)
    # the brain has stopped and closed its log: the window gets its true start and the log up to its end
    m = json.loads(snap.read_text())
    m.update(brain=str(brain), brain_start=start, seconds=round(m["t1_epoch"] - start, 3))
    m["record"] = watch.cut_record(record, m["seconds"], snap.parent / "run.jsonl.gz")
    snap.write_text(json.dumps(m))
    h.update(moment_brain_s=round(h["moment"] - start, 3), press_brain_s=round(h["press"] - start, 3))
    events.emit("brain.clock", start=start, press_s=h["press_brain_s"], moment_s=h["moment_brain_s"])
    t0, t1 = window(h)
    c = confirm(snap, out / "window" / "evidence", h, ledger)
    c["window_brain_s"] = [round(t0 - start, 3), round(t1 - start, 3)]
    tell(h, c)
    return finish(out, doc, h, c, brain, with_loop, auto, tty)


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    a_live = sub.add_parser("live", help="simulator + sidecar; hold the key and say what you saw")
    a_live.add_argument("--brain", default=str(TARGET))
    a_live.add_argument("--seconds", type=float, default=30)
    a_live.add_argument("--cam", default=f"{sim.CAM_DIR}/shots_incident.json")
    a_live.add_argument("--type", action="store_true", help="type instead of speaking: Enter is the key press")
    a_live.add_argument("--mic", help="the microphone's dshow name (default: the first real one)")
    a_clip = sub.add_parser("clip", help="a recorded clip played back as the buffer; the key pressed at --press")
    a_clip.add_argument("snapshot")
    a_clip.add_argument("--press", type=float, required=True, help="brain time (s) the key goes down")
    said = a_clip.add_mutually_exclusive_group(required=True)
    said.add_argument("--wav", help="what was said, as recorded (mono 16-bit WAV, 16 or 24 kHz)")
    said.add_argument("--text", help="what was typed")
    a_clip.add_argument("--brain", help="the loop's target (default: the clip's brain)")
    for p in (a_live, a_clip):
        p.add_argument("--auto", action="store_true", help="the loop asks no one")
        p.add_argument("--no-loop", action="store_true", help="stop after seeing the incident")
        p.add_argument("--out", help=f"run folder (default: {RUNS}/<stamp>)")
    a = ap.parse_args()
    asks = not (a.auto or a.no_loop) or getattr(a, "type", False)
    if asks and not sys.stdin.isatty():
        raise SystemExit("no one at a terminal: run with --auto or --no-loop (and without --type)")
    tty = fix.terminal() if asks else None
    out = pathlib.Path(a.out).expanduser() if a.out else RUNS / time.strftime("%Y%m%d-%H%M%S")
    if a.cmd == "live":
        doc = live(pathlib.Path(a.brain).expanduser(), a.seconds, a.cam, out, not a.no_loop, a.auto, a.type, a.mic,
                   tty=tty)
    else:
        doc = clip(a.snapshot, a.press, out, a.wav, a.text, not a.no_loop, a.auto, a.brain, tty)
    h, c = doc.get("heard"), doc.get("incident")
    print(json.dumps({"out": str(out), "said": h and h["said"], "seconds_ago": h and h["seconds_ago"],
                      "moment_brain_s": h and h["moment_brain_s"],
                      "incident": c and {k: c[k] for k in ("kind", "incident_s", "reading", "names")},
                      "loop": doc.get("loop")}, indent=1))


if __name__ == "__main__":
    main()
