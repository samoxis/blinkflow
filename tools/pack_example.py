"""Pack one finished run as a self-contained example: what a judge needs to check it without this PC.

    python3 tools/pack_example.py <run>/events.jsonl examples/<name> [--provenance SAMPLES.txt] [--extra NAME=PATH ...]

Copies the event stream and every file it names that the console may show, and the run's other text files
(measurements, diagnosis, what each model was sent), never the scorer's ground truth (contact logs,
truth.json, scene files). Paths are rewritten relative to the example ("./...") and the home folder is
written as "~". Adds:
  models.json    every model call of the run (model, where it ran, tokens or frames, seconds, cost)
  glimmer.jsonl  Muse Glimmer's raw replies, each beside its call in models.json
  provenance.txt `ollama ps` and `nvidia-smi` sampled every ~3 s while the run ran, timestamps kept: the run's own
                 (`voice live` writes it), or --provenance
  --extra        other text files (an earlier run's models.json...), scrubbed the same way
  left-out.json  what was not copied: SAM 3.1's replies for the control scenes (masks do not compress; their
                 verdicts stay in the stream and their calls in models.json), unless --all
Then `python3 -m blinkflow.console report examples/<name>/events.jsonl` builds the static report.
"""
import argparse
import gzip
import json
import os
import pathlib
import re
import shutil
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from blinkflow.console import NEVER, named_paths, read_events, servable  # noqa: E402

HOME = str(pathlib.Path.home())
USER = pathlib.Path.home().name
TEXT = {".json", ".jsonl", ".md", ".txt", ".csv"}


def scrub(text):
    """The home folder as "~", the Windows profile as %USERPROFILE% (also as WSL sees it, /mnt/c/Users/...)."""
    text = text.replace(HOME, "~").replace(f"/mnt/c/Users/{USER}", "%USERPROFILE%")
    return re.sub(r"(?i)C:(\\\\|\\|/)Users(\\\\|\\|/)" + re.escape(USER), lambda m: "%USERPROFILE%", text)


def relink(text, dest, out, moved):
    """Paths of files already in the example, written from `dest`'s folder ("./clip.mp4")."""
    for p, r in moved.items():
        rel = os.path.relpath(out / r, dest.parent)
        text = text.replace(json.dumps(p), json.dumps(rel if rel.startswith("../") else "./" + rel))
    return text


def glimmer_replies(evs, root, here):
    """Every Glimmer reply the run kept, in the order they were made. `here`: a path as the example names it."""
    out = []
    for e in evs:
        if e["type"] == "keyframes":
            out += [{"t": e["t"], "purpose": f"describe key frame {f['tag']} ({f['label']})", "image": here(f["image"]),
                     "reply": f["glimmer"]} for f in e["frames"] if f.get("glimmer")]
    for f in sorted(root.rglob("evidence.json")):
        names = json.loads(f.read_text()).get("names") or {}
        out += [{"purpose": "name the robot and the object or hazard nearest to it", "evidence": here(f.parent),
                 "reply": a["reply"], "rejected": a["rejected"]}
                for a in names.get("attempts", []) if a.get("namer") == "glimmer"]
    for f in sorted(root.rglob("voice.json")):
        heard = json.loads(f.read_text()).get("heard") or {}
        out += [{"purpose": "when it happened and what it touched, from the person's words", "said": heard.get("said"),
                 "reply": a.get("reply"), "rejected": a.get("rejected")}
                for a in heard.get("read_attempts", []) if a.get("reader") == "glimmer"]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("events")
    ap.add_argument("out")
    ap.add_argument("--provenance", help="samples of `ollama ps` + `nvidia-smi` taken during the run")
    ap.add_argument("--all", action="store_true", help="keep the control scenes' SAM replies too")
    ap.add_argument("--extra", nargs="*", default=[], help="NAME=PATH: a text file copied in as NAME")
    a = ap.parse_args()
    stream = pathlib.Path(a.events).expanduser().resolve()
    root, out = stream.parent, pathlib.Path(a.out)
    if out.exists():
        raise SystemExit(f"{out} exists")
    evs = read_events(stream)
    moved, left, files = {}, [], []
    for p in sorted(named_paths(evs)):
        f = servable(p, evs, stream)
        if not f:
            continue
        rel = f.relative_to(root) if root in f.parents else pathlib.Path("outside") / f.name
        if not a.all and "control" in rel.parts and f.name.startswith("sam-"):
            left.append({"path": "./" + str(rel), "bytes": f.stat().st_size})
            continue
        moved[p] = "./" + str(rel)
        files.append((f, out / rel))
    for f, _ in list(files):                    # a snapshot's brain log: see --reuse reads it
        m = json.loads(f.read_text()) if f.suffix == ".json" else None
        r = isinstance(m, dict) and m.get("record")
        if r and r not in moved and pathlib.Path(r).is_file() and not NEVER.search(pathlib.Path(r).name):
            q = pathlib.Path(r).resolve()
            rel = q.relative_to(root) if root in q.parents else pathlib.Path("outside") / q.name
            moved[r] = "./" + str(rel)
            files.append((q, out / rel))
    for f, dest in files:                       # all paths known first, so each file can name the others
        dest.parent.mkdir(parents=True, exist_ok=True)
        if f.suffix in TEXT:
            dest.write_text(scrub(relink(f.read_text(), dest, out, moved)))
        elif f.name.endswith(".jsonl.gz"):
            dest.write_bytes(gzip.compress(scrub(gzip.decompress(f.read_bytes()).decode()).encode(), mtime=0))
        else:
            shutil.copy(f, dest)
    for f in sorted(root.rglob("*")):
        rel = f.relative_to(root)
        if (f.is_file() and f.suffix in TEXT and not NEVER.search(f.name) and not f.name.startswith("sam-")
                and f != stream and not (out / rel).exists()):
            (out / rel).parent.mkdir(parents=True, exist_ok=True)
            (out / rel).write_text(scrub(relink(f.read_text(), out / rel, out, moved)))
    lines = []
    for line in stream.read_text().splitlines():
        for p, r in moved.items():
            line = line.replace(json.dumps(p), json.dumps(r))
        lines.append(scrub(line))
    out.mkdir(parents=True, exist_ok=True)
    (out / "events.jsonl").write_text("\n".join(lines) + "\n")
    mfile = next((root / m for m in ("models.json", "fix/models.json") if (root / m).exists()), None)
    if mfile:
        (out / "models.json").write_text(scrub(mfile.read_text()))
    with (out / "glimmer.jsonl").open("w") as fh:
        here = lambda p: moved.get(str(p)) or ("./" + str(pathlib.Path(p).relative_to(root))
                                               if root in pathlib.Path(p).parents else str(p))
        for g in glimmer_replies(evs, root, here):
            fh.write(scrub(json.dumps(g)) + "\n")
    (out / "left-out.json").write_text(json.dumps(left, indent=1))
    for spec in a.extra:
        name, src = spec.split("=", 1)
        (out / name).write_text(scrub(pathlib.Path(src).expanduser().read_text()))
    if a.provenance:
        (out / "provenance.txt").write_text(scrub(pathlib.Path(a.provenance).read_text()))
    private = [str(f) for f in out.rglob("*") if f.is_file() and f.suffix in TEXT and (HOME in f.read_text() or USER in f.read_text())]
    size = sum(f.stat().st_size for f in out.rglob("*") if f.is_file())
    print(json.dumps({"example": str(out), "files": len(moved), "mb": round(size / 1e6, 1), "left_out": len(left), "private_left": private}))


if __name__ == "__main__":
    main()
