"""BlinkFlow sees: from a snapshot (clip + metadata) to measured evidence.

  1. keep the last continuous shot of the clip (the incident camera; earlier shots are cut away);
  2. Muse Glimmer, on this PC, names the robot and the object nearest to it from three frames;
     a name that is scenery (wall, floor...) or that SAM cannot find falls back to Muse Spark;
  3. SAM 3.1 tracks both names through the shot, in parallel; masks are decoded, not just boxes;
  4. per frame: the smallest pixel gap between the two masks, and how far the robot's feet are from
     the object's base (found from pixels: lit top face, darker side face, far end of the mask);
     two first contacts: masks touching, and masks touching with the feet at the base's depth;
     both placed on the brain's clock and the wall clock, with the brain ticks around them;
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
BASE_TOL = 0.1           # the robot's feet may be this fraction of the base's thickness short of it
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


def base_of(mask, frame_rgb):
    """Where the object stands on the floor, from pixels only.

    A box seen from above shows a lit top face and a darker side face running from it towards the
    floor. The direction from the top face to the side face is "down" in the picture (`u`, as
    (dy, dx)); the base is the far end of the mask along `u`, as thick as the top face, narrowed by
    how much the side face narrows towards the floor (perspective). Without two distinct faces,
    `u` is straight down the picture and the base is the last tenth of the mask."""
    ys, xs = np.nonzero(mask)
    pts = np.stack([ys, xs], 1).astype(float)
    lum = frame_rgb.astype(float).mean(2)
    lo, hi = np.percentile(lum[mask], [5, 95])
    top = mask & (lum > (lo + hi) / 2)
    labels, n = ndimage.label(top)
    if n > 1:
        top = labels == 1 + int(np.argmax(ndimage.sum(top, labels, range(1, n + 1))))
    side = mask & ~top
    if hi - lo >= 15 and top.sum() >= 0.1 * mask.sum() and side.sum() >= 0.1 * mask.sum():
        v = np.array(ndimage.center_of_mass(side)) - np.array(ndimage.center_of_mass(top))
        u = v / np.linalg.norm(v)
        w = np.array([-u[1], u[0]])
        tp = np.stack(np.nonzero(top), 1).astype(float)
        spread = lambda p: float(np.percentile(p, 98) - np.percentile(p, 2))
        s = pts @ u
        thick, width = spread(tp @ u), spread(tp @ w)
        end = s >= s.max() - 0.15 * thick
        thick *= min(1.0, spread((pts @ w)[end]) / width)
        method = "lit top face + side face"
    else:
        u = np.array([1.0, 0.0])
        s = pts @ u
        thick = 0.1 * (s.max() - s.min())
        method = "no distinct faces: bottom tenth of the mask"
    far = s.max() - thick
    footprint = np.zeros_like(mask)
    sel = s >= far
    footprint[ys[sel], xs[sel]] = True
    return {"u": u, "far": float(far), "near": float(s.max()), "thickness": float(thick),
            "method": method, "mask": footprint}


def feet_depth(robot_mask, base):
    """How far the robot's lowest point (along the object's "down") is past the base's far edge, in px."""
    ys, xs = np.nonzero(robot_mask)
    return float(np.percentile(np.stack([ys, xs], 1) @ base["u"], 99)) - base["far"]


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
def draw(path, frame_rgb, robot_mask, object_mask, base_mask, names, series, contacts, clock):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, (top, bottom) = plt.subplots(2, 1, figsize=(9, 10), gridspec_kw={"height_ratios": [3, 1.3]})
    img = frame_rgb.astype(np.float32) / 255
    for mask, colour in ((robot_mask, (0.1, 0.55, 1.0)), (object_mask, (0.1, 0.85, 0.25))):
        if mask is not None:
            img[mask] = 0.45 * img[mask] + 0.55 * np.array(colour)
    top.imshow(img)
    if base_mask is not None:
        top.contour(base_mask, levels=[0.5], colors=["#e8222e"], linewidths=1.4)
    top.set_axis_off()
    title = f"{names[0]} (blue)  ·  {names[1]} (green)  ·  its base, from pixels (red)"
    shown = contacts.get("base") or contacts.get("whole_mask")
    if shown:
        title += f"\nfirst contact: frame {shown['frame']}, {shown['brain_s']:.3f} s after the brain starts"
    top.set_title(title, fontsize=11)

    t = [p["brain_s"] for p in series]
    bottom.plot(t, [p["gap_px"] for p in series], color="#1f6fd1", lw=1.6, label="gap, whole masks (px)")
    if any(p.get("feet_depth_px") is not None for p in series):
        bottom.plot(t, [p.get("feet_depth_px") for p in series], color="#999", lw=1, ls=":",
                    label="robot's feet past the base's far edge (px)")
    bottom.axhline(CONTACT_PX, color="#bbb", lw=0.8, ls="--")
    for key, colour, label in (("whole_mask", "#8a5cd1", "masks touch"), ("base", "#d14b1f", "touch at the base")):
        c = contacts.get(key)
        if c:
            bottom.axvline(c["brain_s"], color=colour, lw=1, label=f"{label}: frame {c['frame']}")
    bottom.set_ylim(-40, max(80, max((p["gap_px"] for p in series), default=0) * 1.05))
    bottom.set_xlabel(f"seconds after the brain's first tick ({clock} clock)")
    bottom.legend(fontsize=8, frameon=False, loc="upper right")
    bottom.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)


def see(snapshot_path, out_dir, namers=("glimmer", "spark"), reuse=False):
    """`reuse`: take the names and SAM replies of an earlier run in `out_dir` instead of new calls."""
    snap = load_snapshot(snapshot_path)
    out = pathlib.Path(out_dir).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    ledger = models.Ledger()
    shot = out / "shot.mp4"

    start = last_shot(gray_frames(snap["clip"]))
    if not (reuse and shot.exists()):
        trim(snap["clip"], start, shot)
    n = len(gray_frames(str(shot)))
    size = probe_size(str(shot))
    picks = [round((n - 1) * f) for f in (1 / 3, 2 / 3, 1.0)]

    def run(concept, tag):
        r = sam.track(str(shot), concept, n, raw_path=out / f"sam-{tag}.txt")
        ledger.add("sam-3.1", "Meta Model API", f"track '{concept}'", r["seconds"], r["cost_usd"],
                   frames=n, frames_returned=len(r["frames"]), usage=r["usage"])
        return r

    if reuse:
        before = json.loads((out / "evidence.json").read_text())
        robot, nearest = before["names"]["robot"], before["names"]["object"]
        namer, tried, trouble = before["names"]["named_by"], before["names"]["attempts"], before["names"]["object_warning"]
        tr, to = ({"concept": c, "frames": sam.load_raw(out / f"sam-{tag}.txt"), "status": before["tracking"][k]["status"]}
                  for c, tag, k in ((robot, "robot", "robot"), (nearest, "object", "object")))
        prior = json.loads((out / "models.json").read_text())["calls"]
        for c in prior:
            ledger.calls.append({**c, "reused": True, "original_cost_usd": c.get("original_cost_usd", c["cost_usd"]),
                                 "cost_usd": 0.0})
    else:
        images = [jpeg(str(shot), i) for i in picks]
        (robot, nearest), namer, tried = name_objects(images, ledger, namers)
        with concurrent.futures.ThreadPoolExecutor(2) as pool:
            tr, to = pool.map(run, (robot, nearest), ("robot", "object"))
        trouble = object_trouble(to, size[0] * size[1], n)
        if trouble and "spark" in namers and namer != "spark":
            tried.append({"namer": "sam check", "rejected": f"{nearest!r}: {trouble}"})
            (_, nearest2), namer, more = name_objects(images, ledger, ("spark",))
            tried += more
            if nearest2 != nearest:
                nearest = nearest2
                to = run(nearest, "object")
                trouble = object_trouble(to, size[0] * size[1], n)
    names = (robot, nearest)

    # The object stands still in a fixed shot: find its base once, on the frame where it is seen
    # whole (largest mask among frames with the robot absent, or failing that, any frame).
    seen_obj = {f: v for f, v in to["frames"].items() if v}
    base = None
    if seen_obj:
        area = {f: sum(int(i.mask.sum()) for i in v) for f, v in seen_obj.items()}
        alone = [f for f in seen_obj if not tr["frames"].get(f)] or list(seen_obj)
        f_base = max(alone, key=area.get)
        base = base_of(union(seen_obj[f_base], size), rgb(str(shot), f_base))
        base["frame"] = start + f_base

    series = []
    for f in range(n):
        a, b = tr["frames"].get(f), to["frames"].get(f)
        if not a or not b:
            continue
        ra = union(a, size)
        i = start + f
        p = {"frame": i, "shot_frame": f, "brain_s": round(snap["brain_time"][i], 3),
             "gap_px": round(gap(ra, union(b, size)), 1)}
        if base:
            p["base_gap_px"] = round(gap(ra, base["mask"]), 1)
            p["feet_depth_px"] = round(feet_depth(ra, base), 1)
        series.append(p)

    # Two readings of "first contact". Whole masks: the two masks touch on screen. Base: they touch
    # while the robot's feet have reached the depth of the object's base, so a robot passing behind
    # a tall object (whose top hangs over its path on screen) does not count.
    contacts = {"whole_mask": next((p for p in series if p["gap_px"] <= CONTACT_PX), None), "base": None}
    if base:
        contacts["base"] = next((p for p in series if p["gap_px"] <= CONTACT_PX
                                 and p["feet_depth_px"] >= -BASE_TOL * base["thickness"]), None)

    ticks = brain_ticks(snap["record"])
    for key, hit in contacts.items():
        if not hit:
            continue
        c = dict(hit)
        if snap["epoch"]:
            c["wall_time"] = datetime.datetime.fromtimestamp(snap["epoch"][hit["frame"]]).astimezone().isoformat(
                timespec="milliseconds")
        if ticks:
            c["brain_tick"] = min(ticks, key=lambda k: abs(k["t"] - hit["brain_s"]))
            c["brain_ticks_before"] = around(ticks, hit["brain_s"])
        contacts[key] = c
    first = contacts["base"] or contacts["whole_mask"]
    closest = min(series, key=lambda p: p["gap_px"]) if series else None

    key = first or closest
    frame_rgb = rgb(str(shot), key["shot_frame"] if key else n - 1)
    rm = union(tr["frames"].get(key["shot_frame"], []), size) if key else None
    om = union(to["frames"].get(key["shot_frame"], []), size) if key else None
    draw(out / "evidence.png", frame_rgb, rm, om, base and base["mask"], names, series, contacts, snap["clock"])

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
        "base": base and {"method": base["method"], "from_frame": base["frame"],
                          "down": [round(float(x), 3) for x in base["u"]], "thickness_px": round(base["thickness"], 1),
                          "feet_tolerance_px": round(BASE_TOL * base["thickness"], 1)},
        "first_contact": first and {"reading": "base" if contacts["base"] else "whole_mask", **first},
        "contacts": contacts,
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
    ap.add_argument("--reuse", action="store_true", help="re-measure from the names and SAM replies already in --out")
    a = ap.parse_args()
    p = pathlib.Path(a.snapshot).expanduser()
    out = a.out or p.parent / f"evidence-{p.stem if p.stem != 'meta' else 'twin'}"
    ev = see(p, out, (a.namer,) if a.namer else ("glimmer", "spark"), a.reuse)
    print(json.dumps({"out": str(out), "names": ev["names"]["robot"] + " / " + ev["names"]["object"],
                      "named_by": ev["names"]["named_by"], "base": ev["base"],
                      "contacts": {k: c and {f: c.get(f) for f in ("frame", "brain_s", "gap_px", "wall_time")}
                                   for k, c in ev["contacts"].items()}}, indent=1))


if __name__ == "__main__":
    main()
