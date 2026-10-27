"""The 20 s teaser: the console in film mode on a real run, filmed headless at 1920x960 (a browser of its
own, never the Viser window), one subtitle line per shot burned in a band below it: 1920x1080, no sound.

    python3 tools/teaser.py EVENTS [--out C:/Users/sorin/blinkflow/footage]

EVENTS is a finished run's events.jsonl. Every number in a subtitle is read from that stream. The shots:
the first touch slowed down with the magnifier, the 60 s bar rewound to the moment, SAM 3.1's masks,
the cause in three rows, the proof's 1 -> 0. Needs Playwright with Google Chrome (h264).
"""
import argparse
import base64
import json
import pathlib
import shutil
import socket
import subprocess
import sys
import tempfile
import time

from playwright.sync_api import sync_playwright

REPO = pathlib.Path(__file__).resolve().parent.parent
FOOTAGE = pathlib.Path("/mnt/c/Users/sorin/blinkflow/footage")
FONT = "/mnt/c/Windows/Fonts/arialbd.ttf"
FPS = 30
PAGE_H, BAND = 960, 120          # the console at 1920x960, the subtitles in a band of their own below it
BG = "0x0a0b0e"                  # the console's --bg


def facts(events):
    """What the subtitles say, from the stream only."""
    last = lambda t: [e for e in events if e["type"] == t][-1:] or [None]
    ev = next((e for e in reversed(events) if e["type"] == "evidence" and e.get("tag") == "incident"), {})
    said, rew = last("said")[0], last("rewind")[0]
    diag = last("diagnosis")[0] or {}
    code = diag.get("code") or {}
    verdicts = {e.get("tag"): e for e in events if e["type"] == "verdict"}
    before = verdicts.get("before") or {}
    after = next((v for k, v in reversed(list(verdicts.items())) if str(k).startswith("attempt")), {})
    return {"contact": (ev.get("first_contact") or {}).get("brain_s"), "names": ev.get("names") or {},
            "said": said and said.get("text"), "rewound": rew and rew["press"] - rew["moment"],
            "where": code and f"{code.get('file')}:{code.get('start')}",
            "before": 1 if before.get("incident") else 0, "after": 1 if after.get("incident") else 0}


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("events")
    ap.add_argument("--out", default=str(FOOTAGE))
    a = ap.parse_args()
    events = [json.loads(line) for line in pathlib.Path(a.events).read_text().splitlines() if line.strip()]
    f = facts(events)
    names = f["names"]
    robot, obj = names.get("robot", "robot"), names.get("object", "object")
    end = events[-1]["t"]
    rew_t = next(e["t"] for e in events if e["type"] == "snapshot")
    # (step, seconds, where the stream stands, what the shot does first, the subtitle)
    shots = [
        ("see", 5.0, end, "touch", f"SAM 3.1 finds the first touch at {f['contact']:.2f} s · slowed to ¼"),
        ("watch", 3.5, rew_t + 0.01, None, f"“{f['said']}” → the last 60 s, rewound {f['rewound']:.1f} s"),
        ("see", 3.5, end, "walk", f"SAM 3.1 follows the {robot} and the {obj}, every frame"),
        ("cause", 4.0, end, None, f"Muse Wonder: what the camera saw, what the robot believed, why · {f['where']}"),
        ("proof", 4.0, end, None, f"The fix, replayed on the same inputs: {f['before']} contact → {f['after']}"),
    ]
    out = pathlib.Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    port = free_port()
    server = subprocess.Popen([sys.executable, "-m", "blinkflow.console", "serve", "--port", str(port), "--events",
                               a.events], cwd=REPO, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="teaser-"))
    frames, marks = [], []
    try:
        with sync_playwright() as p:
            b = p.chromium.launch(channel="chrome", headless=True, args=["--autoplay-policy=no-user-gesture-required",
                                                                          "--hide-scrollbars"])
            pg = b.new_page(viewport={"width": 1920, "height": PAGE_H})
            for _ in range(50):
                try:
                    pg.goto(f"http://localhost:{port}/?film=1&script=1")
                    break
                except Exception:
                    time.sleep(0.2)
            pg.wait_for_function("window.BLINKFLOW && window.BLINKFLOW.events()", timeout=20000)
            # a first pass loads every video and mask, so the filmed pass never waits on them
            for step in ("see", "cause", "proof"):
                pg.evaluate(f"BLINKFLOW.seek({end}, '{step}')")
                pg.wait_for_timeout(3000)
            cdp = pg.context.new_cdp_session(pg)

            def frame(e):
                n = len(frames)
                path = tmp / f"{n:05d}.jpg"
                path.write_bytes(base64.b64decode(e["data"]))
                frames.append((e["metadata"]["timestamp"], path))
                cdp.send("Page.screencastFrameAck", {"sessionId": e["sessionId"]})

            cdp.on("Page.screencastFrame", frame)
            cdp.send("Page.startScreencast", {"format": "jpeg", "quality": 95, "maxWidth": 1920, "maxHeight": PAGE_H})
            for step, seconds, t, how, _ in shots:
                pg.evaluate(f"BLINKFLOW.seek({t}, '{step}')")
                if how:
                    # the see step's player: from just before the slowed touch, or from the walk towards it
                    pg.wait_for_function("BLINKFLOW.players().some(k => BLINKFLOW.player(k).slow)", timeout=10000)
                    pg.evaluate("""how => {
                      const p = BLINKFLOW.players().map(k => BLINKFLOW.player(k)).find(p => p.slow);
                      const f = how === 'touch' ? p.slow[0] - 15 : Math.max(0, p.slow[0] - 105);
                      p.video.currentTime = f / 30; p.video.play();
                    }""", how)
                pg.wait_for_timeout(700)               # the crossfade and the video settle
                marks.append(time.time())
                pg.wait_for_timeout(seconds * 1000)
            cdp.send("Page.stopScreencast")
            b.close()
    finally:
        server.terminate()
    # constant frame rate from the screencast's timestamps, then the shots cut out and subtitled
    lst = tmp / "frames.txt"
    with lst.open("w") as fh:
        for (t0, p0), (t1, _) in zip(frames, frames[1:] + [(frames[-1][0] + 1 / FPS, None)]):
            fh.write(f"file '{p0}'\nduration {max(t1 - t0, 0.001):.4f}\n")
    full = tmp / "full.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-vf", f"fps={FPS}",
                    "-c:v", "libx264", "-preset", "fast", "-crf", "14", "-pix_fmt", "yuv420p", str(full)], check=True)
    origin = frames[0][0]
    parts, graph = [], []
    for i, ((_, seconds, _, _, text), m) in enumerate(zip(shots, marks)):
        (tmp / f"sub{i}.txt").write_text(text)
        s0 = m - origin
        size = 40 if len(text) <= 78 else int(40 * 78 / len(text))
        graph.append(f"[0:v]trim={s0:.3f}:{s0 + seconds:.3f},setpts=PTS-STARTPTS,pad=1920:{PAGE_H + BAND}:0:0:{BG},"
                     f"drawtext=fontfile={FONT}:textfile={tmp / f'sub{i}.txt'}:fontsize={size}:fontcolor=white:"
                     f"x=(w-tw)/2:y={PAGE_H}+({BAND}-th)/2[s{i}]")
        parts.append(f"[s{i}]")
    graph.append(f"{''.join(parts)}concat=n={len(parts)}:v=1:a=0[v]")
    dest = out / f"teaser-{time.strftime('%Y%m%d-%H%M')}.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(full), "-filter_complex", ";".join(graph), "-map", "[v]",
                    "-an", "-c:v", "libx264", "-preset", "slow", "-crf", "18", "-pix_fmt", "yuv420p",
                    "-movflags", "+faststart", str(dest)], check=True)
    shutil.rmtree(tmp)
    print(json.dumps({"out": str(dest), "seconds": sum(s[1] for s in shots), "frames": len(frames), **f}))


if __name__ == "__main__":
    main()
