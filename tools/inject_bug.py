"""Blind bug set: clean copies of the target, each with one realistic mutation. Scorer side, not the agent.

The clean base is ~/duck-target as committed, with its known bug undone (side_memory_seconds back to
config.py's default, 3.0); that brain never touches the box in 20 s of the twin. ~/duck-target itself
is only read (`git archive`).

A mutation changes code or a configured value, never a comment. A configured value is changed in
brain.toml and as config.py's default alike, so the two still agree. Each copy is a new git repo with
one commit, with the target's own neutral identity and message, and every file has the same mtime.

Which mutation lands in which copy, and its exact value, follow from a random seed written only to
the set's seal (git-ignored, mode 600). BlinkFlow never reads tools/. Nothing here prints the
mapping except `reveal`, which tools/bug_suite.py calls once the suite has run.

Two sets. `side` (the first suite, Oct 26): mutations around the side memory, all filmed at the box.
`layers`: each mutation belongs to one layer of the brain and one scene of blinkflow.scenes built to
test that layer (low objects, drops, stop threshold and direction, corridor, side memory).

    python3 tools/inject_bug.py draw [--set layers] [--force]   # new seed; copies in <suite>/b<N>/target
    python3 tools/inject_bug.py reveal [--set layers] [LABEL ...]
"""
import argparse
import io
import json
import os
import pathlib
import random
import re
import shutil
import subprocess
import tarfile

HERE = pathlib.Path(__file__).resolve().parent
SEAL = HERE / ".bugseal"
SOURCE = pathlib.Path.home() / "duck-target"
SUITE = pathlib.Path.home() / "blinkflow-runs" / "suite"
SEAL_LAYERS = HERE / ".bugseal-layers"
SUITE_LAYERS = pathlib.Path.home() / "blinkflow-runs" / "suite-layers"
IDENTITY = ["-c", "user.name=duck-target", "-c", "user.email=duck-target@localhost"]
MESSAGE = "microduck-brain snapshot"
CONFIG = "src/microduck_brain/config.py"
DEPTH = "src/microduck_brain/depth.py"
HAZARDS = "src/microduck_brain/hazards.py"
DEPTH_LOW = "out.append(LowObstacle(r, c, d, d * bx, d * by, ratio))"
DEPTH_DROP = "out.append(DropZone(r, c, nominal * bx, nominal * by, no_target))"


# ── edits ────────────────────────────────────────────────────────────────────
def lines_of(text, needle):
    """1-based numbers of the lines containing `needle`."""
    return [i for i, line in enumerate(text.splitlines(), 1) if needle in line]


def set_value(root, section, key, value):
    """`[section] key` in brain.toml and its default in config.py, both to `value`. A comment after the
    value keeps its column. Returns where it changed: [(file, line)]."""
    toml = root / "brain.toml"
    lines = toml.read_text().splitlines(keepends=True)
    current, where = None, []
    for i, line in enumerate(lines):
        if m := re.match(r"\[(\w+)\]", line):
            current = m.group(1)
        m = re.match(rf"({key}\s*=\s*)(\S+)( *)(#.*)?$", line.rstrip("\n"))
        if current == section and m:
            old_len = len(m.group(2)) + len(m.group(3))
            pad = " " * max(1, old_len - len(str(value))) if m.group(4) else ""
            lines[i] = m.group(1) + str(value) + pad + (m.group(4) or "") + "\n"
            where.append(("brain.toml", i + 1))
    toml.write_text("".join(lines))
    cfg = root / CONFIG
    text = cfg.read_text()
    body = re.search(rf"^class {section.capitalize()}:\n(.*?)(?=^\S)", text, re.M | re.S)
    old = re.search(rf"^(    {key}: \w+ = )(\S+)$", body.group(1), re.M)
    at = body.start(1) + old.start()
    text = text[:at] + old.group(1) + str(value) + text[at + len(old.group(0)):]
    cfg.write_text(text)
    where.append((CONFIG, text[:at].count("\n") + 1))
    if len(where) != 2:
        raise RuntimeError(f"{section}.{key}: found {where}")
    return where


def replace_code(root, rel, old, new):
    f = root / rel
    text = f.read_text()
    if text.count(old) != 1:
        raise RuntimeError(f"{rel}: {old!r} found {text.count(old)} times")
    text = text.replace(old, new)
    f.write_text(text)
    return [(rel, n) for n in lines_of(text, new.strip().splitlines()[0])]


# ── the mutations: name, what it means, the values to draw from, how to apply one ───────
def value_mutation(name, meaning, section, key, choices):
    return {"name": name, "meaning": meaning, "choices": choices,
            "apply": lambda root, v: set_value(root, section, key, v),
            "show": lambda v: f"[{section}] {key} = {v}"}


def columns(root, v):
    return set_value(root, "obstacle", "front_first_col", v[0]) + set_value(root, "obstacle", "front_last_col", v[1])


def halves(root, _):
    return replace_code(root, DEPTH,
                        "    left = _column_minima(frame, cfg, range(0, 4))\n"
                        "    right = _column_minima(frame, cfg, range(4, 8))\n",
                        "    left = _column_minima(frame, cfg, range(4, 8))\n"
                        "    right = _column_minima(frame, cfg, range(0, 4))\n")


def lateral_sign(root, _):
    return replace_code(root, HAZARDS, "f, lat = d * bx, d * by + sl\n", "f, lat = d * bx, d * by - sl\n")


def code_mutation(name, meaning, rel, old, new, show, choices=(None,)):
    """One code edit; `new` may hold {v} for the drawn value."""
    return {"name": name, "meaning": meaning, "choices": list(choices), "show": show,
            "apply": lambda root, v: replace_code(root, rel, old, new.format(v=v))}


def side_behind(root, v):
    return replace_code(root, HAZARDS, "if kind != DROP and (fwd < -0.15 or fwd > 2.0):",
                        f"if kind != DROP and (fwd < {v} or fwd > 2.0):")


MUTATIONS = [
    value_mutation("stop distance too short", "the robot stops for a wall only when it is much closer",
                   "obstacle", "stop_distance", [0.12, 0.14, 0.16]),
    {"name": "ahead columns too narrow", "meaning": "only the central columns count as 'ahead'",
     "choices": [(3, 4), (2, 4), (3, 5)], "apply": columns,
     "show": lambda v: f"[obstacle] front_first_col = {v[0]}, front_last_col = {v[1]}"},
    {"name": "sensor sides swapped", "meaning": "the freer-side choice reads the sensor's left columns as right",
     "choices": [None], "apply": halves,
     "show": lambda v: "depth.analyse: left half = columns 4-7, right half = columns 0-3"},
    {"name": "sensor offset sign inverted", "meaning": "side returns are shifted the wrong way by the sensor's lateral offset",
     "choices": [None], "apply": lateral_sign, "show": lambda v: "hazards._detect: lateral = d*by - sensor_lateral"},
    value_mutation("side memory too short", "wall returns beside the body are forgotten almost at once",
                   "obstacle", "side_memory_seconds", [0.05]),
    value_mutation("clear distance too small", "a turn ends as soon as the obstacle is just past the stop distance",
                   "obstacle", "clear_distance", [0.28, 0.29, 0.30]),
    value_mutation("corridor too narrow", "remembered side returns count only very close to the axis",
                   "obstacle", "corridor_half_width", [0.04]),
    {"name": "side points dropped beside the body", "meaning": "a remembered side return is dropped once it is "
     "level with the sensor, while the legs are still passing it", "choices": [0.0, 0.05], "apply": side_behind,
     "show": lambda v: f"hazards.update: side points kept only while fwd >= {v} (was -0.15)"},
    value_mutation("steering starts too late", "the robot starts steering away only close to the obstacle",
                   "obstacle", "slow_distance", [0.32, 0.36]),
    code_mutation("side lookahead too short", "wall returns are remembered as side hazards only when almost "
                  "touching the sensor", HAZARDS, "SIDE_LOOKAHEAD = 0.8    #", "SIDE_LOOKAHEAD = {v:<7}#",
                  lambda v: f"hazards.SIDE_LOOKAHEAD = {v} (was 0.8)", [0.08, 0.1, 0.12]),
    code_mutation("beam components swapped", "a side return's forward and lateral distances are swapped, so "
                  "nothing lands in the side band", HAZARDS, "f, lat = d * bx, d * by + sl\n",
                  "f, lat = d * by, d * bx + sl\n", lambda v: "hazards._detect: f, lat = d*by, d*bx + sensor_lateral"),
    code_mutation("side layer switch inverted", "the side layer is on only for a negative memory time, i.e. never",
                  HAZARDS, "return o.side_memory_seconds > 0\n", "return o.side_memory_seconds < 0\n",
                  lambda v: "hazards._enabled: SIDE on when side_memory_seconds < 0"),
    code_mutation("memory needs a missing yaw", "hazards are remembered only when odometry has no yaw, i.e. never",
                  HAZARDS, "can_remember = pos is not None and yaw is not None\n",
                  "can_remember = pos is not None and yaw is None\n",
                  lambda v: "hazards.update: can_remember = pos is not None and yaw is None"),
    code_mutation("side lookahead comparison flipped", "only wall returns further than the lookahead become side "
                  "hazards", HAZARDS, "if f < SIDE_LOOKAHEAD and abs(lat) < SIDE_BAND:",
                  "if f > SIDE_LOOKAHEAD and abs(lat) < SIDE_BAND:",
                  lambda v: "hazards._detect: side returns kept when f > SIDE_LOOKAHEAD"),
]


def in_layer(layer, scene, m):
    return {**m, "layer": layer, "scene": scene}


# Each one was tried in its scene before the draw; stop threshold, direction and the doorway's corridor
# gave no incident there in any variant tried (the wall view and the side memory both stop the robot),
# and are drawn anyway so the validation reports them.
LAYERED = [
    in_layer("low objects", "low_cube", value_mutation(
        "low-object margin too wide", "a low reading must be far shorter than the floor's to count, so a small "
        "object reads as floor", "low", "range_margin", [0.35, 0.40, 0.45])),
    in_layer("low objects", "low_cube", value_mutation(
        "wall-foot margin too wide", "a low reading is taken for the foot of a wall that is far behind it",
        "low", "wall_margin", [1.5, 2.0, 2.5])),
    in_layer("low objects", "low_cube", code_mutation(
        "low-object position swapped", "a low object's forward and lateral distances are swapped, so it lands "
        "beside the corridor", DEPTH, DEPTH_LOW, "out.append(LowObstacle(r, c, d, d * by, d * bx, ratio))",
        lambda v: "depth.low_obstacles: LowObstacle(..., d*by, d*bx, ...)")),
    in_layer("drops", "ledge", value_mutation(
        "drop check too short", "only zones whose floor is expected within a short range are checked for a "
        "missing floor, i.e. none while standing", "drop", "max_expected", [0.20, 0.25, 0.30])),
    in_layer("drops", "ledge", value_mutation(
        "drop margin too wide", "a reading must be far longer than any plausible floor to count as a drop",
        "drop", "range_margin", [0.5, 0.6, 0.7, 0.8])),
    in_layer("drops", "ledge", code_mutation(
        "drop position swapped", "a drop's forward and lateral distances are swapped, so it lands beside the "
        "corridor", DEPTH, DEPTH_DROP, "out.append(DropZone(r, c, nominal * by, nominal * bx, no_target))",
        lambda v: "depth.drop_zones: DropZone(..., nominal*by, nominal*bx, ...)")),
    in_layer("stop threshold", "corner", value_mutation(
        "stop distance too short", "the robot stops for a wall only when it is much closer",
        "obstacle", "stop_distance", [0.12, 0.16])),
    in_layer("direction", "corner", code_mutation(
        "freer side inverted", "after a stop the robot turns towards the less free side",
        DEPTH, 'return "left" if self.left_free > self.right_free else "right"',
        'return "left" if self.left_free < self.right_free else "right"',
        lambda v: "depth.View.freer_side: left when left_free < right_free")),
    in_layer("corridor", "doorway", value_mutation(
        "corridor too narrow (doorway)", "returns beside the body count as in the way only very close to the axis",
        "obstacle", "corridor_half_width", [0.04, 0.05])),
    in_layer("corridor", "box", value_mutation(
        "corridor too narrow", "returns beside the body count as in the way only very close to the axis",
        "obstacle", "corridor_half_width", [0.04, 0.05])),
    in_layer("side memory", "box", value_mutation(
        "side memory too short", "wall returns beside the body are forgotten almost at once (the target's own "
        "bug, as the reference)", "obstacle", "side_memory_seconds", [0.05])),
]
SETS = {"side": (MUTATIONS, SEAL, SUITE), "layers": (LAYERED, SEAL_LAYERS, SUITE_LAYERS)}


# ── the draw ─────────────────────────────────────────────────────────────────
def plan(seed, mutations=MUTATIONS):
    """[(label, mutation index, value)] in label order, all from the seed."""
    rng = random.Random(seed)
    values = [rng.choice(m["choices"]) for m in mutations]
    order = rng.sample(range(len(mutations)), len(mutations))
    return [(f"b{n}", i, values[i]) for n, i in enumerate(order, 1)]


def clean_base(dst):
    """~/duck-target's committed tree in `dst`, with its known bug undone."""
    dst.mkdir(parents=True)
    tar = subprocess.run(["git", "archive", "HEAD"], cwd=SOURCE, capture_output=True, check=True).stdout
    with tarfile.open(fileobj=io.BytesIO(tar)) as t:
        t.extractall(dst, filter="data")
    set_value(dst, "obstacle", "side_memory_seconds", 3.0)
    return dst


def seal(root):
    """Same mtime on every file, then one commit, as the target itself was made."""
    stamp = (root / "pyproject.toml").stat().st_mtime
    for p in root.rglob("*"):
        os.utime(p, (stamp, stamp))
    os.utime(root, (stamp, stamp))
    for args in (["init", "-q"], ["add", "-A"], ["commit", "-qm", MESSAGE]):
        subprocess.run(["git", *IDENTITY, *args], cwd=root, check=True, capture_output=True)


def draw(force=False, name="side"):
    mutations, seal_file, suite = SETS[name]
    if seal_file.exists() and not force:
        raise SystemExit(f"{seal_file} exists: a set is already drawn (--force draws a new one)")
    if suite.exists():
        shutil.rmtree(suite)
    seed = int.from_bytes(os.urandom(8), "big")
    seal_file.write_text(json.dumps({"seed": seed}))
    seal_file.chmod(0o600)
    labels = []
    for label, i, v in plan(seed, mutations):
        root = clean_base(suite / label / "target")
        mutations[i]["apply"](root, v)
        seal(root)
        labels.append(label)
    print(json.dumps({"drawn": labels, "suite": str(suite)}))


def scenes_of(name="layers"):
    """{label: scene}: where each copy is filmed. The scorer needs it to run the incident; it says which
    scene, not what was changed."""
    mutations, seal_file, _ = SETS[name]
    seed = json.loads(seal_file.read_text())["seed"]
    return {label: mutations[i].get("scene", "box") for label, i, _ in plan(seed, mutations)}


def reveal(labels=None, name="side"):
    mutations, seal_file, suite = SETS[name]
    seed = json.loads(seal_file.read_text())["seed"]
    out = {}
    shutil.rmtree(suite / ".reveal", ignore_errors=True)
    for label, i, v in plan(seed, mutations):
        if labels and label not in labels:
            continue
        m = mutations[i]
        root = clean_base(suite / ".reveal" / label)           # where it lands, measured on a fresh copy
        where = m["apply"](root, v)
        shutil.rmtree(suite / ".reveal")
        out[label] = {"mutation": m["name"], "meaning": m["meaning"], "change": m["show"](v),
                      "where": [{"file": f, "line": n} for f, n in where],
                      **({"layer": m["layer"], "scene": m["scene"]} if "layer" in m else {})}
    return out


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("draw")
    d.add_argument("--force", action="store_true")
    r = sub.add_parser("reveal")
    r.add_argument("labels", nargs="*")
    for p in (d, r):
        p.add_argument("--set", default="side", choices=SETS)
    a = ap.parse_args()
    if a.cmd == "draw":
        draw(a.force, a.set)
    else:
        print(json.dumps(reveal(a.labels, a.set), indent=1))


if __name__ == "__main__":
    main()
