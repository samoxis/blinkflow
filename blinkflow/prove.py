"""BlinkFlow proves: the incident's scenario replayed in the twin, looked at again from pixels.

The brain is a pure function of its inputs and the twin runs on simulated time, so a replay with the
patched brain is the same scene with one thing changed. The replay is rendered from the incident's
fixed camera, SAM 3.1 follows the same robot and the same object as in the incident (no new naming),
and the verdict comes from the masks: contact or not, and when; for a fall, whether the robot's mask
tips over again, or the brain's own log says it fell.

    python3 -m blinkflow.prove <snapshot .json or twin meta.json> [--out DIR]

The simulator's contact log and the twin's record of falls are never read here; the scorers do that.
"""
import argparse
import concurrent.futures
import json
import math
import pathlib
import subprocess
import time

from . import TARGET, diagnose, events, see

HOME = pathlib.Path.home()
REPO = pathlib.Path(__file__).resolve().parent.parent
RL_PYTHON = HOME / "microduck_rl" / ".venv" / "bin" / "python"   # the twin needs mujoco + onnxruntime
MIN_ROBOT_FRAMES = 10     # the robot must be found in at least this many frames for a verdict (the fixed
                          # shot sees it only near the object, ~70 of 520 frames in the incident)
MIN_TRAVEL = 0.5          # ...and walk at least this fraction of the incident's distance
EXTRA_S = 8.0             # the replay runs this long past the incident's end
CONTROL_SCENES = ("low_cube", "ledge", "corner", "doorway")   # every twin scene but the box: the proof is that
CONTROL_S = 20.0          # each control replay's length (the scorer's control is as long)
CONTROL_EVERY = 3         # SAM 3.1 follows every 3rd frame of a control shot (9.5 fps): a third of the cost
CONTROL_WORKERS = 6       # render processes per control scene (four scenes at once on 24 threads)


def scenario(snapshot_path):
    """What to replay: the twin's own settings, or for a live run the demo scene, for the incident's
    duration plus EXTRA_S. A fix that only slows the robot down would otherwise pass: the contact
    moves past the end of the clip (seen on the first fix, Oct 26). The twin is deterministic, so the
    first `seconds` of the longer replay are the incident's scenario unchanged."""
    m = json.loads(pathlib.Path(snapshot_path).expanduser().read_text())
    if "video_times" in m:
        return {"from": "twin", "scene": m["scene"], "settle": m["settle"], "seconds": m["seconds"] + EXTRA_S}
    return {"from": "live", "scene": None, "settle": 3.0, "seconds": m["seconds"] + EXTRA_S}   # sim.py: scene "demo"


def replay(scen, out, brain=TARGET, nice=0, workers=None):
    """Run the twin with the incident's camera shot rendered; returns the replay's meta.json.
    `nice`: a replay rendered in the background yields the CPU to the work in front of it."""
    out.mkdir(parents=True, exist_ok=True)
    args = ["nice", "-n", str(nice)] * bool(nice) + [str(RL_PYTHON), "-m", "blinkflow.twin", "--brain", str(brain), "--settle", str(scen["settle"]),
            "--seconds", str(scen["seconds"]), "--video", "--out", str(out)]
    args += ["--workers", str(workers)] if workers else []
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


def contact_of(ev):
    """The reading a verdict trusts, and its first contact or None: the base's when the object's base
    was found (the body's when only it saw one), else the whole masks'."""
    c = ev["contacts"]
    reading = ("body" if c.get("body") and not c["base"] else "base") if ev.get("base") else "whole_mask"
    return reading, c[reading]


def verdict(ev, record, reference_travel=None, kind="contact"):
    """Did the incident happen again? `kind` is the incident's: "contact" or "fall".
    Contact, from the masks: with the object's base found, a touch at the base's depth counts, or failing
    that a touch with the robot within reach of the base (any part, e.g. its head); a tall object's top
    hanging over the robot's path on screen does not. Without a base, any touch.
    Fall: the robot's mask tips over, drops or vanishes mid-shot (pixels), or the brain logs a fall.
    No verdict if the robot was not followed through the shot or barely walked, or, for a contact,
    if the object was never found."""
    c = ev["contacts"]
    reading, hit = contact_of(ev)
    fall = (ev.get("fall") or {}).get("first")
    again = fall if kind == "fall" else hit
    found = ev["tracking"]["robot"]["frames_with_mask"]
    walked = travel(record)
    problems = []
    # A reply cut short (a 503 mid-stream) may hold the robot but not the frames of the contact.
    for k in ("robot", "object") if kind == "contact" else ("robot",):
        if (st := ev["tracking"][k].get("status", "completed")) != "completed":
            problems.append(f"SAM 3.1 tracking of the {k} {st}")
    if found < MIN_ROBOT_FRAMES:
        problems.append(f"robot found in only {found} frames")
    # A fall is read from the robot's mask and the brain's log; the hazard need not be segmented
    # (SAM 3.1 found no "yellow pit" in any frame: a hole in the floor is not a thing).
    if kind == "contact" and not ev["tracking"]["object"]["frames_with_mask"]:
        problems.append("object not found")
    if reference_travel and walked < MIN_TRAVEL * reference_travel:
        problems.append(f"robot walked {walked:.2f} m, the incident {reference_travel:.2f} m")
    closest = ev["closest"]
    return {"kind": kind, "incident": again is not None, "incident_s": again and round(again["brain_s"], 3),
            "fell_s": fall and round(fall["brain_s"], 3), "fall_reading": fall and fall["reading"],
            "contact": hit is not None, "valid": not problems, "problems": problems, "reading": reading,
            "first_contact_s": hit and round(hit["brain_s"], 3), "first_contact_frame": hit and hit["frame"],
            "whole_mask_touch_s": c["whole_mask"] and round(c["whole_mask"]["brain_s"], 3),
            "closest_gap_px": closest and closest["gap_px"], "closest_s": closest and round(closest["brain_s"], 3),
            "robot_frames": found, "travel_m": round(walked, 3)}


def render(snapshot, out, brain=TARGET, nice=0):
    """The snapshot's scenario replayed in the twin with the brain as it is now: (meta.json, seconds)."""
    t = time.time()
    scen = scenario(snapshot)
    events.emit("replay.start", tag=pathlib.Path(out).name, scene=scen["scene"] or "box", seconds=scen["seconds"],
                brain=str(brain))
    meta = replay(scen, pathlib.Path(out) / "twin", brain, nice)
    seconds = round(time.time() - t, 1)
    events.emit("replay.rendered", tag=pathlib.Path(out).name, video=json.loads(meta.read_text())["video"],
                seconds=seconds)
    return meta, seconds


def look(meta, out, follow, reference_travel=None, kind="contact", replay_s=None):
    """SAM 3.1 on a rendered replay, following `follow`; the verdict on an incident of this `kind`."""
    out = pathlib.Path(out)
    t = time.time()
    ev = see.see(meta, out / "evidence", follow=follow)
    v = verdict(ev, json.loads(meta.read_text())["record"], reference_travel, kind)
    v.update(meta=str(meta), evidence=str(out / "evidence"), replay_s=replay_s, see_s=round(time.time() - t, 1))
    (out / "verdict.json").write_text(json.dumps(v, indent=1))
    events.emit("verdict", tag=out.name, **v)
    return v


def prove(snapshot, out, follow, reference_travel=None, brain=TARGET, kind="contact"):
    """Replay the snapshot's scenario with the brain as it is now, look at it, give the verdict on an
    incident of this `kind`."""
    meta, seconds = render(snapshot, out, brain)
    return look(meta, out, follow, reference_travel, kind, seconds)


def every_nth(meta, n, out):
    """A twin replay with only every n-th frame of its shot (a cheaper look): a meta.json of its own."""
    m = json.loads(pathlib.Path(meta).read_text())
    out.mkdir(parents=True, exist_ok=True)
    video = out / "every.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", m["video"], "-vf", f"select=not(mod(n\\,{n}))",
                    "-fps_mode", "passthrough", "-c:v", "libx264", "-preset", "fast", "-crf", "18",
                    "-pix_fmt", "yuv420p", str(video)], check=True)
    m.update(video=str(video), video_times=m["video_times"][::n], every=n)
    p = out / "meta.json"
    p.write_text(json.dumps(m))
    return p


def control(out, brain=TARGET):
    """The brain as it is now in every other twin scene for CONTROL_S, judged from pixels only: Glimmer
    names what is near the robot in each shot, SAM 3.1 follows it and the robot (every CONTROL_EVERY-th
    frame), and the scene is clean when the proof's rules see no contact and no fall. A scene where the
    robot was not followed has no verdict and is not clean. {scene: {clean, why, names, ...}}"""
    out = pathlib.Path(out)
    events.emit("control.start", scenes=list(CONTROL_SCENES), seconds=CONTROL_S, every=CONTROL_EVERY)

    def render_one(scene):
        t = time.time()
        meta = replay({"scene": scene, "settle": 3.0, "seconds": CONTROL_S}, out / scene / "twin", brain,
                      workers=CONTROL_WORKERS)
        events.emit("control.rendered", scene=scene, video=json.loads(meta.read_text())["video"],
                    seconds=round(time.time() - t, 1))
        return every_nth(meta, CONTROL_EVERY, out / scene / "look"), round(time.time() - t, 1)

    def look_one(scene, meta):
        t = time.time()
        try:
            ev = see.see(meta, out / scene / "evidence", tag=f"control-{scene}")
        except RuntimeError as e:                    # nothing near the robot could be named or found
            return {"clean": False, "valid": False, "why": f"no verdict: {e}"[:300], "names": None}
        kind = "fall" if ev["names"]["object_is"] == "hazard" else "contact"
        v = verdict(ev, json.loads(meta.read_text())["record"], kind=kind)
        hit = v["contact"] and kind == "contact"
        why = ("; ".join(v["problems"]) if not v["valid"] else
               f"fell at t = {v['fell_s']:.2f} s ({v['fall_reading']})" if v["fell_s"] is not None else
               f"touched the {ev['names']['object']} at t = {v['first_contact_s']:.2f} s" if hit else
               "no contact, no fall" + (f"; closest gap {v['closest_gap_px']:.0f} px" if v["closest_gap_px"] is not None
                                        else ""))
        return {**v, "clean": v["valid"] and not hit and v["fell_s"] is None, "why": why,
                "names": [ev["names"]["robot"], ev["names"]["object"]], "evidence": str(out / scene / "evidence"),
                "see_s": round(time.time() - t, 1)}

    with concurrent.futures.ThreadPoolExecutor(len(CONTROL_SCENES)) as pool:
        rendered = dict(zip(CONTROL_SCENES, pool.map(render_one, CONTROL_SCENES)))
    with concurrent.futures.ThreadPoolExecutor(2) as pool:          # 2 at a time: SAM gets ~28 pieces at once
        looked = dict(zip(CONTROL_SCENES, pool.map(lambda s: look_one(s, rendered[s][0]), CONTROL_SCENES)))
    result = {}
    for s in CONTROL_SCENES:
        result[s] = {**looked[s], "render_s": rendered[s][1]}
        events.emit("control.scene", scene=s, **{k: result[s].get(k) for k in (
            "clean", "valid", "why", "names", "evidence", "render_s", "see_s", "robot_frames", "closest_gap_px")})
    (out / "control.json").write_text(json.dumps(result, indent=1))
    events.emit("control.done", clean=all(c["clean"] for c in result.values()),
                scenes={s: c["clean"] for s, c in result.items()})
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("snapshot", help="the incident's snapshot (.json from blinkflow.sim, or a twin meta.json)")
    ap.add_argument("--evidence", help="the incident's evidence dir (for the names to follow)")
    ap.add_argument("--out", default=str(HOME / "blinkflow-runs" / "proofs" / time.strftime("%Y%m%d-%H%M%S")))
    a = ap.parse_args()
    follow, kind = None, "contact"
    if a.evidence:
        e = json.loads((pathlib.Path(a.evidence).expanduser() / "evidence.json").read_text())
        follow, kind = (e["names"]["robot"], e["names"]["object"]), e.get("incident", "contact")
    print(json.dumps(prove(a.snapshot, a.out, follow, kind=kind), indent=1))


if __name__ == "__main__":
    main()
