"""BlinkFlow understands: from measured evidence to the cause in the target's code.

  1. key frames chosen from the evidence: ~1 s before first contact, ~0.5 s before, just before, contact;
     the masks, the object's base and the measured gap are drawn on each;
  2. Muse Glimmer, on this PC, says in one sentence what each key frame shows;
  3. the brain's ticks from the last ~3 s before contact, as a compact table (command, pose, depth);
  4. the target's source files and brain.toml, with line numbers;
  5. Muse Wonder reads it all and answers in JSON: the cause (file, function, lines), the evidence for
     it, its confidence, the direction of a fix (no patch) and a plain explanation;
  6. the answer is checked against what was sent: does the file, function and line range exist, and
     do the cited frames and log ticks exist? A diagnosis that cites no frame or no tick is flagged.

    python -m blinkflow.diagnose <evidence dir> [--model wonder|spark] [--runs N]
    python -m blinkflow.diagnose <evidence dir> --compare 3 [--control 1]

`--compare N` runs Wonder and Spark N times each on the same inputs and reports how often each gives
the same cause. `--control K` adds K runs per model that get the code and the complaint but none of
the evidence, to see whether the cause can be guessed from the code alone.
"""
import argparse
import base64
import collections
import gzip
import json
import math
import pathlib
import re

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy import ndimage

from . import models, sam, see

BEFORE_S = 3.0           # log window before contact
AFTER_S = 0.25
GRID_EVERY_S = 0.5       # full depth grids this often in the log window (plus at the key frames)
IMAGE_WIDTH = 960
MODELS = {"wonder": models.WONDER, "spark": models.SPARK}
EFFORT = "medium"
MAX_OUTPUT = 12000
TARGET_ROOT = pathlib.Path.home() / "duck-target"

DESCRIBE_PROMPT = (
    "This is one frame from a fixed camera in a robot simulator, {label}. The {robot} is a small "
    "two-legged walking robot; the {object} is an object near it. In one sentence, say what the robot "
    "is doing (walking, turning, standing; where its legs are) and where the {object} is in the picture "
    "relative to the robot (picture left or right, above or below, how close). Say left and right as seen in "
    "the picture, not from the robot's point of view. Reply only with JSON: {{\"sentence\": \"...\"}}")

INSTRUCTIONS = """You are debugging the brain of a small two-legged walking robot. The brain is a Python \
program: it reads an 8x8 depth sensor and the robot's pose and sends walking commands. Below are its \
source files and its configuration, with line numbers. After them comes an incident from the \
simulator: key frames from the camera (with segmentation masks and measured pixel gaps drawn on them, \
each also described in one sentence by a local vision model), per-frame measurements, and the brain's \
own log for the seconds before the incident.

Find the cause of the incident in this code: the place where the program does something that made the \
incident happen, or fails to do what would have prevented it.

Rules:
- Ground the diagnosis in the incident's evidence. Every claim about what happened cites a key frame \
(K1..K4), a measurement, or a log tick by its time t. Code is cited by file and line.
- Use the evidence to choose between the explanations the code alone would allow, and say which ones \
it rules out and why.
- If the evidence cannot tell two causes apart, say so and lower your confidence.
- The cause is one place: one file, one function, a line range of at most 30 lines (a config value \
in brain.toml counts as a place).
- Do not write a patch. Give the direction of the fix in one or two sentences.
- The explanation is for someone who has never seen the code: 2-3 sentences, no code identifiers.
Reply with JSON only."""

SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["observed", "cause", "evidence", "ruled_out", "confidence", "fix_direction", "explanation"],
    "properties": {
        "observed": {"type": "string", "description": "what happened, in the evidence's terms"},
        "cause": {"type": "object", "additionalProperties": False,
                  "required": ["file", "function", "lines", "what"],
                  "properties": {"file": {"type": "string"}, "function": {"type": "string"},
                                 "lines": {"type": "object", "additionalProperties": False,
                                           "required": ["start", "end"],
                                           "properties": {"start": {"type": "integer"}, "end": {"type": "integer"}}},
                                 "what": {"type": "string"}}},
        "evidence": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["source", "ref", "value", "shows"],
            "properties": {"source": {"type": "string", "enum": ["frame", "measurement", "log", "code"]},
                           "ref": {"type": "string", "description": "K1..K4, a log tick 't=...', or file:line"},
                           "value": {"type": "string"}, "shows": {"type": "string"}}}},
        "ruled_out": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["cause", "because"],
            "properties": {"cause": {"type": "string"}, "because": {"type": "string"}}}},
        "confidence": {"type": "number", "description": "0 to 1"},
        "fix_direction": {"type": "string"},
        "explanation": {"type": "string"},
    },
}


# ── key frames ───────────────────────────────────────────────────────────────
def key_frames(ev, snap):
    """(tag, label, clip frame) for ~1 s before contact, ~0.5 s before, just before (~0.1 s), contact."""
    c, start, n = ev["first_contact"], ev["shot"]["first_frame"], ev["shot"]["frames"]
    times = snap["brain_time"]

    def at(t):
        return min(range(start, start + n), key=lambda i: abs(times[i] - t))

    picks = [("1 s before contact", at(c["brain_s"] - 1.0)), ("0.5 s before contact", at(c["brain_s"] - 0.5)),
             ("just before contact", max(start, c["frame"] - 3)), ("first contact", c["frame"])]
    out, seen = [], set()
    for label, f in picks:
        if f not in seen:
            seen.add(f)
            out.append({"tag": f"K{len(out) + 1}", "label": label, "frame": f, "shot_frame": f - start,
                        "brain_s": round(times[f], 3)})
    return out


def outline(mask):
    return mask & ~ndimage.binary_erosion(mask, iterations=2)


def annotate(frame_rgb, robot, obj, base, k, m, names):
    img = frame_rgb.astype(np.float32) / 255
    for mask, colour in ((robot, (0.1, 0.55, 1.0)), (obj, (0.1, 0.85, 0.25))):
        if mask is not None and mask.any():
            img[mask] = 0.5 * img[mask] + 0.5 * np.array(colour)
    if base is not None:
        img[outline(base)] = (0.91, 0.13, 0.18)
    im = Image.fromarray((img * 255).astype(np.uint8))
    im = im.resize((IMAGE_WIDTH, round(im.height * IMAGE_WIDTH / im.width)))
    gap = "robot not found" if m is None else f"gap {m['gap_px']:.0f} px"
    if m and m.get("feet_depth_px") is not None:
        gap += f" · feet {m['feet_depth_px']:+.0f} px past the base's far edge"
    lines = [f"{k['tag']} · {k['label']} · t = {k['brain_s']:.2f} s after the brain starts · frame {k['frame']}",
             f"{gap} · blue = {names[0]}, green = {names[1]}, red = its base (from pixels)"]
    font = ImageFont.load_default(size=18)
    bar = Image.new("RGB", (im.width, 52), (20, 20, 20))
    d = ImageDraw.Draw(bar)
    for i, line in enumerate(lines):
        d.text((8, 4 + 24 * i), line, fill=(240, 240, 240), font=font)
    out = Image.new("RGB", (im.width, im.height + bar.height))
    out.paste(bar, (0, 0))
    out.paste(im, (0, bar.height))
    return out


def build_frames(evdir, ev, snap, ledger):
    """Key frames, annotated, each described by Glimmer. Writes keyframes/K*.jpg."""
    shot = str(evdir / "shot.mp4")
    size = tuple(ev["shot"]["size"])
    start = ev["shot"]["first_frame"]
    robot_raw, obj_raw = sam.load_raw(evdir / "sam-robot.txt"), sam.load_raw(evdir / "sam-object.txt")
    base = None
    if ev.get("base"):
        fb = ev["base"]["from_frame"] - start
        base = see.base_of(see.union(obj_raw[fb], size), see.rgb(shot, fb))["mask"]
    by_frame = {p["frame"]: p for p in ev["gap_by_frame"]}
    names = (ev["names"]["robot"], ev["names"]["object"])
    (evdir / "keyframes").mkdir(exist_ok=True)
    frames = []
    for k in key_frames(ev, snap):
        f = k["shot_frame"]
        r = see.union(robot_raw.get(f) or [], size)
        o = see.union(obj_raw.get(f) or [], size)
        m = by_frame.get(k["frame"])
        path = evdir / "keyframes" / f"{k['tag']}.jpg"
        annotate(see.rgb(shot, f), r, o, base, k, m, names).save(path, quality=88)
        reply = models.glimmer(DESCRIBE_PROMPT.format(label=k["label"], robot=names[0], object=names[1]),
                               [see.jpeg(shot, f)], ledger, f"describe key frame {k['tag']}")
        try:
            sentence = json.loads(reply)["sentence"].strip()
        except (ValueError, KeyError, AttributeError):
            sentence = reply.strip()
        frames.append({**k, "image": str(path.relative_to(evdir)), "glimmer": sentence,
                       "gap_px": m and m["gap_px"], "feet_depth_px": m and m.get("feet_depth_px")})
    return frames


# ── brain log ────────────────────────────────────────────────────────────────
def read_ticks(record):
    """Every tick of a run, with the depth frame and pose carried forward where the log omits them."""
    with gzip.open(record, "rt") as fh:
        next(fh)
        rows = [json.loads(line) for line in fh]
    t0, f, p, out = rows[0]["t"], None, None, []
    for r in rows:
        new = "f" in r
        f = r["f"] if new else f
        p = r["p"] if "p" in r else p
        out.append({**r, "t": r["t"] - t0, "f": f, "p": p, "new_frame": new})
    return out


def cm(f, i):
    s, d = f["s"][i], f["d"][i]
    if s in (5, 9) and d > 0:
        return f"{d / 10:.0f}"
    return "nt" if s == 255 else "x"


def row_mins(f):
    out = []
    for r in range(8):
        vals = [f["d"][r * 8 + c] for c in range(8) if f["s"][r * 8 + c] in (5, 9) and f["d"][r * 8 + c] > 0]
        out.append(f"{min(vals) / 10:.0f}" if vals else "-")
    return out


def log_table(record, tc, key_times):
    ticks = [k for k in read_ticks(record) if tc - BEFORE_S <= k["t"] <= tc + AFTER_S]
    head = ("Brain log, every tick from {:.1f} s before first contact to {:.2f} s after. t = seconds after the "
            "brain's first tick (same clock as the frames); dt = t minus first contact. cmd = kind, vx (m/s), "
            "vyaw (rad/s); yaw (rad) and x, y (m) from odometry. depth: nearest valid reading in each sensor row, "
            "row 0 (top) to row 7 (bottom), in cm; '*' = a new depth frame arrived this tick, ' ' = the previous "
            "one is reused.").format(BEFORE_S, AFTER_S)
    lines = [head, "", "     t      dt  state     cmd      vx    vyaw     yaw       x       y  safe  depth row 0..7 (cm)"]
    for k in ticks:
        cmd = k["cmd"]
        pos = k["pos"] or [math.nan, math.nan]
        yaw = math.nan if k["yaw"] is None else k["yaw"]
        depth = " ".join(f"{v:>3}" for v in row_mins(k["f"])) if k["f"] else "none"
        safe = "yes" if k["safe"] else "NO " + (k.get("why") or "")
        lines.append(f"{k['t']:7.3f} {k['t'] - tc:+6.3f}  {k['state']:<8} {cmd[0]:<6} {cmd[1]:5.2f} {cmd[2]:+7.3f} "
                     f"{yaw:+7.3f} {pos[0]:+7.3f} {pos[1]:+7.3f}  {safe:<4} {'*' if k['new_frame'] else ' '}{depth}")
    # Full 8x8 grids every GRID_EVERY_S and at the key frames: rows top to bottom, column 0 = robot's left.
    want = sorted(set([tc - BEFORE_S + GRID_EVERY_S * i for i in range(int(BEFORE_S / GRID_EVERY_S) + 1)]
                      + list(key_times)))
    lines += ["", "Full depth frames (cm; row 0 = top, column 0 = robot's left; x = invalid, nt = no target):"]
    shown = set()
    for t in want:
        k = min(ticks, key=lambda k: abs(k["t"] - t))
        if k["t"] in shown or not k["f"]:
            continue
        shown.add(k["t"])
        lines.append(f"t = {k['t']:.3f} (dt {k['t'] - tc:+.3f})")
        lines += ["  " + " ".join(f"{cm(k['f'], r * 8 + c):>3}" for c in range(8)) for r in range(8)]
    return "\n".join(lines), [round(k["t"], 3) for k in ticks]


# ── code ─────────────────────────────────────────────────────────────────────
def target_files(target):
    files = sorted(p for p in (target / "src").rglob("*.py") if "__pycache__" not in p.parts)
    files.append(target / "brain.toml")
    return {str(p.relative_to(target)): p.read_text() for p in files}


def code_text(files):
    parts = []
    for name, text in files.items():
        lines = text.splitlines()
        parts.append(f"===== {name} ({len(lines)} lines) =====\n"
                     + "\n".join(f"{i:4d}| {line}" for i, line in enumerate(lines, 1)))
    return "\n\n".join(parts)


# ── the incident, as text ────────────────────────────────────────────────────
def incident_text(ev, frames, table):
    names = ev["names"]
    c = ev["first_contact"]
    w = ev["contacts"].get("whole_mask")
    lines = [f"INCIDENT. A fixed camera filmed the robot ({names['robot']!r}) walking; it touched the "
             f"{names['object']!r}. Clock: {ev['clock']}.",
             "",
             "Measurements (from SAM 3.1 segmentation masks, per video frame):",
             f"- First contact ({c['reading']} reading): frame {c['frame']}, t = {c['brain_s']:.3f} s; mask gap "
             f"{c['gap_px']} px, robot's feet {c.get('feet_depth_px')} px past the base's far edge "
             f"(contact = gap <= {ev['contact_px']} px with the feet at the base's depth)."]
    if w and w["frame"] != c["frame"]:
        lines.append(f"- The two masks first touch on screen earlier, at frame {w['frame']}, t = {w['brain_s']:.3f} s, "
                     "while the feet are not yet at the object's base (the object's top overlaps the robot "
                     "in the picture).")
    if ev.get("base"):
        lines.append(f"- The object's base was found from pixels ({ev['base']['method']}), "
                     f"{ev['base']['thickness_px']} px thick.")
    lines += ["", "Gap over time (t, dt, gap px, feet past base edge px), every 3rd frame from 3 s before contact:"]
    series = [p for p in ev["gap_by_frame"] if c["brain_s"] - BEFORE_S <= p["brain_s"] <= c["brain_s"] + AFTER_S]
    lines += [f"  {p['brain_s']:.3f} {p['brain_s'] - c['brain_s']:+.3f} {p['gap_px']:6.1f} {p.get('feet_depth_px')}"
              for p in series[::3]]
    lines += ["", "Key frames (images follow, in the same order; blue = robot mask, green = object mask, "
              "red = object's base). Left and right in the local model's sentences are directions in the "
              "picture, not the robot's own left and right:"]
    for k in frames:
        lines.append(f"- {k['tag']}, {k['label']}: frame {k['frame']}, t = {k['brain_s']:.3f} s, gap {k['gap_px']} px, "
                     f"feet past base edge {k['feet_depth_px']} px. Local vision model: \"{k['glimmer']}\"")
    return "\n".join(lines + ["", table])


def content_for(code, ev, frames, table, evdir, control, context=None):
    head = INSTRUCTIONS + "\n\n" + code
    if control:
        return [{"type": "input_text", "text": head},
                {"type": "input_text", "text": f"INCIDENT. While walking in the simulator, the robot touched the "
                 f"{ev['names']['object']}. No video, measurements or log are available for this incident."}]
    parts = [{"type": "input_text", "text": head}, {"type": "input_text", "text": incident_text(ev, frames, table)}]
    if context:
        parts.append({"type": "input_text", "text": context})
    for k in frames:
        parts.append({"type": "input_text", "text": f"{k['tag']} ({k['label']}, t = {k['brain_s']:.3f} s):"})
        parts.append({"type": "input_image", "image_url": "data:image/jpeg;base64,"
                      + base64.b64encode((evdir / k["image"]).read_bytes()).decode()})
    return parts


# ── checking an answer ───────────────────────────────────────────────────────
def norm_function(name):
    return re.sub(r"\(.*$", "", name or "").split(".")[-1].strip().lower()


def check(d, files, frames, tick_times):
    """Does the answer point at real code, and does it cite real frames and log ticks?"""
    c = d["cause"]
    name = next((n for n in files if n == c["file"] or n.endswith("/" + c["file"].split("/")[-1])), None)
    text = files.get(name, "")
    n_lines = len(text.splitlines())
    fn = norm_function(c["function"])
    a, b = c["lines"]["start"], c["lines"]["end"]
    tags = {k["tag"] for k in frames}
    frames_cited, ticks_cited, bad = set(), set(), []
    for e in d["evidence"]:
        # Models label depth frames from the log as "frame" and key frames as "log" now and then: look
        # for key-frame tags and tick times in every non-code reference, whatever its label.
        if e["source"] == "code":
            continue
        ref = e["ref"]
        got = set(re.findall(r"K\d", ref)) & tags
        hits = [t for t in map(float, re.findall(r"\d+\.\d+", ref))
                if any(abs(t - u) <= 0.026 for u in tick_times)]
        frames_cited |= got
        ticks_cited |= set(hits)
        if e["source"] in ("frame", "log") and not got and not hits:
            bad.append(ref)
    return {"file": name, "file_ok": name is not None,
            "lines_ok": name is not None and 1 <= a <= b <= n_lines,
            "function_ok": bool(fn) and (re.search(rf"\bdef {re.escape(fn)}\b", text) is not None
                                         or name == "brain.toml"),
            "frames_cited": sorted(frames_cited), "log_ticks_cited": sorted(ticks_cited), "bad_refs": bad,
            "grounded": bool(frames_cited) and bool(ticks_cited)}


def cause_key(d, chk, files):
    """One name per place, however the model spells it: file::function for code, file::[section] key
    for a configuration value (models name a config line's "function" in many ways)."""
    name = chk["file"] or d["cause"]["file"]
    if not name.endswith(".toml"):
        return f"{name}::{norm_function(d['cause']['function'])}"
    lines = files.get(name, "").splitlines()
    a, b = d["cause"]["lines"]["start"], d["cause"]["lines"]["end"]
    key = next((m.group(1) for i in range(max(a, 1), min(b, len(lines)) + 1)
                if (m := re.match(r"\s*([A-Za-z_]\w*)\s*=", lines[i - 1]))), None)
    section = next((m.group(1) for i in range(min(a, len(lines)), 0, -1)
                    if (m := re.match(r"\s*\[([^\]]+)\]", lines[i - 1]))), "")
    return f"{name}::[{section}] {key}" if key else f"{name}::lines {a}-{b}"


def ask(model, content, ledger, purpose, files, frames, tick_times):
    reply = models.respond(MODELS[model], content, ledger, purpose, EFFORT, SCHEMA, MAX_OUTPUT)
    call = ledger.calls[-1]
    try:
        d = json.loads(re.sub(r"^```(?:json)?|```$", "", reply.strip()))
    except ValueError:
        return {"model": model, "error": "reply is not JSON", "reply": reply[:2000], "call": call}
    chk = check(d, files, frames, tick_times)
    return {"model": model, "diagnosis": d, "check": chk, "key": cause_key(d, chk, files), "call": call}


# ── output ───────────────────────────────────────────────────────────────────
def agreement(runs):
    keys = [r.get("key") for r in runs if "key" in r]
    if not keys:
        return {"runs": len(runs), "answered": 0}
    top, n = collections.Counter(keys).most_common(1)[0]
    return {"runs": len(runs), "answered": len(keys), "causes": dict(collections.Counter(keys)),
            "majority": top, "same_as_majority": n,
            "grounded": sum(r["check"]["grounded"] for r in runs if "check" in r)}


def write_md(path, ev, frames, main, compare):
    d, chk = main["diagnosis"], main["check"]
    c = d["cause"]
    out = [f"# Diagnosis: {ev['names']['robot']} touches the {ev['names']['object']}", "",
           f"**Cause:** `{c['file']}`, `{c['function']}`, lines {c['lines']['start']}-{c['lines']['end']}. {c['what']}", "",
           f"**In plain words:** {d['explanation']}", "",
           f"**What happened:** {d['observed']}", "",
           f"**Confidence:** {d['confidence']:.2f}  ·  **Fix direction (no patch):** {d['fix_direction']}", "",
           "## Evidence cited", ""]
    out += [f"- *{e['source']}* `{e['ref']}`: {e['value']}. {e['shows']}" for e in d["evidence"]]
    out += ["", "## Ruled out", ""] + [f"- {r['cause']}: {r['because']}" for r in d["ruled_out"]]
    out += ["", "## Check against what was sent", "",
            f"- file exists: {chk['file_ok']}; lines in range: {chk['lines_ok']}; function found: {chk['function_ok']}",
            f"- key frames cited: {', '.join(chk['frames_cited']) or 'none'}; log ticks cited: "
            f"{', '.join(f'{t:.3f}' for t in chk['log_ticks_cited']) or 'none'}",
            f"- references that match nothing sent: {chk['bad_refs'] or 'none'}",
            f"- **grounded in pixels and log: {'yes' if chk['grounded'] else 'NO'}**", "",
            "## Key frames", ""]
    for k in frames:
        out += [f"**{k['tag']}** {k['label']}, t = {k['brain_s']:.2f} s. Glimmer: *{k['glimmer']}*", "",
                f"![{k['tag']}]({k['image']})", ""]
    if compare:
        out += ["## Repeatability", "", "| model | evidence | runs | same cause as its majority | majority cause | grounded |",
                "|---|---|---|---|---|---|"]
        for name, a in compare["summary"].items():
            model, mode = name.split("/")
            out.append(f"| {model} | {mode} | {a['runs']} | {a.get('same_as_majority', 0)}/{a['answered']} | "
                       f"`{a.get('majority', '-')}` | {a.get('grounded', 0)}/{a['answered']} |")
        out += ["", compare["note"], ""]
    m = main["call"]
    out += ["## Model", "", f"{m['model']} (Meta Model API), effort {m.get('effort')}, {m['input_tokens']} input tokens "
            f"({m['cached_input_tokens']} cached), {m['output_tokens']} output ({m.get('reasoning_tokens')} reasoning), "
            f"${m['cost_usd']:.3f}, {m['seconds']:.0f} s. Every call of this incident is in `models.json`."]
    path.write_text("\n".join(out) + "\n")


def control_note(groups, summary):
    lines = []
    for model in ("wonder", "spark"):
        ev, ctl = summary.get(f"{model}/evidence"), summary.get(f"{model}/code-only")
        if not ev or not ctl or not ev.get("majority") or not ctl.get("majority"):
            continue
        conf = lambda g: np.mean([r["diagnosis"]["confidence"] for r in groups[g] if "diagnosis" in r])
        same = ctl["causes"].get(ev["majority"], 0)
        if same:
            lines.append(f"{model}: {same}/{ctl['answered']} code-only runs name the same place as with evidence "
                         f"(`{ev['majority']}`), so the code alone points there; the evidence confirms it rather "
                         f"than finds it (mean confidence {conf(f'{model}/evidence'):.2f} with evidence, "
                         f"{conf(f'{model}/code-only'):.2f} without).")
        else:
            lines.append(f"{model}: no code-only run names `{ev['majority']}`; without the evidence it says "
                         f"{', '.join(f'`{k}`' for k in ctl['causes'])} (mean confidence "
                         f"{conf(f'{model}/code-only'):.2f}). The evidence changes the answer.")
    return " ".join(lines) or "No code-only control was run."


def report(evdir, ev, frames, target, results, main_model):
    """Group the runs, pick the diagnosis kept, write diagnosis.json, diagnosis.md, diagnosis-runs.json."""
    groups = collections.defaultdict(list)
    for r in results:
        groups[f"{r['model']}/{r['mode']}"].append(r)
    summary = {k: agreement(v) for k, v in groups.items()}
    several = len(results) > 1
    comp = {"summary": summary, "note": control_note(groups, summary)} if several else None

    # The diagnosis kept: the majority cause of the main model's evidence runs, first run that gave it.
    maj = summary.get(f"{main_model}/evidence", {}).get("majority")
    main = next((r for r in groups.get(f"{main_model}/evidence", []) if r.get("key") == maj), None)
    (evdir / "diagnosis-runs.json").write_text(json.dumps(results, indent=1))
    if main is None:
        raise SystemExit(f"no usable diagnosis: {[r.get('error') for r in results]}")
    doc = {"incident": str(evdir / "evidence.json"), "target": str(target), "key_frames": frames,
           **main["diagnosis"], "cause_key": main["key"], "check": main["check"], "model": main["call"],
           "repeatability": comp}
    (evdir / "diagnosis.json").write_text(json.dumps(doc, indent=1))
    write_md(evdir / "diagnosis.md", ev, frames, main, comp)
    return doc


def rescore(evdir):
    """Re-check and re-group the saved runs (no model calls), after a change to the checks."""
    evdir = pathlib.Path(evdir).expanduser()
    ev = json.loads((evdir / "evidence.json").read_text())
    old = json.loads((evdir / "diagnosis.json").read_text())
    frames, target = old["key_frames"], pathlib.Path(old["target"])
    snap = see.load_snapshot(ev["snapshot"])
    _, tick_times = log_table(snap["record"], ev["first_contact"]["brain_s"], [k["brain_s"] for k in frames])
    files = target_files(target)
    results = json.loads((evdir / "diagnosis-runs.json").read_text())
    for r in results:
        if "diagnosis" in r:
            r["check"] = check(r["diagnosis"], files, frames, tick_times)
            r["key"] = cause_key(r["diagnosis"], r["check"], files)
    main_model = "wonder" if any(r["model"] == "wonder" and r["mode"] == "evidence" for r in results) else "spark"
    return report(evdir, ev, frames, target, results, main_model)


def diagnose(evdir, model="wonder", runs=1, compare=0, control=0, target=None, context=None):
    """`context`: extra text sent after the incident (a replay with a fix in place says what it changed)."""
    evdir = pathlib.Path(evdir).expanduser()
    if evdir.name == "evidence.json":
        evdir = evdir.parent
    ev = json.loads((evdir / "evidence.json").read_text())
    if not ev.get("first_contact"):
        raise SystemExit("evidence.json has no first contact: nothing to diagnose")
    snap = see.load_snapshot(ev["snapshot"])
    meta = json.loads(pathlib.Path(ev["snapshot"]).read_text())
    target = pathlib.Path(target or meta.get("brain") or TARGET_ROOT).expanduser().resolve()
    if target != TARGET_ROOT.resolve():
        raise SystemExit(f"refusing to read {target}: the only target is {TARGET_ROOT}")

    ledger = models.Ledger()
    frames = build_frames(evdir, ev, snap, ledger)
    table, tick_times = log_table(snap["record"], ev["first_contact"]["brain_s"], [k["brain_s"] for k in frames])
    files = target_files(target)
    code = code_text(files)
    (evdir / "diagnosis-input.txt").write_text(incident_text(ev, frames, table) + ("\n\n" + context if context else ""))

    plan = [(m, "evidence") for m in ([model] if not compare else ["wonder", "spark"])
            for _ in range(compare or runs)]
    plan += [(m, "code-only") for m in (["wonder", "spark"] if compare else [model]) for _ in range(control)]
    results, blocked = [], set()
    for i, (m, mode) in enumerate(plan):
        if m in blocked:
            results.append({"model": m, "mode": mode, "error": "skipped: daily budget reached"})
            continue
        content = content_for(code, ev, frames, table, evdir, mode == "code-only", context)
        try:
            r = ask(m, content, ledger, f"diagnose ({mode}, run {i + 1})", files, frames, tick_times)
        except RuntimeError as e:
            r = {"model": m, "error": str(e)}
        r["mode"] = mode
        results.append(r)
        print(json.dumps({"model": m, "mode": mode, "key": r.get("key"), "error": r.get("error"),
                          "grounded": r.get("check", {}).get("grounded"),
                          "cost": r.get("call", {}).get("cost_usd")}), flush=True)
        if r.get("error", "").startswith("budget"):
            blocked.add(m)

    prior = evdir / "models.json"
    calls = json.loads(prior.read_text())["calls"] if prior.exists() else []
    ledger.calls = calls + ledger.calls
    ledger.write(prior)
    return report(evdir, ev, frames, target, results, "wonder" if compare else model)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("evidence", help="an evidence directory (or its evidence.json) written by blinkflow.see")
    ap.add_argument("--model", choices=tuple(MODELS), default="wonder")
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--compare", type=int, default=0, metavar="N", help="Wonder and Spark, N runs each")
    ap.add_argument("--control", type=int, default=0, metavar="K", help="K code-only runs per model")
    ap.add_argument("--rescore", action="store_true", help="re-check the saved runs, no model calls")
    a = ap.parse_args()
    doc = rescore(a.evidence) if a.rescore else diagnose(a.evidence, a.model, a.runs, a.compare, a.control)
    print(json.dumps({"cause": doc["cause"], "confidence": doc["confidence"], "grounded": doc["check"]["grounded"],
                      "explanation": doc["explanation"], "repeatability": doc["repeatability"]}, indent=1))


if __name__ == "__main__":
    main()
