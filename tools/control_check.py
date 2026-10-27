"""Does the pixel rule raise false alarms, and does it still catch the real incidents? Scorer side only.

Every saved look (evidence.json with its SAM 3.1 replies and shot) is measured again with the code as it
is now, from the saved replies (`see --reuse`: no new model calls), in a scratch copy, and compared with
the ground truth the agent never reads: the twin's contacts.csv and truth.json (touches, fall), or for a
live run the simulator's contacts-*.csv. Only truth inside the look's own shot counts.

    python3 tools/control_check.py run LABEL [--only SUBSTR]   # measure every look, save LABEL.json
    python3 tools/control_check.py table BEFORE AFTER          # markdown: outcomes before and after

A look "raises" when the proof's rule (prove.contact_of, or a fall) sees an incident in it.
"""
import argparse
import concurrent.futures
import csv
import json
import pathlib
import shutil
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent), str(HERE)]
from blinkflow import prove, see  # noqa: E402
import score_contact  # noqa: E402

RUNS = pathlib.Path.home() / "blinkflow-runs"
OUT = RUNS / "control-check"
NEEDS = ("evidence.json", "models.json", "sam-robot.txt", "sam-object.txt", "shot.mp4")
MARGIN_S = 0.5          # truth this close past the shot's ends still belongs to it


def looks(only=None):
    for ev in sorted(RUNS.rglob("evidence.json")):
        d = ev.parent
        if OUT in d.parents or not all((d / n).exists() for n in NEEDS):
            continue
        if only and only not in str(d):
            continue
        yield d


def truth(snapshot, times):
    """The first true incident inside the shot: (brain s, what) or None."""
    snap = see.load_snapshot(snapshot)
    t0, t1 = times[0] - MARGIN_S, times[-1] + MARGIN_S
    hits = []
    if snap["kind"] == "twin":
        # a control's look is a thinned copy (prove.every_nth): the twin's own folder is its record's
        twin = pathlib.Path(json.loads(pathlib.Path(snapshot).read_text())["record"]).parent
        for r in list(csv.reader(open(twin / "contacts.csv")))[1:]:
            hits.append((float(r[0]), f"contact {r[1]}"))
        tj = twin / "truth.json"
        if tj.exists():
            t = json.loads(tj.read_text())
            hits += [(x["t"], f"touch {x.get('geom') or x.get('body') or ''}".strip()) for x in t.get("touches") or []
                     if isinstance(x, dict) and "t" in x]
            if t.get("fell_s") is not None:
                hits.append((t["fell_s"], "fall"))
    else:
        gt = score_contact.truth(snapshot, snap)
        if gt:
            hits.append((gt[0], f"contact {gt[1]}"))
    hits = [h for h in hits if t0 <= h[0] <= t1]
    return min(hits, default=None)


def measure(d):
    old = json.loads((d / "evidence.json").read_text())
    with tempfile.TemporaryDirectory(dir=OUT) as tmp:
        tmp = pathlib.Path(tmp)
        for n in NEEDS:
            (tmp / n).symlink_to(d / n) if n == "shot.mp4" else shutil.copy(d / n, tmp / n)
        try:
            ev = see.see(old["snapshot"], tmp, reuse=True)
        except Exception as e:          # an old look the code can no longer read: reported, not hidden
            return {"look": str(d), "error": f"{type(e).__name__}: {e}"[:300]}
    reading, hit = prove.contact_of(ev)
    fall = (ev.get("fall") or {}).get("first")
    raised = min((x for x in (hit, fall) if x), key=lambda x: x["brain_s"], default=None)
    times = [p["brain_s"] for p in ev["gap_by_frame"]] or [0.0]
    snap = see.load_snapshot(old["snapshot"])
    shot_times = snap["brain_time"][ev["shot"]["first_frame"]:ev["shot"]["first_frame"] + ev["shot"]["frames"]]
    try:
        gt = truth(old["snapshot"], shot_times or times)
    except (OSError, KeyError, ValueError) as e:
        return {"look": str(d), "error": f"no ground truth: {type(e).__name__}: {e}"[:300]}
    out = {"look": str(d), "names": [ev["names"]["robot"], ev["names"]["object"]], "reading": reading,
           "raised_s": raised and raised["brain_s"], "raised_by": raised and ("fall" if raised is fall else reading),
           "object": ev.get("object"), "truth_s": gt and round(gt[0], 3), "truth": gt and gt[1]}
    out["outcome"] = ("caught" if raised and gt else "false alarm" if raised else "missed" if gt else "quiet")
    if raised and gt:
        out["delta_s"] = round(raised["brain_s"] - gt[0], 3)
    return out


def run(label, only):
    OUT.mkdir(parents=True, exist_ok=True)
    todo = list(looks(only))
    print(f"{len(todo)} looks", flush=True)
    res = []
    with concurrent.futures.ThreadPoolExecutor(3) as pool:
        for r in pool.map(measure, todo):
            res.append(r)
            print(json.dumps({k: r.get(k) for k in ("look", "outcome", "raised_s", "truth_s", "error")}), flush=True)
    (OUT / f"{label}.json").write_text(json.dumps(res, indent=1))


def group(look):
    rel = pathlib.Path(look).relative_to(RUNS).parts
    if "control" in rel:
        return "fix control (pixels)"
    return {"watch-suite": "watcher suite", "suite-layers": "layered suite", "suite": "blind suite",
            "voice": "voice", "quick": "quick loop"}.get(rel[0], "other")


def table(before, after):
    b = {r["look"]: r for r in json.loads((OUT / f"{before}.json").read_text())}
    a = {r["look"]: r for r in json.loads((OUT / f"{after}.json").read_text())}
    keys = [k for k in b if k in a and "error" not in b[k] and "error" not in a[k]]
    groups = {}
    for k in keys:
        groups.setdefault(group(k), []).append(k)
    print("| looks | n | true incidents | caught before → after | false alarms before → after | missed before → after |")
    print("|---|---|---|---|---|---|")
    total = {"n": 0, "pos": 0}
    for g, ks in sorted(groups.items()) + [("all", keys)]:
        cnt = lambda d, o: sum(d[k]["outcome"] == o for k in ks)
        pos = sum(b[k]["truth_s"] is not None for k in ks)
        print(f"| {g} | {len(ks)} | {pos} | {cnt(b, 'caught')} → {cnt(a, 'caught')} | "
              f"{cnt(b, 'false alarm')} → {cnt(a, 'false alarm')} | {cnt(b, 'missed')} → {cnt(a, 'missed')} |")
    changed = [k for k in keys if (b[k]["outcome"], b[k]["raised_s"]) != (a[k]["outcome"], a[k]["raised_s"])]
    if changed:
        print("\n| look | names | truth | before | after |")
        print("|---|---|---|---|---|")
        for k in changed:
            fmt = lambda r: f"{r['outcome']}" + (f" {r['raised_s']:.2f} s ({r['raised_by']})" if r["raised_s"] is not None else "")
            t = f"{b[k]['truth']} {b[k]['truth_s']:.2f} s" if b[k]["truth_s"] is not None else "none"
            print(f"| {pathlib.Path(k).relative_to(RUNS)} | {' · '.join(a[k]['names'])} | {t} | {fmt(b[k])} | {fmt(a[k])} |")
    errs = [k for k in a if "error" in a[k]]
    if errs:
        print(f"\nNot measurable ({len(errs)}): " + "; ".join(f"{pathlib.Path(k).relative_to(RUNS)}: {a[k]['error'][:80]}" for k in errs))


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("label")
    r.add_argument("--only")
    t = sub.add_parser("table")
    t.add_argument("before")
    t.add_argument("after")
    a = ap.parse_args()
    run(a.label, a.only) if a.cmd == "run" else table(a.before, a.after)


if __name__ == "__main__":
    main()
