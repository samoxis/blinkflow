"""BlinkFlow proves: the incident's scenario replayed in the twin, looked at again from pixels.

The brain is a pure function of its inputs and the twin runs on simulated time, so a replay with the
patched brain is the same scene with one thing changed. The replay is rendered from the incident's
fixed camera, SAM 3.1 follows the same robot and the same object as in the incident (no new naming),
and the verdict comes from the masks only: contact or not, and when.

    python3 -m blinkflow.prove <snapshot .json or twin meta.json> [--out DIR]

The simulator's contact log is never read here; tools/score_contact.py does that, as the scorer.
"""
import argparse
import json
import math
import pathlib
import subprocess
import time

from . import diagnose, see

HOME = pathlib.Path.home()
REPO = pathlib.Path(__file__).resolve().parent.parent
RL_PYTHON = HOME / "microduck_rl" / ".venv" / "bin" / "python"   # the twin needs mujoco + onnxruntime
TARGET = HOME / "duck-target"
MIN_ROBOT_FRAMES = 10     # the robot must be found in at least this many frames for a verdict (the fixed
                          # shot sees it only near the object, ~70 of 520 frames in the incident)
MIN_TRAVEL = 0.5          # ...and walk at least this fraction of the incident's distance
EXTRA_S = 8.0             # the replay runs this long past the incident's end


def scenario(snapshot_path):
    """What to replay: the twin's own settings, or for a live run the demo scene, for the incident's
    duration plus EXTRA_S. A fix that only slows the robot down would otherwise pass: the contact
    moves past the end of the clip (seen on the first fix, Oct 26). The twin is deterministic, so the
    first `seconds` of the longer replay are the incident's scenario unchanged."""
    m = json.loads(pathlib.Path(snapshot_path).expanduser().read_text())
    if "video_times" in m:
        return {"from": "twin", "scene": m["scene"], "settle": m["settle"], "seconds": m["seconds"] + EXTRA_S}
    return {"from": "live", "scene": None, "settle": 3.0, "seconds": m["seconds"] + EXTRA_S}   # sim.py: scene "demo"


def replay(scen, out, brain=TARGET):
    """Run the twin with the incident's camera shot rendered; returns the replay's meta.json."""
    out.mkdir(parents=True, exist_ok=True)
    args = [str(RL_PYTHON), "-m", "blinkflow.twin", "--brain", str(brain), "--settle", str(scen["settle"]),
            "--seconds", str(scen["seconds"]), "--video", "--out", str(out)]
    if scen["scene"]:
        args += ["--scene", scen["scene"]]
    # The twin prints its own contact count; that is ground truth, so its output is not read.
    subprocess.run(args, cwd=REPO, check=True, stdout=subprocess.DEVNULL)
    (meta,) = sorted(out.glob("*/meta.json"))
    return meta


def travel(record):
    """Distance walked (m), from the brain's odometry."""
    pts = [k["pos"] for k in diagnose.read_ticks(record) if k["pos"]]
    return sum(math.dist(a, b) for a, b in zip(pts, pts[1:]))


def verdict(ev, record, reference_travel=None):
    """Contact or not, from the masks. With the object's base found, only a touch at the base's depth
    counts (a tall object's top hangs over the robot's path on screen); without it, any touch.
    No verdict if the robot was not followed through the shot or barely walked."""
    c = ev["contacts"]
    reading = "base" if ev.get("base") else "whole_mask"
    hit = c[reading]
    found = ev["tracking"]["robot"]["frames_with_mask"]
    walked = travel(record)
    problems = []
    if found < MIN_ROBOT_FRAMES:
        problems.append(f"robot found in only {found} frames")
    if not ev["tracking"]["object"]["frames_with_mask"]:
        problems.append("object not found")
    if reference_travel and walked < MIN_TRAVEL * reference_travel:
        problems.append(f"robot walked {walked:.2f} m, the incident {reference_travel:.2f} m")
    closest = ev["closest"]
    return {"contact": hit is not None, "valid": not problems, "problems": problems, "reading": reading,
            "first_contact_s": hit and round(hit["brain_s"], 3), "first_contact_frame": hit and hit["frame"],
            "whole_mask_touch_s": c["whole_mask"] and round(c["whole_mask"]["brain_s"], 3),
            "closest_gap_px": closest and closest["gap_px"], "closest_s": closest and round(closest["brain_s"], 3),
            "robot_frames": found, "travel_m": round(walked, 3)}


def prove(snapshot, out, follow, reference_travel=None, brain=TARGET):
    """Replay the snapshot's scenario with the brain as it is now, look at it, give the verdict."""
    out = pathlib.Path(out)
    t = time.time()
    meta = replay(scenario(snapshot), out / "twin", brain)
    t_replay = time.time() - t
    ev = see.see(meta, out / "evidence", follow=follow)
    v = verdict(ev, json.loads(meta.read_text())["record"], reference_travel)
    v.update(meta=str(meta), evidence=str(out / "evidence"), replay_s=round(t_replay, 1),
             see_s=round(time.time() - t - t_replay, 1))
    (out / "verdict.json").write_text(json.dumps(v, indent=1))
    return v


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("snapshot", help="the incident's snapshot (.json from blinkflow.sim, or a twin meta.json)")
    ap.add_argument("--evidence", help="the incident's evidence dir (for the names to follow)")
    ap.add_argument("--out", default=str(HOME / "blinkflow-runs" / "proofs" / time.strftime("%Y%m%d-%H%M%S")))
    a = ap.parse_args()
    follow = None
    if a.evidence:
        n = json.loads((pathlib.Path(a.evidence).expanduser() / "evidence.json").read_text())["names"]
        follow = (n["robot"], n["object"])
    print(json.dumps(prove(a.snapshot, a.out, follow), indent=1))


if __name__ == "__main__":
    main()
