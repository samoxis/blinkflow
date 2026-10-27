"""BlinkFlow sees: from a snapshot (clip + metadata) to measured evidence.

  1. keep the last continuous shot of the clip (the incident camera; earlier shots are cut away);
  2. Muse Glimmer, on this PC, names the robot and the object nearest to it from three frames;
     a name that is scenery (wall, floor...) or that SAM cannot find falls back to Muse Spark;
  3. SAM 3.1 tracks both names through the shot, in parallel; masks are decoded, not just boxes;
  4. per frame: the smallest pixel gap between the two masks, and how far the robot's feet are from
     the object's base (found from pixels: lit top face, darker side face, far end of the mask);
     three first contacts: masks touching; masks touching with the feet at the base's depth; and,
     when the base never sees one, masks touching with the robot close enough to the base for any
     part of it (a head, an arm) to reach the object;
     both placed on the brain's clock and the wall clock, with the brain ticks around them;
  5. a fall: the robot's mask drops and tips over within half a second, or vanishes mid-frame for good
     (pixels), or the brain logs one (its own log, which the user has anyway). The twin's own record of
     a fall is never read here; it is the scorer's;
  6. writes evidence.json, evidence.png and models.json.

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
import urllib.error

import numpy as np
from scipy import ndimage, spatial

from . import events, models, sam

CONTACT_PX = 2           # masks this close (or overlapping) count as touching
BASE_TOL = 0.1           # the robot's feet may be this fraction of the base's thickness short of it
REACH = 0.65             # any part: the robot's lowest point may be this many of its own heights short of
                         # the base (b10's jaw on the box read 0.5-0.8 on time; base runs unchanged)
MAX_TILT = 60            # "down" from the faces may lean this far from the picture's vertical (the real
                         # incidents' objects: 0-49 degrees, a pit's inner wall: 166 = 14 from straight up;
                         # a tall block's side face beside its top: 95)
SAME_OBJECT = 0.5        # an instance is the same still object when half of the smaller box is shared
CLEAR_PX = 20           # the robot's height on screen is measured where it is this far from the object
FALL_DROP = 0.6          # a fall, from pixels: the robot's top drops this many of its own heights...
FALL_TURN = 35           # ...and its long axis turns this many degrees, both within FALL_S
FALL_S = 0.5             # (b5-b7's falls into the pit: 0.8-1.4 heights and 65-90 deg; walking, turning,
                         # leaving the frame in 57 other shots: never both past 0.65 / 1 deg or 0.01 / 89 deg)
GONE_S = 0.5             # or its mask vanishes for good, this long before the shot ends, away from the
EDGE_PX = 10             # frame's edges and not shrinking (a robot walking out of view leaves at an edge)
CUT_SCALE = (160, 125)
PIECE_FRAMES = 90        # SAM 3.1 takes longer the more frames it answers for: a longer shot is tracked as
                         # pieces of about this many frames, all at once (a 658-frame replay: 44 s whole,
                         # 14 s in 180-frame pieces, 12 s in 90; the verdict and first contact unchanged)
WARMUP = 15              # every piece but the first starts this many frames early, so SAM's tracker has
                         # seen the scene before the frames that count; the warm-up frames are dropped
SCENERY = ("wall", "floor", "ground", "background", "shadow", "sky", "ceiling", "grid", "tile", "room")

HAZARD_WORDS = ("edge", "hole", "pit", "step", "steps", "stairs", "drop", "gap", "ledge", "trench", "ditch")

NAMING_PROMPT = (
    "These are {n} frames, in time order, from one fixed camera shot of a robot simulator. "
    "Name what a segmentation model should search for, as short noun phrases: colour + thing, 1-3 words "
    "(good: \"white robot\", \"purple box\", \"yellow pit\"). Two kinds: objects standing on the floor, and "
    "hazards in the floor itself that a walking robot could step or fall into: edges, holes, pits, steps, "
    "drop-offs. Do not name the plain floor, walls, shadows or the background. Say which phrase is the robot, "
    "which object or hazard is closest to the robot, and whether that one is an object or a hazard. "
    "Reply only with JSON: {{\"objects\": [\"...\"], \"hazards\": [\"...\"], \"robot\": \"...\", "
    "\"nearest\": \"...\", \"nearest_is\": \"object\" or \"hazard\"}}")


NAMING_SCHEMA = {
    "type": "object",
    "properties": {"objects": {"type": "array", "items": {"type": "string"}, "maxItems": 6},
                   "hazards": {"type": "array", "items": {"type": "string"}, "maxItems": 6},
                   "robot": {"type": "string"}, "nearest": {"type": "string"},
                   "nearest_is": {"type": "string", "enum": ["object", "hazard"]}},
    "required": ["objects", "hazards", "robot", "nearest", "nearest_is"]}


# ── snapshot ─────────────────────────────────────────────────────────────────
def load_snapshot(path):
    """Normalise a sidecar snapshot (<id>.json) or a twin run (meta.json) to one shape:
    clip, per-frame brain time (s after the brain's first tick), per-frame epoch or None, brain log."""
    path = pathlib.Path(path).expanduser()
    m = json.loads(path.read_text())
    for k in ("video", "record", "path"):          # a packed example names its files from the snapshot's folder
        if isinstance(m.get(k), str) and m[k].startswith("./"):
            m[k] = str(path.parent / m[k])
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


def trim(clip, start, out, end=None):
    """Frames `start`.. (to `end`, exclusive) of the clip, re-encoded once."""
    pick = f"select=gte(n\\,{start})" if end is None else f"select=between(n\\,{start}\\,{end - 1})"
    # timestamps from zero: a browser plays an mp4 that starts later from its first frame, frames off
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", clip, "-vf", pick + ",setpts=PTS-STARTPTS",
                    "-fps_mode", "passthrough", "-c:v", "libx264", "-preset", "fast", "-crf", "18",
                    "-pix_fmt", "yuv420p", str(out)], check=True)


def pieces(n):
    """(first frame sent, first frame kept, end) of each piece of an n-frame shot, in shot frames."""
    k = max(1, round(n / PIECE_FRAMES))
    edges = [round(i * n / k) for i in range(k + 1)]
    return [(max(0, a - WARMUP), a, b) for a, b in zip(edges, edges[1:])]


def cut_pieces(clip, start, plan, out):
    """Each piece cut from the source clip like shot.mp4 (one re-encode, not two), in parallel."""
    paths = [out / f"piece-{i}.mp4" for i in range(len(plan))]
    with concurrent.futures.ThreadPoolExecutor(len(plan)) as pool:
        list(pool.map(lambda pp: trim(clip, start + pp[1][0], pp[0], start + pp[1][2]), zip(paths, plan)))
    return paths


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
    """Parsed reply -> ((robot, nearest), "object" or "hazard") or (None, a reason they cannot be used)."""
    try:
        d = json.loads(reply)
        robot, nearest = d["robot"].strip().lower(), d["nearest"].strip().lower()
        hazards = [h.strip().lower() for h in d.get("hazards") or []]
    except (ValueError, KeyError, AttributeError, TypeError):
        return None, f"not the JSON asked for: {reply[:120]!r}"
    if not robot or not nearest or robot == nearest:
        return None, f"robot and nearest object must be two names: {robot!r}, {nearest!r}"
    words = set(nearest.split())
    kind = "hazard" if d.get("nearest_is") == "hazard" or nearest in hazards or words & set(HAZARD_WORDS) \
        else "object"
    for name in (robot, nearest):
        # "floor edge" names a hazard; a plain "floor" or "wall" names nothing to track
        if any(w in name.split() for w in SCENERY) and not (name == nearest and words & set(HAZARD_WORDS)):
            return None, f"{name!r} is scenery, not an object"
        if len(name.split()) > 4:
            return None, f"{name!r} is not a short noun phrase"
    return ((robot, nearest), kind), None


SAID_HINT = (" A person watching said: \"{said}\". The object or hazard they say the robot touched or fell "
             "into is the nearest one; name it as it looks on screen, not as they called it.")


def name_objects(images, ledger, namers=("glimmer", "spark"), said=None):
    """`said`: what the person who saw the incident said (blinkflow.voice); it tells the namer which one."""
    tried = []
    prompt = NAMING_PROMPT.format(n=len(images)) + (SAID_HINT.format(said=said.replace('"', "'")) if said else "")
    for namer in namers:
        purpose = "name the robot and the object or hazard nearest to it"
        try:
            reply = (models.glimmer(prompt, images, ledger, purpose, NAMING_SCHEMA) if namer == "glimmer"
                     else models.spark(prompt, images, ledger, purpose))
        except urllib.error.HTTPError as e:         # a local model that fails is a namer that did not answer
            tried.append({"namer": namer, "reply": None, "rejected": f"HTTP {e.code}: {e.read()[:200]!r}"})
            continue
        named, why = check_names(reply)
        tried.append({"namer": namer, "reply": reply, "rejected": why})
        if named:
            return named, namer, tried
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


def overlap(a, b):
    """How much two boxes (x1, y1, x2, y2) overlap, as a share of the smaller one."""
    w = min(a[2], b[2]) - max(a[0], b[0]) + 1
    h = min(a[3], b[3]) - max(a[1], b[1]) + 1
    if w <= 0 or h <= 0:
        return 0.0
    area = lambda r: (r[2] - r[0] + 1) * (r[3] - r[1] + 1)
    return w * h / min(area(a), area(b))


def objects(frames, n_frames):
    """One name can match several things ("gray block": a block and a wall). The camera and the objects
    stand still, so an object is a place on screen: each instance joins the object whose box it shares
    (SAM's instance ids restart in every piece, so they cannot say which is which), never two instances
    of one frame in the same object. Objects seen in too few frames to be a thing are dropped.
    [{"box": first box, "frames": {frame: [instances]}}], most frames first."""
    out = []
    for f in sorted(frames):
        used = set()
        for inst in sorted(frames[f] or [], key=lambda i: -int(i.mask.sum())):
            best = max((k for k in range(len(out)) if k not in used), default=None,
                       key=lambda k: overlap(out[k]["box"], inst.box))
            if best is None or overlap(out[best]["box"], inst.box) < SAME_OBJECT:
                out.append({"box": tuple(int(x) for x in inst.box), "frames": {}})
                best = len(out) - 1
            used.add(best)
            out[best]["frames"].setdefault(f, []).append(inst)
    keep = [o for o in out if len(o["frames"]) >= max(3, 0.1 * n_frames)] or out
    return sorted(keep, key=lambda o: -len(o["frames"]))


def same_object(instances, box):
    """The instances of one frame that are the object at `box` (see objects())."""
    return [i for i in instances or [] if overlap(box, i.box) >= SAME_OBJECT]


def bounds(mask):
    rows, cols = np.flatnonzero(mask.any(1)), np.flatnonzero(mask.any(0))
    return rows[0], rows[-1] + 1, cols[0], cols[-1] + 1


def edge(mask):
    """The mask's pixels with a 4-neighbour outside it, as (y, x) rows."""
    return np.argwhere(mask & ~ndimage.binary_erosion(mask))


def gap(a, b):
    """Smallest Euclidean pixel distance between two masks (0 when they overlap). The closest pair
    always lies on both edges, so only edge pixels inside the pair's bounding box are compared
    (the same value as a distance transform, 3x faster)."""
    if not (a.any() and b.any()):
        return float("inf")
    (ay0, ay1, ax0, ax1), (by0, by1, bx0, bx1) = bounds(a), bounds(b)
    y0, y1, x0, x1 = min(ay0, by0), max(ay1, by1), min(ax0, bx0), max(ax1, bx1)
    a, b = a[y0:y1, x0:x1], b[y0:y1, x0:x1]
    if (a & b).any():
        return 0.0
    return float(spatial.cKDTree(edge(b)).query(edge(a), k=1)[0].min())


def base_of(mask, frame_rgb):
    """Where the object stands on the floor, from pixels only.

    A box seen from above shows a lit top face and a darker side face running from it towards the
    floor. The direction from the top face to the side face is "down" in the picture (`u`, as
    (dy, dx)); the base is the far end of the mask along `u`, as thick as the top face, narrowed by
    how much the side face narrows towards the floor (perspective). Without two distinct faces, or
    when the side face lies more than MAX_TILT beside the top one rather than under it (or, for a pit's
    inner wall, over it), `u` is straight down the picture and the base is the last tenth of the mask."""
    ys, xs = np.nonzero(mask)
    pts = np.stack([ys, xs], 1).astype(float)
    lum = frame_rgb.astype(float).mean(2)
    lo, hi = np.percentile(lum[mask], [5, 95])
    top = mask & (lum > (lo + hi) / 2)
    labels, n = ndimage.label(top)
    if n > 1:
        top = labels == 1 + int(np.argmax(ndimage.sum(top, labels, range(1, n + 1))))
    side = mask & ~top
    faces = hi - lo >= 15 and top.sum() >= 0.1 * mask.sum() and side.sum() >= 0.1 * mask.sum()
    method = "no distinct faces: bottom tenth of the mask"
    if faces:
        v = np.array(ndimage.center_of_mass(side)) - np.array(ndimage.center_of_mass(top))
        u = v / np.linalg.norm(v)
        # The camera does not roll, so the world's down never runs sideways on screen: a side face
        # beside the top face (a tall block seen from its corner) does not say where the floor is.
        # Up the picture it can run: a pit's far inner wall shows above its rim.
        faces = abs(u[0]) >= np.cos(np.radians(MAX_TILT))
        method = "lit top face + side face" if faces else "side face beside the top: bottom tenth of the mask"
    if faces:
        w = np.array([-u[1], u[0]])
        tp = np.stack(np.nonzero(top), 1).astype(float)
        spread = lambda p: float(np.percentile(p, 98) - np.percentile(p, 2))
        s = pts @ u
        thick, width = spread(tp @ u), spread(tp @ w)
        end = s >= s.max() - 0.15 * thick
        thick *= min(1.0, spread((pts @ w)[end]) / width)
    else:
        u = np.array([1.0, 0.0])
        s = pts @ u
        thick = 0.1 * (s.max() - s.min())
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


def extent(robot_mask, u):
    """The robot's length on screen along the object's "down", in px."""
    ys, xs = np.nonzero(robot_mask)
    s = np.stack([ys, xs], 1) @ u
    return float(np.percentile(s, 99) - np.percentile(s, 1))


def shape(mask):
    """Top and bottom (px), bounding box, long axis and elongation of a mask, or None if it is a speck."""
    ys, xs = np.nonzero(mask)
    if len(ys) < 20:
        return None
    vals, vecs = np.linalg.eigh(np.cov(np.stack([ys, xs]).astype(float)))
    return {"top": float(np.percentile(ys, 1)), "bottom": float(np.percentile(ys, 99)),
            "box": [int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())],
            "axis": vecs[:, 1], "elong": float(np.sqrt(vals[1] / max(vals[0], 1e-9)))}


def fall_from_pixels(robot_frames, size, n, times):
    """First fall seen in the robot's mask: top dropping FALL_DROP of its height while its long axis
    turns FALL_TURN, within FALL_S; or the mask gone for good mid-frame. `times`: brain s per shot frame."""
    pts = [(f, times[f], sh) for f in range(n) if robot_frames.get(f)
           for sh in [shape(union(robot_frames[f], size))] if sh]
    for i, (f, s, a) in enumerate(pts):
        prev = [p for _, t, p in pts[:i] if s - t <= 0.5]
        if len(prev) < 5 or a["elong"] < 1.3:
            continue
        h = float(np.median([p["bottom"] - p["top"] for p in prev]))
        drop = turn = 0.0
        for g, t, b in pts[i + 1:]:
            if t - s > FALL_S:
                break
            drop = max(drop, b["top"] - a["top"])
            if b["elong"] >= 1.3:
                turn = max(turn, float(np.degrees(np.arccos(min(1.0, abs(float(a["axis"] @ b["axis"])))))))
            if drop >= FALL_DROP * h and turn >= FALL_TURN:
                return {"reading": "pixels", "how": "dropped and tipped over", "shot_frame": g, "brain_s": round(t, 3),
                        "from_shot_frame": f, "drop_px": round(drop, 1), "robot_px": round(h, 1),
                        "turn_deg": round(turn, 1)}
    if pts and times[n - 1] - times[pts[-1][0]] >= GONE_S:
        f, s, last = pts[-1]
        prev = [p for _, t, p in pts if s - 0.5 <= t < s]
        x0, y0, x1, y1 = last["box"]
        away = min(x0, y0, size[0] - 1 - x1, size[1] - 1 - y1) >= EDGE_PX
        whole = len(prev) >= 5 and last["bottom"] - last["top"] >= 0.5 * np.median([p["bottom"] - p["top"] for p in prev])
        if away and whole:
            return {"reading": "pixels", "how": "vanished mid-frame", "shot_frame": min(f + 1, n - 1),
                    "brain_s": round(times[min(f + 1, n - 1)], 3), "last_box": last["box"]}
    return None


def fall_from_log(ticks, times):
    """First brain tick within the shot whose reason mentions a fall."""
    for k in ticks:
        why = (k["why"] or "").lower()
        if times[0] <= k["t"] <= times[-1] and ("fall" in why or "fell" in why):
            f = int(np.argmin([abs(t - k["t"]) for t in times]))
            return {"reading": "brain log", "how": k["why"], "shot_frame": f, "brain_s": round(k["t"], 3),
                    "brain_tick": k}
    return None


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
def draw(path, frame_rgb, robot_mask, object_mask, base_mask, names, series, contacts, clock, fall=None):
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
    shown = contacts.get("base") or contacts.get("body") or contacts.get("whole_mask")
    if shown:
        title += f"\nfirst contact: frame {shown['frame']}, {shown['brain_s']:.3f} s after the brain starts"
    if fall:
        title += f"\nfall ({fall['reading']}): frame {fall['frame']}, {fall['brain_s']:.3f} s after the brain starts"
    top.set_title(title, fontsize=11)

    t = [p["brain_s"] for p in series]
    bottom.plot(t, [p["gap_px"] for p in series], color="#1f6fd1", lw=1.6, label="gap, whole masks (px)")
    if any(p.get("feet_depth_px") is not None for p in series):
        bottom.plot(t, [p.get("feet_depth_px") for p in series], color="#999", lw=1, ls=":",
                    label="robot's feet past the base's far edge (px)")
    bottom.axhline(CONTACT_PX, color="#bbb", lw=0.8, ls="--")
    for key, colour, label in (("whole_mask", "#8a5cd1", "masks touch"), ("base", "#d14b1f", "touch at the base"),
                               ("body", "#c9a227", "touch, any part")):
        c = contacts.get(key)
        if c:
            bottom.axvline(c["brain_s"], color=colour, lw=1, label=f"{label}: frame {c['frame']}")
    if fall:
        bottom.axvline(fall["brain_s"], color="#111", lw=1.4, label=f"fall ({fall['reading']}): frame {fall['frame']}")
    bottom.set_ylim(-40, max(80, max((p["gap_px"] for p in series), default=0) * 1.05))
    bottom.set_xlabel(f"seconds after the brain's first tick ({clock} clock)")
    bottom.legend(fontsize=8, frameon=False, loc="upper right")
    bottom.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)


def measure(robot_frames, obj_frames, size, shot, start, snap):
    """One still object against the robot, frame by frame: {base, series, contacts, height}."""
    # The object stands still in a fixed shot: find its base once, on the frame where it is seen
    # whole (largest mask among frames with the robot absent, or failing that, any frame).
    seen_obj = {f: v for f, v in obj_frames.items() if v}
    base = None
    if seen_obj:
        area = {f: sum(int(i.mask.sum()) for i in v) for f, v in seen_obj.items()}
        alone = [f for f in seen_obj if not robot_frames.get(f)] or list(seen_obj)
        f_base = max(alone, key=area.get)
        base = base_of(union(seen_obj[f_base], size), rgb(shot, f_base))
        base["frame"] = start + f_base

    series = []
    for f in sorted(seen_obj):
        a = robot_frames.get(f)
        if not a:
            continue
        ra = union(a, size)
        i = start + f
        p = {"frame": i, "shot_frame": f, "brain_s": round(snap["brain_time"][i], 3),
             "gap_px": round(gap(ra, union(seen_obj[f], size)), 1)}
        if base:
            p["base_gap_px"] = round(gap(ra, base["mask"]), 1)
            p["feet_depth_px"] = round(feet_depth(ra, base), 1)
            p["robot_px"] = round(extent(ra, base["u"]), 1)
        series.append(p)

    # Three readings of "first contact". Whole masks: the two masks touch on screen. Base: they touch
    # while the robot's feet have reached the depth of the object's base, so a robot passing behind
    # a tall object (whose top hangs over its path on screen) does not count. Any part: only when the
    # base sees nothing, they touch while the robot's lowest point is within REACH of its own height
    # (measured where it stands clear of the object) of the base: a head can reach the object's side
    # from there, a robot well behind it cannot. It is not the first reading because a leg on its way
    # to the base passes through that band ~0.8 s early.
    contacts = {"whole_mask": next((p for p in series if p["gap_px"] <= CONTACT_PX), None), "base": None, "body": None}
    height = None
    if base:
        contacts["base"] = next((p for p in series if p["gap_px"] <= CONTACT_PX
                                 and p["feet_depth_px"] >= -BASE_TOL * base["thickness"]), None)
        clear = [p["robot_px"] for p in series if p["gap_px"] > CLEAR_PX]
        height = float(np.median(clear)) if clear else None
        if height and not contacts["base"]:
            contacts["body"] = next((p for p in series if p["gap_px"] <= CONTACT_PX
                                     and p["feet_depth_px"] >= -REACH * height), None)
    return {"base": base, "series": series, "contacts": contacts, "height": height}


def see(snapshot_path, out_dir, namers=("glimmer", "spark"), reuse=False, follow=None, said=None, tag=None):
    """`reuse`: take the names and SAM replies of an earlier run in `out_dir` instead of new calls.
    `follow`: (robot, object) names to track as given, no naming (a replay follows the incident's).
    `said`: the person's own words about the incident, handed to the namer.
    `tag`: what this look is, in the event stream (default: "incident", or for a replay its folder's name)."""
    snap = load_snapshot(snapshot_path)
    out = pathlib.Path(out_dir).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    tag = tag or ("incident" if not follow else out.parent.name)
    ledger = models.Ledger()
    shot = out / "shot.mp4"

    start = last_shot(gray_frames(snap["clip"]))
    if not (reuse and shot.exists()):
        trim(snap["clip"], start, shot)
    n = len(gray_frames(str(shot)))
    size = probe_size(str(shot))
    picks = [round((n - 1) * f) for f in (1 / 3, 2 / 3, 1.0)]
    times = [snap["brain_time"][start + f] for f in range(n)]
    if not reuse:
        events.emit("see.start", tag=tag, evidence=str(out), shot=str(shot), clip=snap["clip"], frames=n,
                    size=list(size), fps=round((n - 1) / (times[-1] - times[0]), 3) if n > 1 else None,
                    times=[round(t, 3) for t in times], naming_frames=picks)

    plan = pieces(n)
    clips = [shot] if len(plan) == 1 else None

    def run(concept, tag):
        """`concept` tracked through the shot, its pieces in parallel; one reply, numbered as the shot."""
        def piece(i):
            lo, a, b = plan[i]
            r = sam.track(str(clips[i]), concept, b - lo)
            what = f"track '{concept}'" + (f" (frames {a}-{b - 1}, sent from {lo})" if len(plan) > 1 else "")
            if r["cached"]:                         # the same bytes, concept and parameters were paid for before
                ledger.add("sam-3.1", "cached", what, r["seconds"], 0.0, frames=b - lo,
                           frames_returned=len(r["frames"]), cache_key=r["cached"], original_seconds=r["original_seconds"])
            else:
                ledger.add("sam-3.1", "Meta Model API", what, r["seconds"], r["cost_usd"],
                           frames=b - lo, frames_returned=len(r["frames"]), usage=r["usage"], cache_key=r["cache_key"])
            events.emit("sam.piece", tag=tag, concept=concept, piece=i, pieces=len(plan), first=a, end=b,
                        found=sum(1 for f, v in r["frames"].items() if v and a <= lo + f < b))
            return r
        events.emit("sam.start", tag=tag, concept=concept, pieces=len(plan), frames=n)
        with concurrent.futures.ThreadPoolExecutor(len(plan)) as pool:
            parts = list(pool.map(piece, range(len(plan))))
        raw = "\n".join(sam.renumber(r["raw"], lo, range(a - lo, b - lo)) for r, (lo, a, b) in zip(parts, plan))
        (out / f"sam-{tag}.txt").write_text(raw)
        frames = {lo + f: inst for r, (lo, a, b) in zip(parts, plan) for f, inst in r["frames"].items()
                  if a <= lo + f < b}
        return {"concept": concept, "frames": frames,
                "status": next((r["status"] for r in parts if r["status"] != "completed"), "completed")}

    if reuse:
        before = json.loads((out / "evidence.json").read_text())
        robot, nearest = before["names"]["robot"], before["names"]["object"]
        kind = before["names"].get("object_is", "object")
        namer, tried, trouble = before["names"]["named_by"], before["names"]["attempts"], before["names"]["object_warning"]
        said = said or before["names"].get("said")
        tr, to = ({"concept": c, "frames": sam.load_raw(out / f"sam-{tag}.txt"), "status": before["tracking"][k]["status"]}
                  for c, tag, k in ((robot, "robot", "robot"), (nearest, "object", "object")))
        prior = json.loads((out / "models.json").read_text())["calls"]
        for c in prior:
            ledger.calls.append({**c, "reused": True, "original_cost_usd": c.get("original_cost_usd", c["cost_usd"]),
                                 "cost_usd": 0.0})
    else:
        if clips is None:
            clips = cut_pieces(snap["clip"], start, plan, out)
        images = [jpeg(str(shot), i) for i in picks]
        if follow:
            (robot, nearest), kind, namer, tried = follow, "as in the incident", "incident", []
        else:
            ((robot, nearest), kind), namer, tried = name_objects(images, ledger, namers, said)
        events.emit("named", tag=tag, robot=robot, object=nearest, object_is=kind, named_by=namer, said=said,
                    frames=picks)
        with concurrent.futures.ThreadPoolExecutor(2) as pool:
            tr, to = pool.map(run, (robot, nearest), ("robot", "object"))
        trouble = object_trouble(to, size[0] * size[1], n)
        if trouble and not follow and "spark" in namers and namer != "spark":
            tried.append({"namer": "sam check", "rejected": f"{nearest!r}: {trouble}"})
            ((_, nearest2), kind2), namer, more = name_objects(images, ledger, ("spark",), said)
            tried += more
            if nearest2 != nearest:
                nearest, kind = nearest2, kind2
                events.emit("named", tag=tag, robot=robot, object=nearest, object_is=kind, named_by=namer,
                            said=said, frames=picks, why=f"SAM 3.1: {trouble}")
                to = run(nearest, "object")
                trouble = object_trouble(to, size[0] * size[1], n)
    names = (robot, nearest)
    for f in out.glob("piece-*.mp4"):               # the replies are kept; the pieces are the shot again
        f.unlink()

    # One name can cover several still objects; each is measured on its own, with its own base, and
    # never as a union of two things. The object the verdict is about is the one the robot touches first
    # by the proof's reading, or failing that the one it comes closest to.
    measured = [dict(o, **measure(tr["frames"], o["frames"], size, str(shot), start, snap)) for o in
                objects(to["frames"], n)] or [dict(box=None, frames={}, **measure(tr["frames"], {}, size, str(shot), start, snap))]

    def first_by_proof(m):
        c = m["contacts"]
        return c["base"] or c["body"] if m["base"] else c["whole_mask"]

    chosen = min(measured, key=lambda m: (first_by_proof(m) is None,
                                           (first_by_proof(m) or {}).get("brain_s", 0),
                                           min((p["gap_px"] for p in m["series"]), default=float("inf"))))
    base, series, contacts, height = chosen["base"], chosen["series"], chosen["contacts"], chosen["height"]
    obj_frames = chosen["frames"]
    ticks = brain_ticks(snap["record"])
    falls = {"pixels": fall_from_pixels(tr["frames"], size, n, times), "brain_log": fall_from_log(ticks, times)}
    seen = [c for c in falls.values() if c]
    for c in seen:
        c["frame"] = start + c["shot_frame"]
    fall = {**falls, "first": min(seen, key=lambda c: c["brain_s"]) if seen else None}
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
    reading = next((k for k in ("base", "body", "whole_mask") if contacts[k]), None)
    first = reading and contacts[reading]
    closest = min(series, key=lambda p: p["gap_px"]) if series else None

    key = fall["first"] or first or closest
    frame_rgb = rgb(str(shot), key["shot_frame"] if key else n - 1)
    rm = union(tr["frames"].get(key["shot_frame"], []), size) if key else None
    om = union(obj_frames.get(key["shot_frame"], []), size) if key else None
    draw(out / "evidence.png", frame_rgb, rm, om, base and base["mask"], names, series, contacts, snap["clock"],
         fall["first"])

    evidence = {
        "snapshot": snap["source"], "kind": snap["kind"], "clock": snap["clock"], "clip": snap["clip"],
        "shot": {"first_frame": start, "frames": n, "size": list(size), "naming_frames": [start + p for p in picks]},
        "names": {"robot": robot, "object": nearest, "object_is": kind, "named_by": namer, "attempts": tried,
                  "object_warning": trouble, "said": said},
        "tracking": {k: {"concept": t["concept"], "status": t["status"],
                         "frames_with_mask": sum(1 for v in t["frames"].values() if v),
                         "instances_max": max((len(v) for v in t["frames"].values()), default=0)}
                     for k, t in (("robot", tr), ("object", to))},
        "object": {"box": chosen["box"], "frames": len(obj_frames), "objects_named": len(measured),
                   "others": [{"box": m["box"], "frames": len(m["frames"])} for m in measured if m is not chosen]},
        "contact_px": CONTACT_PX,
        "base": base and {"method": base["method"], "from_frame": base["frame"],
                          "down": [round(float(x), 3) for x in base["u"]], "thickness_px": round(base["thickness"], 1),
                          "feet_tolerance_px": round(BASE_TOL * base["thickness"], 1),
                          "robot_height_px": height and round(height, 1),
                          "reach_px": height and round(REACH * height, 1)},
        "incident": "fall" if fall["first"] else "contact",
        "fall": fall,
        "first_contact": first and {"reading": reading, **first},
        "contacts": contacts,
        "closest": closest,
        "gap_by_frame": series,
    }
    (out / "evidence.json").write_text(json.dumps(evidence, indent=1))
    ledger.write(out / "models.json")
    events.emit("evidence", tag=tag, evidence=str(out), shot=str(shot), image=str(out / "evidence.png"),
                sam={"robot": str(out / "sam-robot.txt"), "object": str(out / "sam-object.txt")},
                first_frame=start, frames=n, size=list(size), names=evidence["names"] | {"attempts": None},
                incident=evidence["incident"], first_contact=first and {k: first.get(k) for k in (
                    "frame", "shot_frame", "brain_s", "gap_px", "wall_time")} | {"reading": reading},
                fall=fall["first"] and {k: fall["first"].get(k) for k in ("reading", "how", "frame", "shot_frame",
                                                                          "brain_s")},
                closest=closest, frames_with_mask={k: v["frames_with_mask"] for k, v in evidence["tracking"].items()},
                object_box=chosen["box"], objects_named=len(measured),
                base=base and {k: base.get(k) for k in ("down", "thickness_px", "method")},
                series=[[p["shot_frame"], p["brain_s"], p["gap_px"]] for p in series])
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
                      "named_by": ev["names"]["named_by"], "base": ev["base"], "incident": ev["incident"],
                      "fall": ev["fall"]["first"] and {f: ev["fall"]["first"][f] for f in ("reading", "how", "frame", "brain_s")},
                      "contacts": {k: c and {f: c.get(f) for f in ("frame", "brain_s", "gap_px", "wall_time")}
                                   for k, c in ev["contacts"].items()}}, indent=1))


if __name__ == "__main__":
    main()
