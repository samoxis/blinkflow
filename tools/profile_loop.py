"""The quick loop's stopwatch. Scorer side: it reads the twin's own logs; BlinkFlow does not.

    python3 tools/profile_loop.py run LABEL [--snapshot CLIP.json]
    python3 tools/profile_loop.py table LABEL [LABEL ...]

`run`: the whole loop (blinkflow.fix) on the purple-box incident, against a fresh copy of ~/duck-target
(~/duck-target itself is only read), then the scorer: the brain as the loop left it replayed in the
box scene as long as the proof (incident + 8 s, at least 20 s) (is the contact gone?) and in every scene for 20 s (is the control
still clean?), from the twin's own contact log. Writes ~/blinkflow-runs/quick/<LABEL>/profile.json.
`table`: one row per step of the loop, one column per run, as markdown.
"""
import argparse
import json
import os
import pathlib
import shutil
import subprocess
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parent
sys.path[:0] = [str(REPO), str(HERE)]
import bug_suite  # noqa: E402

HOME = pathlib.Path.home()
QUICK = HOME / "blinkflow-runs" / "quick"
INCIDENT = HOME / "blinkflow-runs" / "clips" / "20261026-173622-2e3fba.json"   # the live purple-box run


def run(label, snapshot):
    d = QUICK / label
    if d.exists():
        raise SystemExit(f"{d} exists")
    d.mkdir(parents=True)
    target = d / "target"
    shutil.copytree(HOME / "duck-target", target, symlinks=True)
    # The snapshot names the brain it ran; the copy stands in for it (diagnose reads only that target).
    meta = json.loads(pathlib.Path(snapshot).read_text())
    meta["brain"] = str(target)
    snap = d / "snapshot.json"
    snap.write_text(json.dumps(meta))
    env = {**os.environ, "BLINKFLOW_TARGET": str(target)}
    t = time.time()
    with open(d / "fix.log", "w") as log:
        rc = subprocess.run([sys.executable, "-m", "blinkflow.fix", str(snap), "--out", str(d / "fix")],
                            cwd=REPO, env=env, stdout=log, stderr=subprocess.STDOUT).returncode
    loop_s = time.time() - t
    t = time.time()
    after = bug_suite.twin(target, max(bug_suite.SECONDS, meta["seconds"] + 8), d / "after", scene="box")
    ctl = bug_suite.control(target, d / "control")
    score_s = time.time() - t
    doc = {"label": label, "rc": rc, "loop_s": round(loop_s, 1), "score_s": round(score_s, 1),
           "after": {"first_contact_s": after["first_contact_s"], "fell_s": after["fell_s"]},
           "control": ctl, "control_clean": all(c["clean"] for c in ctl.values())}
    (d / "profile.json").write_text(json.dumps(doc, indent=1))
    print(json.dumps({k: doc[k] for k in ("label", "rc", "loop_s", "score_s", "after", "control_clean")}))


# ── the table ────────────────────────────────────────────────────────────────
def calls(fixdir, stage, model, purpose=""):
    ms = json.loads((fixdir / "models.json").read_text())["calls"]
    return [c["seconds"] for c in ms if c["stage"] == stage and c["model"].startswith(model) and purpose in c["purpose"]]


def steps(label):
    """{step: seconds} for one run; parallel steps are each measured on their own."""
    d = QUICK / label
    p = json.loads((d / "profile.json").read_text())
    fixdir = d / "fix"
    fx = json.loads((fixdir / "fix.json").read_text())
    st = {s["stage"]: s for s in fx["stages"]}
    when = lambda prefix: next((s for k, s in st.items() if k.startswith(prefix)), None)
    out = {}
    see = when("see")
    out["Glimmer: name robot + object"] = sum(calls(fixdir, "incident", "muse-glimmer", "name"))
    out["SAM 3.1 on the incident (robot, object)"] = max(calls(fixdir, "incident", "sam"), default=0)
    out["see: the rest (ffmpeg, masks, measuring)"] = see["seconds"] - out["Glimmer: name robot + object"] \
        - out["SAM 3.1 on the incident (robot, object)"]
    describe = calls(fixdir, "incident", "muse-glimmer", "describe")
    out["Glimmer: describe 4 key frames"] = max(describe) if "start" in see else sum(describe)   # parallel since
    out["Muse Wonder: prompt cache warm-up (background)"] = sum(calls(fixdir, "incident", "muse-wonder", "warm"))
    out["Muse Wonder: diagnosis"] = sum(calls(fixdir, "incident", "muse-wonder", "diagnose"))
    out["Muse Wonder: input tokens read from cache"] = sum(
        c.get("cached_input_tokens") or 0 for c in json.loads((fixdir / "models.json").read_text())["calls"]
        if c["stage"] == "incident" and "diagnose" in c["purpose"])
    b, a = fx["before"], fx["attempts"][0]["verdict"] if fx["attempts"] else None
    out["replay before: twin render"] = b["replay_s"]
    out["replay before: SAM 3.1 + verdict"] = b["see_s"]
    out["Muse Code: edit"] = fx["attempts"][0]["muse_code"]["seconds"] if fx["attempts"] else None
    out["replay after: twin render"] = a and a["replay_s"]
    out["replay after: SAM 3.1 + verdict"] = a and a["see_s"]
    out["scorer: box 20 s + control in 5 scenes (twin log)"] = p["score_s"]
    out["**seen -> fixed and verified (loop wall time)**"] = fx["seconds"]
    out["attempts / fixed / control clean"] = f"{len(fx['attempts'])} / {fx['fixed']} / {p['control_clean']}"
    return out


def table(labels):
    cols = {lb: steps(lb) for lb in labels}
    rows = list(next(iter(cols.values())))
    fmt = lambda v: "-" if v is None else (v if isinstance(v, str) else str(v) if isinstance(v, int) else f"{v:.1f}")
    print("| step | " + " | ".join(labels) + " |")
    print("|---|" + "---|" * len(labels))
    for r in rows:
        print(f"| {r} | " + " | ".join(fmt(cols[lb].get(r)) for lb in labels) + " |")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("label")
    r.add_argument("--snapshot", default=str(INCIDENT))
    t = sub.add_parser("table")
    t.add_argument("labels", nargs="+")
    a = ap.parse_args()
    run(a.label, a.snapshot) if a.cmd == "run" else table(a.labels)


if __name__ == "__main__":
    main()
