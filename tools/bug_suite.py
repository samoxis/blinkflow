"""The blind bug suite. Scorer side: it reads the twin's own contact log; BlinkFlow does not.

    python3 tools/bug_suite.py validate          # twin, 20 s: the clean base must not touch the box,
                                                 # a copy is kept as a bug only if it does
    python3 tools/bug_suite.py run [LABEL ...]   # for each bug: the incident filmed in the twin, then
                                                 # the whole loop (blinkflow.fix) on that copy
    python3 tools/bug_suite.py report            # results/bug_suite.md; reveals the mutations

Copies come from tools/inject_bug.py (~/blinkflow-runs/suite/<label>/target); ~/duck-target is only
read. The incident is the twin's rendered shot, ending ~1 s after the first contact, like a snapshot
taken right after the incident. The first diagnosis is made COMPARE times each by Muse Wonder and
Muse Spark (Wonder's majority goes on to Muse Code); budgets are blinkflow.models' daily caps. A bug
whose loop dies on an API error is run once more; the suite stops only if that fails again.
"""
import argparse
import json
import math
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import time

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parent
sys.path[:0] = [str(REPO), str(HERE)]
import inject_bug  # noqa: E402
from blinkflow import models  # noqa: E402

SUITE = inject_bug.SUITE
RL_PYTHON = pathlib.Path.home() / "microduck_rl" / ".venv" / "bin" / "python"
SECONDS = 20.0
MAX_BUGS = 6
COMPARE = 3
API_ERRORS = ("HTTP", "ended", "ConnectionError", "Timeout", "RemoteDisconnected", "ChunkedEncodingError")
RESULTS = REPO / "results" / "bug_suite.md"


def twin(brain, seconds, out, video=False):
    """One twin run; returns its summary (first contact with the box from the twin's own log)."""
    args = [str(RL_PYTHON), "-m", "blinkflow.twin", "--brain", str(brain), "--seconds", str(seconds),
            "--out", str(out)] + (["--video"] if video else [])
    r = subprocess.run(args, cwd=REPO, capture_output=True, text=True, check=True)
    return json.loads(r.stdout.strip().splitlines()[-1])


def git(root, *args):
    return subprocess.run(["git", *inject_bug.IDENTITY, *args], cwd=root, capture_output=True, text=True,
                          check=True).stdout.strip()


def labels():
    return sorted((p.parent.name for p in SUITE.glob("b*/target")), key=lambda s: int(s[1:]))


# ── validate ─────────────────────────────────────────────────────────────────
def validate():
    with tempfile.TemporaryDirectory(dir=SUITE) as tmp:
        base = twin(inject_bug.clean_base(pathlib.Path(tmp) / "base"), SECONDS, pathlib.Path(tmp) / "runs")
    if base["first_contact_s"] is not None:
        raise SystemExit(f"the clean base touches the box: {base}")
    doc = {"seconds": SECONDS, "base": base, "bugs": {}}
    for label in labels():
        r = twin(SUITE / label / "target", SECONDS, SUITE / label / "validate")
        doc["bugs"][label] = {"contact": r["first_contact_s"] is not None, **r}
    valid = [k for k, v in doc["bugs"].items() if v["contact"]]
    doc["kept"] = valid[:MAX_BUGS]
    rejected = [k for k in doc["bugs"] if k not in valid]
    doc["rejected"] = inject_bug.reveal(rejected) if rejected else {}
    (SUITE / "validation.json").write_text(json.dumps(doc, indent=1))
    print(json.dumps({"base": "no contact in 20 s", "kept": doc["kept"], "valid_not_kept": valid[MAX_BUGS:],
                      "rejected": {k: {"mutation": v["change"], "where": v["where"]}
                                   for k, v in doc["rejected"].items()}}, indent=1))


# ── run ──────────────────────────────────────────────────────────────────────
def run(label):
    d, target = SUITE / label, SUITE / label / "target"
    v = json.loads((SUITE / "validation.json").read_text())["bugs"][label]
    first = git(target, "rev-list", "--max-parents=0", "HEAD")
    if git(target, "rev-parse", "HEAD") != first or git(target, "status", "--porcelain"):
        raise SystemExit(f"{label}: the copy is not as drawn")
    for sub in ("incident", "fix", "after"):
        shutil.rmtree(d / sub, ignore_errors=True)
    seconds = math.ceil((v["first_contact_s"] + 1.0) * 2) / 2
    t = time.time()
    inc = twin(target, seconds, d / "incident", video=True)
    render_s = time.time() - t
    meta = pathlib.Path(inc["out"]) / "meta.json"
    env = {**os.environ, "BLINKFLOW_TARGET": str(target)}
    t = time.time()
    with open(d / "fix.log", "w") as log:
        rc = subprocess.run([sys.executable, "-m", "blinkflow.fix", str(meta), "--out", str(d / "fix"),
                             "--compare", str(COMPARE)],
                            cwd=REPO, env=env, stdout=log, stderr=subprocess.STDOUT).returncode
    fix_s = time.time() - t
    if git(target, "status", "--porcelain"):         # the loop broke off mid-attempt: back to the drawn copy
        git(target, "reset", "-q", "--hard", first)
        git(target, "clean", "-qfd")
    after = twin(target, max(SECONDS, seconds + 8), d / "after")
    doc = {"label": label, "incident_seconds": seconds, "incident": str(meta), "render_s": round(render_s, 1),
           "fix_rc": rc, "fix_s": round(fix_s, 1), "head": git(target, "rev-parse", "HEAD"),
           "before_twin": v, "after_twin": after}
    (d / "result.json").write_text(json.dumps(doc, indent=1))
    print(json.dumps({"label": label, "rc": rc, "fix_s": doc["fix_s"],
                      "after_contact": after["first_contact_s"]}), flush=True)
    return doc


def run_all(chosen):
    kept = json.loads((SUITE / "validation.json").read_text())["kept"]
    for label in chosen or kept:
        if label not in kept:
            raise SystemExit(f"{label} is not a kept bug")
        for tries in (1, 2):
            doc = run(label)
            lines = (SUITE / label / "fix.log").read_text().strip().splitlines()
            if not (doc["fix_rc"] and lines and any(e in lines[-1] for e in API_ERRORS)):   # the error that ended it
                break
            shutil.copy(SUITE / label / "fix.log", SUITE / label / f"fix-failed-{tries}.log")
        else:
            print(json.dumps({"stopped": f"API errors twice in a row on {label}"}), flush=True)
            return


# ── report ───────────────────────────────────────────────────────────────────
def costs(models_json):
    calls = json.loads(models_json.read_text())["calls"]
    out = {"sam": 0.0, "wonder": 0.0, "other": 0.0}
    for c in calls:
        k = "sam" if c["model"].startswith("sam") else "wonder" if c["model"] == models.WONDER else "other"
        out[k] += c["cost_usd"] or 0.0
    return out


def located(cause, where):
    """Does Wonder's cause (file + line range) contain a mutated line?"""
    lo, hi = cause["lines"]["start"], cause["lines"]["end"]
    return any(cause["file"].endswith(w["file"]) and lo <= w["line"] <= hi for w in where)


def restored(label, where):
    """How many mutated lines read again as in the clean base, in the copy as the loop left it."""
    with tempfile.TemporaryDirectory(dir=SUITE) as tmp:
        base = inject_bug.clean_base(pathlib.Path(tmp) / "base")
        now = SUITE / label / "target"
        same = sum((base / w["file"]).read_text().splitlines()[w["line"] - 1]
                   == (now / w["file"]).read_text().splitlines()[w["line"] - 1] for w in where)
    return same, len(where)


def contact(s):
    return "none" if s is None else f"{s:.2f} s"


def report():
    val = json.loads((SUITE / "validation.json").read_text())
    truth = inject_bug.reveal()
    rows, n_fixed, n_located, n_cause, n_run, located_runs = [], 0, 0, 0, 0, {}
    total = {"sam": 0.0, "wonder": 0.0, "other": 0.0}
    for label in val["kept"]:
        rf = SUITE / label / "result.json"
        t = truth[label]
        if not rf.exists():
            rows.append(f"| {label} | {t['mutation']}: `{t['change']}` | not run | | | | | | | |")
            continue
        n_run += 1
        r = json.loads(rf.read_text())
        fj = SUITE / label / "fix" / "fix.json"
        fix = json.loads(fj.read_text()) if fj.exists() else None
        dj = SUITE / label / "fix" / "incident" / "diagnosis.json"
        diag = json.loads(dj.read_text()) if dj.exists() else None
        c = costs(SUITE / label / "fix" / "models.json") if (SUITE / label / "fix" / "models.json").exists() else None
        if c:
            total = {k: total[k] + c[k] for k in total}
        hit = diag is not None and located(diag["cause"], t["where"])
        runs_f = SUITE / label / "fix" / "incident" / "diagnosis-runs.json"
        per_model = {}
        for x in json.loads(runs_f.read_text()) if runs_f.exists() else []:
            if x.get("mode") == "evidence":
                m = per_model.setdefault(x["model"], [0, 0])
                m[0] += "diagnosis" in x and located(x["diagnosis"]["cause"], t["where"])
                m[1] += 1
        for m, (a, b) in per_model.items():
            located_runs.setdefault(m, [0, 0])
            located_runs[m][0] += a
            located_runs[m][1] += b
        cmp = ", ".join(f"{m} {a}/{b}" for m, (a, b) in sorted(per_model.items(), reverse=True)) or "-"
        same, n = restored(label, t["where"])
        fixed = r["after_twin"]["first_contact_s"] is None
        n_fixed += fixed
        n_located += hit
        n_cause += fixed and same == n
        found = (f"`{diag['cause']['file']}` {diag['cause']['lines']['start']}-{diag['cause']['lines']['end']} "
                 f"({diag['confidence']:.2f}): {diag['cause']['what']}") if diag else "no diagnosis"
        att = len(fix["attempts"]) if fix else "-"
        verdict = ("fixed" if fix["fixed"] else "not fixed") if fix else f"loop failed (rc {r['fix_rc']})"
        rows.append(f"| {label} | {t['mutation']}: `{t['change']}` | {found} | {'yes' if hit else 'no'} | {cmp} | {att} | "
                    f"{contact(r['before_twin']['first_contact_s'])} | {contact(r['after_twin']['first_contact_s'])} | "
                    f"{verdict}; mutated lines restored {same}/{n} | {r['render_s'] + r['fix_s']:.0f} s | "
                    + (f"${sum(c.values()):.2f} (SAM {c['sam']:.2f}, Wonder {c['wonder']:.2f})" if c else "-") + " |")
    k = len(val["kept"])
    out = ["# BlinkFlow blind bug suite", "",
           f"Clean base: `~/duck-target` with its known bug undone; in the twin it does not touch the box in "
           f"{val['seconds']:.0f} s. {len(val['bugs'])} mutations drawn from `tools/inject_bug.py` with a sealed "
           f"seed; {len(val['bugs']) - len(val['rejected'])} gave a contact within {val['seconds']:.0f} s, "
           f"{k} were kept. BlinkFlow saw each incident only as the twin's rendered shot and the brain's log; the "
           "mutation is revealed here, after the runs.", "",
           "| bug | mutation (revealed) | what Muse Wonder found (confidence) | at the mutated line? | "
           "runs at the mutated line, per model | attempts | contact before (twin) | contact after (twin) | "
           "loop's verdict | time | cost |",
           "|---|---|---|---|---|---|---|---|---|---|---|", *rows, "",
           f"**{n_fixed}/{k} fixed** (no contact in the twin after the loop's change); Wonder put the cause on the "
           f"mutated line in **{n_located}/{k}**; the change restored the mutated line(s) in **{n_cause}/{k}**. "
           f"{n_run}/{k} bugs ran. Contacts are the twin's own log (scorer); the loop decides from pixels only.", "",
           f"First diagnosis, {COMPARE} runs per model on the same evidence; runs whose cause contains a mutated "
           "line: " + (", ".join(f"{m} {a}/{b}" for m, (a, b) in sorted(located_runs.items(), reverse=True)) or "-")
           + ".", "",
           f"Model cost of the runs: ${sum(total.values()):.2f} (SAM 3.1 ${total['sam']:.2f}, Muse Wonder "
           f"${total['wonder']:.2f}, other ${total['other']:.2f}). Time = rendering the incident + the whole loop.",
           ""]
    if val["rejected"]:
        out += ["## Mutations without a contact in 20 s (not in the set)", ""]
        out += [f"- {v['mutation']}: `{v['change']}`" for v in val["rejected"].values()]
        out += [""]
    RESULTS.parent.mkdir(exist_ok=True)
    RESULTS.write_text("\n".join(out))
    print(RESULTS)


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("validate")
    r = sub.add_parser("run")
    r.add_argument("labels", nargs="*")
    sub.add_parser("report")
    a = ap.parse_args()
    {"validate": validate, "run": lambda: run_all(a.labels), "report": report}[a.cmd]()


if __name__ == "__main__":
    main()
