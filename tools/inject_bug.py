"""Blind bug set: clean copies of the target, each with one realistic mutation. Scorer side, not the agent.

The clean base is ~/duck-target as committed, with its known bug undone (side_memory_seconds back to
config.py's default, 3.0); that brain never touches the box in 20 s of the twin. ~/duck-target itself
is only read (`git archive`).

A mutation changes code or a configured value, never a comment. A configured value is changed in
brain.toml and as config.py's default alike, so the two still agree. Each copy is a new git repo with
one commit, with the target's own neutral identity and message, and every file has the same mtime.

Which mutation lands in which copy, and its exact value, follow from a random seed written only to
tools/.bugseal (git-ignored, mode 600). BlinkFlow never reads tools/. Nothing here prints the
mapping except `reveal`, which tools/bug_suite.py calls once the suite has run.

    python3 tools/inject_bug.py draw [--force]     # new seed; copies in ~/blinkflow-runs/suite/b<N>/target
    python3 tools/inject_bug.py reveal [LABEL ...]
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
IDENTITY = ["-c", "user.name=duck-target", "-c", "user.email=duck-target@localhost"]
MESSAGE = "microduck-brain snapshot"
CONFIG = "src/microduck_brain/config.py"
DEPTH = "src/microduck_brain/depth.py"
HAZARDS = "src/microduck_brain/hazards.py"


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


# ── the draw ─────────────────────────────────────────────────────────────────
def plan(seed):
    """[(label, mutation index, value)] in label order, all from the seed."""
    rng = random.Random(seed)
    values = [rng.choice(m["choices"]) for m in MUTATIONS]
    order = rng.sample(range(len(MUTATIONS)), len(MUTATIONS))
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


def draw(force=False):
    if SEAL.exists() and not force:
        raise SystemExit(f"{SEAL} exists: a set is already drawn (--force draws a new one)")
    if SUITE.exists():
        shutil.rmtree(SUITE)
    seed = int.from_bytes(os.urandom(8), "big")
    SEAL.write_text(json.dumps({"seed": seed}))
    SEAL.chmod(0o600)
    labels = []
    for label, i, v in plan(seed):
        root = clean_base(SUITE / label / "target")
        MUTATIONS[i]["apply"](root, v)
        seal(root)
        labels.append(label)
    print(json.dumps({"drawn": labels, "suite": str(SUITE)}))


def reveal(labels=None):
    seed = json.loads(SEAL.read_text())["seed"]
    out = {}
    shutil.rmtree(SUITE / ".reveal", ignore_errors=True)
    for label, i, v in plan(seed):
        if labels and label not in labels:
            continue
        m = MUTATIONS[i]
        root = clean_base(SUITE / ".reveal" / label)           # where it lands, measured on a fresh copy
        where = m["apply"](root, v)
        shutil.rmtree(SUITE / ".reveal")
        out[label] = {"mutation": m["name"], "meaning": m["meaning"], "change": m["show"](v),
                      "where": [{"file": f, "line": n} for f, n in where]}
    return out


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("draw")
    d.add_argument("--force", action="store_true")
    r = sub.add_parser("reveal")
    r.add_argument("labels", nargs="*")
    a = ap.parse_args()
    if a.cmd == "draw":
        draw(a.force)
    else:
        print(json.dumps(reveal(a.labels), indent=1))


if __name__ == "__main__":
    main()
