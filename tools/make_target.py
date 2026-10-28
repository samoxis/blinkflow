"""Make BlinkFlow's target: microduck-brain at a fixed public commit, with the demo bug in and the hints out.

    python3 tools/make_target.py [DEST]          # default ~/duck-target; DEST must not exist

1. clone https://github.com/samoxis/microduck-brain at COMMIT (v0.3, Apache-2.0);
2. keep only the code a developer would have: src/, brain.toml, pyproject.toml, uv.lock, LICENSE
   (no README, docs, tests, tools, CI or history), and drop the readme line from pyproject.toml;
3. put the demo bug in: "ahead" = the front columns only, no side memory. This is the author's
   pre-existing commit "demo: reintroduce finding 6" (Oct 22), which was never pushed, re-stated here
   as text edits;
4. rewrite the comments that would give the answer away so they describe the code as it now is;
5. one commit, "microduck-brain snapshot", by duck-target <duck-target@localhost>.

The result is the same, file for file, as the ~/duck-target every run in results/ used. The brain's
own environment is made by `uv run` in DEST the first time the simulator starts it.
"""
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

REPO = "https://github.com/samoxis/microduck-brain"
COMMIT = "e1e157de164260e3eea9732f94f8dfea1e053923"
KEEP = ("src", "brain.toml", "pyproject.toml", "uv.lock", "LICENSE")
IDENTITY = ["-c", "user.name=duck-target", "-c", "user.email=duck-target@localhost"]

# (file, text at COMMIT, text in the target); each must occur exactly once.
EDITS = [
    # the bug: "ahead" = the central columns, at their raw distance, as in the version before the fix
    ("src/microduck_brain/depth.py",
     '''    # "Ahead" is geometric, not a set of columns: every wall-row return whose lateral position, relative
    # to the robot's axis, falls within the body's swept corridor counts, at its forward distance. The
    # sensor sits ``sensor_lateral`` to the left of the axis, so the right side needs the outer columns.
    ranges: list[float] = []
    for r in rows:
        for c in range(frame.cols):
            d = frame.zone(r, c, cfg.max_range)
            if d is None:
                continue
            bx, by, _ = BEAMS[r * frame.cols + c]
            if abs(d * by + cfg.sensor_lateral) <= cfg.corridor_half_width:
                ranges.append(d * bx)
''',
     '''    # "Ahead" = the wall-row returns of the front columns, at their measured distance.
    ranges: list[float] = []
    for r in rows:
        for c in front_cols:
            d = frame.zone(r, c, cfg.max_range)
            if d is not None:
                ranges.append(d)
'''),
    # the bug: no side memory
    ("brain.toml",
     "side_memory_seconds = 3.0 # remember wall returns near the body for this long: a chair leg leaves the "
     "field of view ~30 cm before passing the leg",
     "side_memory_seconds = 0.0 # remember wall returns near the body for this long (s)"),
    # hints: the comments that name the blind spot or the leg
    ("src/microduck_brain/hazards.py",
     '''* **Sides**: the 45° field of view is narrower than the body close up, and the sensor sits 2.2 cm to
  the left of the axis. A chair leg or a wall corner that will pass within a few centimetres of the
  right leg leaves the field of view ~30 cm before it gets there.
''',
     "* **Sides**: wall returns near the body can be kept for a configurable time.\n"),
    ("brain.toml",
     "# \"ahead\" = any wall return within this of the robot's axis (m): the body's swept width + margin",
     "# half-width of the robot's swept corridor (m): body width + margin"),
    ("brain.toml",
     "# microduck-brain configuration. Every value here is the built-in default: delete any line and the\n"
     "# default applies. An unknown key is an error, not silently ignored.\n",
     "# microduck-brain configuration. An unknown key is an error, not silently ignored.\n"),
    ("pyproject.toml", 'readme = "README.md"\n', ""),
]


def git(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, stdout=subprocess.DEVNULL)


def main():
    dest = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "~/duck-target").expanduser().resolve()
    if dest.exists():
        raise SystemExit(f"{dest} exists; remove it or name another folder")
    with tempfile.TemporaryDirectory() as tmp:
        src = pathlib.Path(tmp) / "microduck-brain"
        git("clone", "-q", "--no-checkout", REPO, str(src), cwd=tmp)
        git("checkout", "-q", COMMIT, cwd=src)
        dest.mkdir(parents=True)
        for name in KEEP:
            (shutil.copytree if (src / name).is_dir() else shutil.copy2)(src / name, dest / name)
    for rel, old, new in EDITS:
        p = dest / rel
        text = p.read_text()
        if text.count(old) != 1:
            shutil.rmtree(dest)
            raise SystemExit(f"{rel}: expected text found {text.count(old)} times, not once; nothing made")
        p.write_text(text.replace(old, new))
    (dest / ".gitignore").write_text(".venv/\n__pycache__/\n*.pyc\n")
    git("init", "-q", cwd=dest)
    git("add", ".", cwd=dest)
    git(*IDENTITY, "commit", "-q", "-m", "microduck-brain snapshot", cwd=dest)
    head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=dest, capture_output=True, text=True).stdout
    print(f"target made: {dest} (base commit {head.strip()}, from {REPO} @ {COMMIT[:7]})")
    if os.environ.get("BLINKFLOW_TARGET") not in (None, str(dest)):
        print(f"note: BLINKFLOW_TARGET is {os.environ['BLINKFLOW_TARGET']}, not this folder")


if __name__ == "__main__":
    main()
