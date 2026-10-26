"""BlinkFlow sees: from a snapshot (clip + metadata) to measured evidence.

  1. keep the last continuous shot of the clip (the incident camera; earlier shots are cut away);
  2. Muse Glimmer, on this PC, names the robot and the object nearest to it from three frames;
     a name that is scenery (wall, floor...) or that SAM cannot find falls back to Muse Spark;
  3. SAM 3.1 tracks both names through the shot, in parallel; masks are decoded, not just boxes;
  4. per frame: the smallest pixel gap between the two masks; first contact = first frame at or
     under CONTACT_PX, placed on the brain's clock and the wall clock, with the brain ticks around it;
  5. writes evidence.json, evidence.png and models.json.

    python -m blinkflow.see ~/blinkflow-runs/clips/<id>.json [--out DIR]
    python -m blinkflow.see ~/blinkflow-runs/twin/<stamp>/meta.json
"""
import argparse
import concurrent.futures
import datetime
import gzip
import json
import pathlib
import subprocess

import numpy as np
from scipy import ndimage

from . import models, sam

CONTACT_PX = 2           # masks this close (or overlapping) count as touching
CUT_SCALE = (160, 125)
SCENERY = ("wall", "floor", "ground", "background", "shadow", "sky", "ceiling", "grid", "tile", "room")

NAMING_PROMPT = (
    "These are {n} frames, in time order, from one fixed camera shot of a robot simulator. "
    "Name the objects as short noun phrases a segmentation model can search for: colour + object, "
    "1-3 words (good: \"white robot\", \"purple box\"). Do not name the floor, walls, shadows or the "
    "background. Say which phrase is the robot and which object is closest to the robot. "
    "Reply only with JSON: {{\"objects\": [\"...\"], \"robot\": \"...\", \"nearest\": \"...\"}}")


# ── snapshot ─────────────────────────────────────────────────────────────────
def load_snapshot(path):
    """Normalise a sidecar snapshot (<id>.json) or a twin run (meta.json) to one shape:
    clip, per-frame brain time (s after the brain's first tick), per-frame epoch or None, brain log."""
    path = pathlib.Path(path).expanduser()
    m = json.loads(path.read_text())
    if "video_times" in m:                                    # twin: simulated time
        times = [t - m["brain_start_sim"] for t in m["video_times"]]
        return {"source": str(path), "kind": "twin", "clip": m["video"], "record": m["record"],
                "brain_time": times, "epoch": None, "clock": "simulated"}
    n = m["frames"]
    epoch = [m["t0_epoch"] + i / m["fps"] for i in range(n)]
    return {"source": str(path), "kind": "live", "clip": m["path"], "record": m.get("record"),
            "brain_time": [e - m["brain_start"] for e in epoch], "epoch": epoch, "clock": "wall"}


def gray_frames(clip):
    w, h = CUT_SCALE
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", clip, "-vf", f"scale={w}:{h},format=gray",
                          "-f", "rawvideo", "-"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(-1, h, w).astype(np.float32)


def last_shot(frames):
    """Index of the first frame after the last hard cut (0 if the clip is one shot)."""
    d = np.abs(np.diff(frames, axis=0)).mean(axis=(1, 2))
    if not len(d):
        return 0
    cuts = np.where((d > 20) & (d > 8 * (np.median(d) + 0.5)))[0]
    return int(cuts[-1]) + 1 if len(cuts) else 0


def trim(clip, start, out):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", clip, "-vf", f"select=gte(n\\,{start})",
                    "-fps_mode", "passthrough", "-c:v", "libx264", "-preset", "fast", "-crf", "18",
                    "-pix_fmt", "yuv420p", str(out)], check=True)


def jpeg(clip, n, width=640):
    return subprocess.run(["ffmpeg", "-v", "error", "-i", clip, "-vf", f"select=eq(n\\,{n}),scale={width}:-2",
                           "-frames:v", "1", "-q:v", "3", "-f", "image2", "-c:v", "mjpeg", "-"],
                          capture_output=True, check=True).stdout


def rgb(clip, n):
    out = subprocess.run(["ffmpeg", "-v", "error", "-i", clip, "-vf", f"select=eq(n\\,{n})", "-frames:v", "1",
                          "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True, check=True).stdout
    w, h = probe_size(clip)
    return np.frombuffer(out, np.uint8).reshape(h, w, 3)


def probe_size(clip):
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v", "-show_entries",
                          "stream=width,height", "-of", "csv=p=0", clip], capture_output=True, text=True).stdout
    w, h = out.strip().split(",")
    return int(w), int(h)


# ── naming ───────────────────────────────────────────────────────────────────
def check_names(reply):
    """Parsed reply -> (robot, nearest) or a reason they cannot be used."""
    try:
        d = json.loads(reply)
        robot, nearest = d["robot"].strip().lower(), d["nearest"].strip().lower()
    except (ValueError, KeyError, AttributeError, TypeError):
        return None, f"not the JSON asked for: {reply[:120]!r}"
    if not robot or not nearest or robot == nearest:
        return None, f"robot and nearest object must be two names: {robot!r}, {nearest!r}"
    for name in (robot, nearest):
        if any(w in name.split() for w in SCENERY):
            return None, f"{name!r} is scenery, not an object"
        if len(name.split()) > 4:
            return None, f"{name!r} is not a short noun phrase"
    return (robot, nearest), None


def name_objects(images, ledger, namers=("glimmer", "spark")):
    tried = []
    prompt = NAMING_PROMPT.format(n=len(images))
    for namer in namers:
        call = models.glimmer if namer == "glimmer" else models.spark
        reply = call(prompt, images, ledger, "name the robot and the object nearest to it")
        names, why = check_names(reply)
        tried.append({"namer": namer, "reply": reply, "rejected": why})
        if names:
            return names, namer, tried
    raise RuntimeError(f"no usable object names: {tried}")


def object_trouble(track, frame_area, n_frames):
    """Why a tracked object looks like the wrong thing, or None."""
    present = [f for f, inst in track["frames"].items() if inst]
    if len(present) < max(3, 0.1 * n_frames):
        return f"found in only {len(present)} of {n_frames} frames"
    areas = [sum(int(i.mask.sum()) for i in track["frames"][f]) for f in present]
    if np.median(areas) > 0.3 * frame_area:
        return f"covers {np.median(areas) / frame_area:.0%} of the frame: scenery, not an object"
    return None


# ── measuring ────────────────────────────────────────────────────────────────
def union(instances, size):
    w, h = size
    out = np.zeros((h, w), bool)
    for i in instances:
        x1, y1, x2, y2 = i.box
        out[y1:y2 + 1, x1:x2 + 1] |= i.mask.astype(bool)
    return out


def gap(a, b):
    """Smallest Euclidean pixel distance between two masks (0 when they overlap)."""
    if (a & b).any():
        return 0.0
    ys, xs = np.nonzero(a | b)
    y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
    a, b = a[y0:y1, x0:x1], b[y0:y1, x0:x1]
    return float(ndimage.distance_transform_edt(~b)[a].min())


def brain_ticks(record):
    if not record or not pathlib.Path(record).exists():
        return []
    with gzip.open(record, "rt") as f:
        next(f)
        rows = [json.loads(line) for line in f]
    t0 = rows[0]["t"]
    return [{"t": round(r["t"] - t0, 3), "state": r.get("state"), "cmd": r.get("cmd"), "why": r.get("why")}
            for r in rows]


def around(ticks, t, before=0.5, after=0.2):
    """Ticks from `before` s ahead of `t` to `after` s past it, collapsed to changes of state/command."""
    out, last = [], None
    for k in ticks:
        if t - before <= k["t"] <= t + after:
            key = (k["state"], json.dumps(k["cmd"]), k["why"])
            if key != last:
                out.append(k)
                last = key
    return out


# ── output ───────────────────────────────────────────────────────────────────
def draw(path, frame_rgb, robot_mask, object_mask, names, series, contact, clock):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, (top, bottom) = plt.subplots(2, 1, figsize=(9, 10), gridspec_kw={"height_ratios": [3, 1.3]})
    img = frame_rgb.astype(np.float32) / 255
    for mask, colour in ((robot_mask, (0.1, 0.55, 1.0)), (object_mask, (0.1, 0.85, 0.25))):
        if mask is not None:
            img[mask] = 0.45 * img[mask] + 0.55 * np.array(colour)
    top.imshow(img)
    top.set_axis_off()
    title = f"{names[0]} (blue)  ·  {names[1]} (green)"
    if contact:
        title += f"\nfirst contact: frame {contact['frame']}, {contact['brain_s']:.3f} s after the brain starts"
    top.set_title(title, fontsize=11)

    t = [p["brain_s"] for p in series]
    d = [p["gap_px"] for p in series]
    bottom.plot(t, d, color="#1f6fd1", lw=1.6)
    bottom.axhline(CONTACT_PX, color="#999", lw=0.8, ls="--")
    if contact:
        bottom.axvline(contact["brain_s"], color="#d14b1f", lw=1)
        bottom.annotate("first contact", (contact["brain_s"], max(d) * 0.85), color="#d14b1f",
                        xytext=(4, 0), textcoords="offset points", fontsize=9)
    bottom.set_xlabel(f"seconds after the brain's first tick ({clock} clock)")
    bottom.set_ylabel("gap between masks (px)")
    bottom.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)


def see(snapshot_path, out_dir, namers=("glimmer", "spark")):
    snap = load_snapshot(snapshot_path)
    out = pathlib.Path(out_dir).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    ledger = models.Ledger()

    start = last_shot(gray_frames(snap["clip"]))
    shot = out / "shot.mp4"
    trim(snap["clip"], start, shot)
    n = len(gray_frames(str(shot)))
    size = probe_size(str(shot))
    picks = [round((n - 1) * f) for f in (1 / 3, 2 / 3, 1.0)]
    images = [jpeg(str(shot), i) for i in picks]

    (robot, nearest), namer, tried = name_objects(images, ledger, namers)

    def run(concept, tag):
        r = sam.track(str(shot), concept, n, raw_path=out / f"sam-{tag}.txt")
        ledger.add("sam-3.1", "Meta Model API", f"track '{concept}'", r["seconds"], r["cost_usd"],
                   frames=n, frames_returned=len(r["frames"]), usage=r["usage"])
        return r

    with concurrent.futures.ThreadPoolExecutor(2) as pool:
        tr, to = pool.map(run, (robot, nearest), ("robot", "object"))

    trouble = object_trouble(to, size[0] * size[1], n)
    if trouble and "spark" in namers and namer != "spark":
        tried.append({"namer": "sam check", "rejected": f"{nearest!r}: {trouble}"})
        (robot2, nearest2), namer, more = name_objects(images, ledger, ("spark",))
        tried += more
        if nearest2 != nearest:
            nearest = nearest2
            to = run(nearest, "object")
            trouble = object_trouble(to, size[0] * size[1], n)
    names = (robot, nearest)

    series = []
    for f in range(n):
        a, b = tr["frames"].get(f), to["frames"].get(f)
        if not a or not b:
            continue
        g = gap(union(a, size), union(b, size))
        i = start + f
        series.append({"frame": i, "shot_frame": f, "brain_s": round(snap["brain_time"][i], 3),
                       "gap_px": round(g, 1)})
    hit = next((p for p in series if p["gap_px"] <= CONTACT_PX), None)

    ticks = brain_ticks(snap["record"])
    contact = None
    if hit:
        i = hit["frame"]
        contact = dict(hit)
        if snap["epoch"]:
            contact["wall_time"] = datetime.datetime.fromtimestamp(snap["epoch"][i]).astimezone().isoformat(
                timespec="milliseconds")
        tick = min(ticks, key=lambda k: abs(k["t"] - hit["brain_s"])) if ticks else None
        contact["brain_tick"] = tick
        contact["brain_ticks_before"] = around(ticks, hit["brain_s"])
    closest = min(series, key=lambda p: p["gap_px"]) if series else None

    key = hit or closest
    frame_rgb = rgb(str(shot), key["shot_frame"] if key else n - 1)
    rm = union(tr["frames"].get(key["shot_frame"], []), size) if key else None
    om = union(to["frames"].get(key["shot_frame"], []), size) if key else None
    draw(out / "evidence.png", frame_rgb, rm, om, names, series, contact, snap["clock"])

    evidence = {
        "snapshot": snap["source"], "kind": snap["kind"], "clock": snap["clock"], "clip": snap["clip"],
        "shot": {"first_frame": start, "frames": n, "size": list(size), "naming_frames": [start + p for p in picks]},
        "names": {"robot": robot, "object": nearest, "named_by": namer, "attempts": tried,
                  "object_warning": trouble},
        "tracking": {k: {"concept": t["concept"], "status": t["status"],
                         "frames_with_mask": sum(1 for v in t["frames"].values() if v),
                         "instances_max": max((len(v) for v in t["frames"].values()), default=0)}
                     for k, t in (("robot", tr), ("object", to))},
        "contact_px": CONTACT_PX,
        "first_contact": contact,
        "closest": closest,
        "gap_by_frame": series,
    }
    (out / "evidence.json").write_text(json.dumps(evidence, indent=1))
    ledger.write(out / "models.json")
    return evidence


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("snapshot")
    ap.add_argument("--out", help="default: <snapshot dir>/evidence-<snapshot name>")
    ap.add_argument("--namer", choices=("glimmer", "spark"), help="use only this namer")
    a = ap.parse_args()
    p = pathlib.Path(a.snapshot).expanduser()
    out = a.out or p.parent / f"evidence-{p.stem if p.stem != 'meta' else 'twin'}"
    ev = see(p, out, (a.namer,) if a.namer else ("glimmer", "spark"))
    print(json.dumps({"out": str(out), "names": ev["names"]["robot"] + " / " + ev["names"]["object"],
                      "named_by": ev["names"]["named_by"], "first_contact": ev["first_contact"] and
                      {k: ev["first_contact"].get(k) for k in ("frame", "brain_s", "gap_px", "wall_time")},
                      "closest": ev["closest"]}, indent=1))


if __name__ == "__main__":
    main()
