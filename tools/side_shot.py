"""The film's side shot: the first touch seen from the side, at the box's height, in slow motion.

Scorer side, not part of the agent: it replays the target's brain in the twin with a camera
perpendicular to the walk, low on the floor, framed on the right leg and the box's base, and takes
the moment of the first touch from the twin's own contact log (contacts.csv), which the agent never
reads. The seconds around it are slowed 4x; the label says so, and says where the time comes from.

    python3 tools/side_shot.py [--brain ~/duck-target] [--out C:/Users/sorin/blinkflow/footage]

Needs microduck_rl's interpreter for the twin (~/microduck_rl/.venv/bin/python).
"""
import argparse
import csv
import json
import pathlib
import subprocess
import tempfile
import time

HOME = pathlib.Path.home()
REPO = pathlib.Path(__file__).resolve().parent.parent
TWIN_PY = HOME / "microduck_rl" / ".venv" / "bin" / "python"
FOOTAGE = pathlib.Path("/mnt/c/Users/sorin/blinkflow/footage")
FONT = "/mnt/c/Windows/Fonts/arialbd.ttf"
# The robot walks +x (heading ~15 deg left) past demo_box, whose side faces its right leg; the camera
# stands on the robot's left, at the box's base height, looking across the walk at the touch.
CAMERA = {"pos": [0.72, 0.86, 0.075], "look": [0.86, 0.29, 0.1], "fov": 40}
FPS = 200                       # every 5 ms physics step: a 4x slow motion still plays at 50 fps
SLOW, BEFORE, SLOW_FROM, SLOW_TO, AFTER = 4, 3.5, 0.6, 0.5, 1.2


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--brain", default=str(HOME / "duck-target"))
    ap.add_argument("--camera", default=json.dumps(CAMERA))
    ap.add_argument("--out", default=str(FOOTAGE))
    a = ap.parse_args()
    out = pathlib.Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        r = subprocess.run([str(TWIN_PY), "-m", "blinkflow.twin", "--brain", a.brain, "--scene", "box", "--seconds", "14", "--video",
                            "--camera", a.camera, "--size", "1920x1080", "--fps", str(FPS), "--out", tmp],
                           cwd=REPO, capture_output=True, text=True, check=True)
        run = pathlib.Path(json.loads(r.stdout.strip().splitlines()[-1])["out"])
        meta = json.loads((run / "meta.json").read_text())
        rows = list(csv.reader(open(run / "contacts.csv")))[1:]
        if not rows:
            raise SystemExit("no contact in this run: nothing to film")
        hit, body = float(rows[0][0]), rows[0][1]
        # video seconds of the touch: frame times are simulated seconds, the brain starts at brain_start_sim
        v0 = meta["video_times"][0]
        at = hit + meta["brain_start_sim"] - v0
        t0, s0, s1, t1 = at - BEFORE, at - SLOW_FROM, at + SLOW_TO, at + SLOW_TO + AFTER
        label = pathlib.Path(tmp) / "label.txt"
        label.write_text("side camera · the same brain, replayed in the twin")
        touch = pathlib.Path(tmp) / "touch.txt"
        touch.write_text(f"first touch · {body.replace('_', ' ')} · {hit:.2f} s (simulator contact log)")
        slow = pathlib.Path(tmp) / "slow.txt"
        slow.write_text(f"{'¼' if SLOW == 4 else f'1/{SLOW}'}× speed")
        txt = f"fontfile={FONT}:fontcolor=white:box=1:boxcolor=black@0.55:boxborderw=14"
        # the slowed piece's own clock: after setpts, its touch sits at SLOW_FROM*SLOW seconds
        hit_slow = SLOW_FROM * SLOW
        graph = (f"[0:v]split=3[a][b][c];"
                 f"[a]trim={t0:.3f}:{s0:.3f},setpts=PTS-STARTPTS[A];"
                 f"[b]trim={s0:.3f}:{s1:.3f},setpts={SLOW}*(PTS-STARTPTS),"
                 f"drawbox=x=0:y=0:w=iw:h=ih:color=0xff4d5e:t=18:enable='between(t,{hit_slow:.3f},{hit_slow + 0.6:.3f})',"
                 f"drawtext={txt}:textfile={touch}:fontsize=46:x=(w-tw)/2:y=h-150:enable='gte(t,{hit_slow:.3f})',"
                 f"drawtext={txt}:textfile={slow}:fontsize=40:fontcolor=0xd9c2ff:x=w-tw-60:y=60[B];"
                 f"[c]trim={s1:.3f}:{t1:.3f},setpts=PTS-STARTPTS,"
                 f"drawtext={txt}:textfile={touch}:fontsize=46:x=(w-tw)/2:y=h-150[C];"
                 f"[A][B][C]concat=n=3:v=1:a=0,fps=50,drawtext={txt}:textfile={label}:fontsize=34:x=60:y=60[v]")
        dest = out / f"side-{time.strftime('%Y%m%d-%H%M')}.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(run / "twin.mp4"),
                        "-filter_complex", graph, "-map", "[v]", "-an", "-c:v", "libx264", "-preset", "slow",
                        "-crf", "18", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(dest)], check=True)
    print(json.dumps({"out": str(dest), "first_touch_s": hit, "body": body,
                      "seconds": round(BEFORE - SLOW_FROM + (SLOW_FROM + SLOW_TO) * SLOW + AFTER, 2)}))


if __name__ == "__main__":
    main()
