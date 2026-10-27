"""The film's impact shot: the first touch seen low from behind and to the right, slowed down, held still.

Scorer side, not part of the agent: it replays the target's brain in the twin and takes the first touch
(its moment and its point in the world) from the twin's own contact log (contacts.csv), which the agent
never reads. The camera is placed from that point and the robot's heading: `angle` degrees from straight
behind, towards the robot's right (where the box is), low, so the gap between the ankle and the box's edge
closes in view. Each clip is 4 s: 1x, then 1/4 up to the touch, a 0.5 s hold with a ring on the point of
contact, 1/4 again, 1x. Every slowed second is labelled.

    python3 tools/side_shot.py [--angles 30,38,45] [--plain] [--brain ~/duck-target] [--out C:/Users/sorin/blinkflow/footage]

Writes impact-<angle>-<date>.mp4 per angle and, with several angles, a contact sheet of them side by side
(impact-sheet-<date>.mp4 and .png). --plain leaves out every label but the ring (for the teaser, which draws its own).
Needs microduck_rl's interpreter for the twin (~/microduck_rl/.venv/bin/python).
"""
import argparse
import csv
import json
import math
import pathlib
import subprocess
import tempfile
import time

import numpy as np
from PIL import Image, ImageDraw, ImageFont

HOME = pathlib.Path.home()
REPO = pathlib.Path(__file__).resolve().parent.parent
TWIN_PY = HOME / "microduck_rl" / ".venv" / "bin" / "python"
FOOTAGE = pathlib.Path("/mnt/c/Users/sorin/blinkflow/footage")
FONT = "/mnt/c/Windows/Fonts/arialbd.ttf"
W, H = 1920, 1080
SRC_FPS, OUT_FPS = 200, 50      # every 5 ms physics step is a frame: 1/4 speed still plays at 50 fps
DIST, HEIGHT, FOV = 0.28, 0.07, 50   # m from the point of contact (further, a table leg comes between), height, vertical fov
# (source seconds relative to the touch, speed) per piece; the hold sits between the two slowed ones
BEFORE, SLOW_IN, SLOW_OUT, AFTER, HOLD, SLOW = 0.7, 0.3, 0.3, 0.4, 0.5, 4
RED = (255, 77, 94)


def twin(brain, out, camera=None, seconds=14):
    cmd = [str(TWIN_PY), "-m", "blinkflow.twin", "--brain", str(brain), "--scene", "box", "--seconds", str(seconds),
           "--out", str(out)]
    if camera:
        cmd += ["--video", "--camera", json.dumps(camera), "--size", f"{W}x{H}", "--fps", str(SRC_FPS)]
    r = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, check=True)
    return pathlib.Path(json.loads(r.stdout.strip().splitlines()[-1])["out"])


def touch(run):
    """The first touch from the twin's truth: (brain s, body, world point, heading of the walk)."""
    rows = list(csv.reader(open(run / "contacts.csv")))[1:]
    if not rows:
        raise SystemExit("no contact in this run: nothing to film")
    t, body, *at = rows[0]
    track = json.loads((run / "truth.json").read_text())["track"]
    a = min(track, key=lambda p: abs(p[0] - (float(t) - 0.6)))
    b = min(track, key=lambda p: abs(p[0] - float(t)))
    return float(t), body, np.array([float(v) for v in at]), math.atan2(b[2] - a[2], b[1] - a[1])


def camera(point, heading, angle):
    """`angle` degrees from straight behind the walk, towards its right; low, looking at the point."""
    back = np.array([-math.cos(heading), -math.sin(heading)])
    right = np.array([math.sin(heading), -math.cos(heading)])
    a = math.radians(angle)
    xy = point[:2] + DIST * (math.cos(a) * back + math.sin(a) * right)
    return {"pos": [round(float(xy[0]), 4), round(float(xy[1]), 4), HEIGHT],
            "look": [round(float(v), 4) for v in (point + [0, 0, 0.01])], "fov": FOV}


def project(cam, p):
    """Pixel of a world point in MuJoCo's free camera (vertical fov, z up)."""
    pos, look = np.array(cam["pos"]), np.array(cam["look"])
    f = (look - pos) / np.linalg.norm(look - pos)
    r = np.cross(f, [0, 0, 1.0]); r /= np.linalg.norm(r)
    u = np.cross(r, f)
    v = p - pos
    k = (H / 2) / math.tan(math.radians(cam["fov"]) / 2)
    return W / 2 + k * (v @ r) / (v @ f), H / 2 - k * (v @ u) / (v @ f)


def frames(video, t0, t1):
    """Decoded RGB frames of [t0, t1] seconds of the video, at its own rate."""
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t0:.4f}", "-i", str(video), "-t", f"{t1 - t0:.4f}",
                          "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(-1, H, W, 3)


def label(img, text, xy, size, fill=(255, 255, 255), anchor="la"):
    d = ImageDraw.Draw(img)
    font = ImageFont.truetype(FONT, size)
    box = d.textbbox(xy, text, font=font, anchor=anchor)
    d.rounded_rectangle((box[0] - 16, box[1] - 12, box[2] + 16, box[3] + 12), 10, fill=(0, 0, 0, 150))
    d.text(xy, text, font=font, fill=fill, anchor=anchor)


def clip(run, cam, hit, body, point, dest, plain=False):
    """The 4 s clip: 1x, 1/4, the hold with the ring, 1/4, 1x."""
    meta = json.loads((run / "meta.json").read_text())
    at = hit + meta["brain_start_sim"] - meta["video_times"][0]          # the touch, in video seconds
    src = frames(run / "twin.mp4", at - BEFORE - SLOW_IN, at + SLOW_OUT + AFTER + 0.05)
    hit_i = round(BEFORE * SRC_FPS + SLOW_IN * SRC_FPS)                  # the touch's frame in `src`
    step = SRC_FPS // OUT_FPS                                             # source frames per output frame at 1x
    plan = ([(i, "1x") for i in range(0, round(BEFORE * SRC_FPS), step)] +
            [(i, "slow") for i in range(round(BEFORE * SRC_FPS), hit_i, step // SLOW or 1)] +
            [(hit_i, "hold")] * round(HOLD * OUT_FPS) +
            [(i, "slow") for i in range(hit_i, hit_i + round(SLOW_OUT * SRC_FPS), step // SLOW or 1)] +
            [(i, "1x") for i in range(hit_i + round(SLOW_OUT * SRC_FPS), min(len(src), hit_i + round((SLOW_OUT + AFTER) * SRC_FPS)), step)])
    cx, cy = project(cam, point)
    where = f"first touch · {body.replace('_', ' ')} · {hit:.2f} s (the twin's contact log)"
    enc = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
                            "-r", str(OUT_FPS), "-i", "-", "-an", "-c:v", "libx264", "-preset", "slow", "-crf", "18",
                            "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(dest)], stdin=subprocess.PIPE)
    held = 0
    for i, how in plan:
        img = Image.fromarray(src[min(i, len(src) - 1)]).convert("RGBA")
        over = Image.new("RGBA", img.size, (0, 0, 0, 0))
        d = ImageDraw.Draw(over)
        if how == "hold" or (how == "slow" and i >= hit_i and i < hit_i + 12):
            # the ring: grows in over the hold, then fades through the first slowed frames after it
            g = min(1.0, held / (HOLD * OUT_FPS * 0.5)) if how == "hold" else 1.0
            fade = 1.0 if how == "hold" else 1 - (i - hit_i) / 12
            r = 26 + 34 * g
            d.ellipse((cx - r, cy - r, cx + r, cy + r), outline=RED + (int(255 * fade),), width=7)
            held += how == "hold"
        if not plain:
            label(over, "the same brain, replayed in the twin", (60, 60), 34)
            if i >= hit_i:
                label(over, where, (W / 2, H - 90), 44, anchor="ms")
        if how in ("slow", "hold") and not plain:
            label(over, "paused" if how == "hold" else "¼× speed", (W - 60, 60), 40, fill=(217, 194, 255), anchor="ra")
        enc.stdin.write(Image.alpha_composite(img, over).convert("RGB").tobytes())
    enc.stdin.close()
    enc.wait()
    return round(len(plan) / OUT_FPS, 2), (round(cx), round(cy))


def sheet(clips, angles, stamp, out):
    """The variants side by side, each with its angle on it: an mp4 and a still at the touch."""
    n = len(clips)
    tiles = "".join(f"[{i}:v]scale=1280:720,drawtext=fontfile={FONT}:text='{chr(65 + i)} · {a}°':fontsize=44:"
                    f"fontcolor=white:box=1:boxcolor=black@0.6:boxborderw=12:x=24:y=h-th-24[t{i}];"
                    for i, a in enumerate(angles))
    graph = tiles + "".join(f"[t{i}]" for i in range(n)) + f"hstack=inputs={n}[v]"
    ins = [x for c in clips for x in ("-i", str(c))]
    mp4, png = out / f"impact-sheet-{stamp}.mp4", out / f"impact-sheet-{stamp}.png"
    subprocess.run(["ffmpeg", "-v", "error", "-y", *ins, "-filter_complex", graph, "-map", "[v]", "-an",
                    "-c:v", "libx264", "-preset", "slow", "-crf", "18", "-pix_fmt", "yuv420p", str(mp4)], check=True)
    hold_at = (BEFORE + SLOW_IN * SLOW + HOLD * 0.8)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{hold_at:.2f}", "-i", str(mp4), "-frames:v", "1", str(png)],
                   check=True)
    return mp4, png


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--brain", default=str(HOME / "duck-target"))
    ap.add_argument("--angles", default="30,38,45", help="degrees from straight behind, towards the right")
    ap.add_argument("--plain", action="store_true", help="no labels, only the ring (the teaser draws its own)")
    ap.add_argument("--out", default=str(FOOTAGE))
    a = ap.parse_args()
    out = pathlib.Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M")
    angles = [float(x) for x in a.angles.split(",")]
    made = []
    with tempfile.TemporaryDirectory() as tmp:
        hit, body, point, heading = touch(twin(a.brain, pathlib.Path(tmp) / "probe"))
        for ang in angles:
            cam = camera(point, heading, ang)
            run = twin(a.brain, pathlib.Path(tmp) / f"a{ang:g}", cam)
            h2, b2, p2, _ = touch(run)
            assert (h2, b2) == (hit, body) and np.allclose(p2, point), "the twin is not deterministic"
            dest = out / f"impact-{ang:g}-{stamp}.mp4"
            seconds, px = clip(run, cam, hit, body, point, dest, a.plain)
            made.append({"angle": ang, "out": str(dest), "seconds": seconds, "ring_px": px, "camera": cam})
    result = {"first_touch_s": hit, "body": body, "point": point.round(4).tolist(),
              "heading_deg": round(math.degrees(heading), 1), "clips": made}
    if len(made) > 1:
        result["sheet"] = [str(p) for p in sheet([m["out"] for m in made], angles, stamp, out)]
    print(json.dumps(result))


if __name__ == "__main__":
    main()
