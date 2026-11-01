"""The ablation's runs as manifests: what each run said, changed and saw, with a hash of every file it saw.

    python3 tools/ablation_manifest.py write RUN... --out results/ablation [--repo TARGET...]
    python3 tools/ablation_manifest.py check results/ablation/*.json [--target TARGET...]

write: one <set>-<run>.json per run of tools/ablation.py: the sentence, every attempt (Muse Code's files and
seconds, the replay's verdict, the control), the kept diff and the git blob of each file it leaves, and the
sha256 of every file the verdicts came from (the twin's shots, SAM 3.1's replies, the measurements). Never the
scorer's ground truth (the twin's contacts.csv, truth.json): those are left out, not hashed.
check: on the PC that holds the runs, every listed file has its hash, and every measurement is re-derived
from SAM 3.1's saved replies (blinkflow.see --reuse, no key, no GPU) and equals the saved one; with --target,
the kept diff applied to the base commit gives the listed blobs (a temporary index, the target untouched).
"""
import argparse
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from blinkflow.console import NEVER  # noqa: E402
from pack_example import scrub  # noqa: E402

HOME = pathlib.Path.home()


def sha(f):
    return hashlib.sha256(f.read_bytes()).hexdigest()


def blobs(repo, base, diff):
    """{file: git blob} after `diff` is applied to `base`, in a temporary index (no checkout, no commit)."""
    with tempfile.TemporaryDirectory() as tmp:
        env = {**os.environ, "GIT_INDEX_FILE": str(pathlib.Path(tmp) / "index")}
        git = lambda *a, **k: subprocess.run(["git", "-C", str(repo), *a], env=env, check=True, text=True,
                                             capture_output=True, **k).stdout
        git("read-tree", base)
        git("apply", "--cached", "-", input=diff)
        files = git("diff", "--cached", "--name-only", base).split()
        return {f: git("ls-files", "-s", "--", f).split()[1] for f in files}


def evidence_dirs(run):
    return sorted(p.parent for p in run.rglob("evidence/evidence.json"))


def write(run, out, repos):
    run = run.expanduser().resolve()
    s = json.loads((run / "ablation.json").read_text())
    repo = next((r for r in repos if subprocess.run(["git", "-C", str(r), "cat-file", "-e", s["base"]],
                                                    capture_output=True).returncode == 0), None)
    files = [{"path": str(f.relative_to(run)), "bytes": f.stat().st_size, "sha256": sha(f)}
             for f in sorted(run.rglob("*")) if f.is_file() and not NEVER.search(f.name)]
    name = (f"{'b7' if run.parent.name.startswith('b7') else 'box'}-precise-{run.name.split('-')[-1]}"
            if run.name.startswith("run-") else "{}-vague-{}".format(*run.name.split("-")))
    doc = {"run": str(run), **{k: s.get(k) for k in ("sentence", "said", "scene", "control", "base", "model",
                                                 "fixed_and_control_clean", "seconds", "muse_code_usd", "proof_usd")},
           "attempts": [{k: a.get(k) for k in ("attempt", "muse_code_s", "files", "stat", "problems", "verdict",
                                              "control", "proof_s")} for a in s["attempts"]],
           "kept_diff": s["kept_diff"],
           "kept_blobs": blobs(repo, s["base"], s["kept_diff"]) if s["kept_diff"] and repo else None,
           "evidence": [str(d.relative_to(run)) for d in evidence_dirs(run)],
           "left_out": sorted(str(f.relative_to(run)) for f in run.rglob("*") if f.is_file() and NEVER.search(f.name)),
           "files": files,
           "recheck": f"python3 tools/ablation_manifest.py check results/ablation/{name}.json --target <a clone of the "
                      f"target holding {s['base'][:7]}>"}
    (out / f"{name}.json").write_text(scrub(json.dumps(doc, indent=1)) + "\n")
    return name, doc


def check(manifest, targets):
    m = json.loads(manifest.read_text())
    run = pathlib.Path(m["run"].replace("~", str(HOME), 1))
    bad = [f["path"] for f in m["files"] if not (run / f["path"]).is_file() or sha(run / f["path"]) != f["sha256"]]
    same = []
    with tempfile.TemporaryDirectory() as tmp:
        for d in m["evidence"]:
            copy = pathlib.Path(tmp) / d
            shutil.copytree(run / d, copy)
            old = json.loads((run / d / "evidence.json").read_text())
            subprocess.run([sys.executable, "-m", "blinkflow.see", old["snapshot"], "--out", str(copy), "--reuse"],
                           cwd=HERE.parent, check=True, capture_output=True)
            new = json.loads((copy / "evidence.json").read_text())
            same.append(sorted(k for k in old.keys() | new.keys() if old.get(k) != new.get(k)) == [])
    blob_ok = None
    repo = next((pathlib.Path(t).expanduser() for t in targets if subprocess.run(
        ["git", "-C", str(pathlib.Path(t).expanduser()), "cat-file", "-e", m["base"]], capture_output=True).returncode == 0), None)
    if repo and m["kept_diff"]:
        blob_ok = blobs(repo, m["base"], m["kept_diff"]) == m["kept_blobs"]
    return {"manifest": manifest.name, "files": len(m["files"]), "hash_mismatch": bad,
            "measurements_rederived": f"{sum(same)}/{len(same)}", "blobs_match": blob_ok}


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    w = sub.add_parser("write")
    w.add_argument("runs", nargs="+", type=pathlib.Path)
    w.add_argument("--out", type=pathlib.Path, required=True)
    w.add_argument("--repo", nargs="*", type=pathlib.Path, default=[HOME / "duck-target"],
                   help="target repos to find each run's base commit in")
    c = sub.add_parser("check")
    c.add_argument("manifests", nargs="+", type=pathlib.Path)
    c.add_argument("--target", nargs="*", default=[], help="target repos; the one holding the base commit is used")
    a = ap.parse_args()
    if a.cmd == "write":
        a.out.mkdir(parents=True, exist_ok=True)
        for r in a.runs:
            name, doc = write(r, a.out, [p.expanduser() for p in a.repo])
            print(name, doc["fixed_and_control_clean"], doc["kept_blobs"], len(doc["files"]), "files")
    else:
        for m in a.manifests:
            print(json.dumps(check(m, a.target)))


if __name__ == "__main__":
    main()
