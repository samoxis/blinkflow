"""The watcher measured: false alarms and misses. Scorer side: it reads the twin's own logs and the live
runs' contact logs (through live-check.json); the watcher reads only the clip and the brain's log.

    python3 tools/watch_suite.py render     # twin, 20 s, filmed: each layered bug as drawn in its scene,
                                            # and the clean base (the v0.3 behaviour) in all 5 scenes
    python3 tools/watch_suite.py run [CASE ...]   # blinkflow.watch on each clip, played in real time
    python3 tools/watch_suite.py table      # markdown, for results/watcher.md

Cases: the 8 layered bugs and the 5 controls (twin renders), and the 20 live runs of live-check (purple
box: duck-target before its fix, with a contact in 9; after it, none in 11). One case at a time:
Glimmer's latency is part of what is measured.
"""
import argparse
import concurrent.futures
import json
import pathlib
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parent
sys.path[:0] = [str(REPO), str(HERE)]
import bug_suite  # noqa: E402
import inject_bug  # noqa: E402

HOME = pathlib.Path.home()
OUT = HOME / "blinkflow-runs" / "watch-suite"
CASES = OUT / "cases.json"
LIVE_CHECKS = sorted((HOME / "blinkflow-runs" / "live-check").glob("*/live-check.json"))
EARLY_S = 1.5        # a confirmed incident more than this before the true one is a false alarm


def render():
    OUT.mkdir(exist_ok=True)
    val = json.loads((inject_bug.SUITE_LAYERS / "validation.json").read_text())
    jobs = {}
    brains = OUT / "brains"                           # kept: a watch with --loop needs its brain
    brains.mkdir()
    base = inject_bug.clean_base(brains / "base")
    for s in bug_suite.SCENES:
        jobs[f"control-{s}"] = (base, s, None)
    for label in val["kept"]:
        target = inject_bug.SUITE_LAYERS / label / "target"
        drawn = brains / label      # the copy as drawn, before the loop's fix
        drawn.mkdir()
        first = bug_suite.git(target, "rev-list", "--max-parents=0", "HEAD")
        tar = subprocess.run(["git", "archive", first], cwd=target, capture_output=True, check=True).stdout
        subprocess.run(["tar", "-x", "-C", str(drawn)], input=tar, check=True)
        jobs[label] = (drawn, val["bugs"][label]["scene"], label)
    cases = {}
    with concurrent.futures.ThreadPoolExecutor(2) as pool:
        futs = {k: pool.submit(bug_suite.twin, b, bug_suite.SECONDS, OUT / "renders" / k, True, s)
                for k, (b, s, _) in jobs.items()}
        for k, f in futs.items():
            r = f.result()
            t = bug_suite.incident_s(r)
            cases[k] = {"source": "twin", "scene": jobs[k][1], "snapshot": str(pathlib.Path(r["out"]) / "meta.json"),
                        "positive": t is not None, "truth_s": t, "truth_kind": "fall" if r["fell_s"] == t and t
                        is not None else "contact" if t is not None else None, "twin": r}
    for f in LIVE_CHECKS:
        lc = json.loads(f.read_text())
        for r in lc["runs"]:
            k = f"live{int(lc['seconds'])}-{r['side']}-{r['run']}"
            cases[k] = {"source": "live", "scene": "box", "snapshot": r["snapshot"].replace(".mp4", ".json"),
                        "positive": r["contact"], "truth_s": r["first_contact_s"],
                        "truth_kind": "contact" if r["contact"] else None, "brain": r["side"] == "after" and "fixed" or "bug"}
    CASES.write_text(json.dumps(cases, indent=1))
    print(json.dumps({k: (c["positive"], c["truth_s"]) for k, c in cases.items()}, indent=1))


def run(chosen):
    cases = json.loads(CASES.read_text())
    for k in chosen or cases:
        out = OUT / "runs" / k
        if (out / "watch.json").exists():
            continue
        subprocess.run([sys.executable, "-m", "blinkflow.watch", "clip", cases[k]["snapshot"], "--out", str(out)],
                       cwd=REPO, check=True, stdout=subprocess.DEVNULL)
        print(json.dumps({k: score(cases[k], json.loads((out / "watch.json").read_text()))}), flush=True)


def score(case, w):
    """One case: what Glimmer raised, what SAM confirmed, and how that compares with the truth."""
    c = w["incident"]
    t = case["truth_s"]
    raised = [r for r in w["raises"]]
    first_raise = next((r for r in raised if t is None or r["t"] >= t - EARLY_S), None) if case["positive"] else None
    s = {"positive": case["positive"], "truth_s": t, "truth_kind": case["truth_kind"],
         "raises": len(raised), "raise_signs": sorted({x for r in raised for x in r["signs"]}),
         "confirmations": w["summary"]["confirmations"], "dismissed": sum(not x["confirmed"] for x in w["confirmations"]),
         "confirmed": c and c["kind"], "confirmed_raise_t": c and c["raised"]["t"], "confirmed_s": c and c["incident_s"],
         "confirmed_at": c and c["done_at"], "look_s_median": w["summary"]["look_s_median"],
         "frame_gap_s_median": w["summary"]["frame_gap_s_median"], "frame_gap_s_max": w["summary"]["frame_gap_s_max"],
         "sam_cost_usd": w["summary"]["sam_cost_usd"]}
    if not case["positive"]:
        s["outcome"] = "false alarm" if c else "quiet"
    elif not c:
        s["outcome"] = "miss"
    elif c["raised"]["t"] < t - EARLY_S:
        s["outcome"] = "false alarm (early)"
    else:
        s["outcome"] = "caught"
        s["raised_after_s"] = round(c["raised"]["t"] - t, 2)
        s["confirmed_after_s"] = round(c["done_at"] - t, 2)
    s["first_raise_after_s"] = first_raise and round(first_raise["t"] - t, 2)
    return s


def table():
    cases = json.loads(CASES.read_text())
    rows, scored = [], {}
    for k, case in cases.items():
        p = OUT / "runs" / k / "watch.json"
        if p.exists():
            scored[k] = score(case, json.loads(p.read_text()))
    print("| case | scene | truth | Glimmer raised (signs) | SAM: confirmed / dismissed | outcome | raised after | confirmed after | look s | SAM $ |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    for k, s in scored.items():
        truth = f"{s['truth_kind']} {s['truth_s']:.2f} s" if s["positive"] else "none"
        conf = f"{s['confirmed']} {s['confirmed_s']:.2f} s" if s["confirmed"] else "-"
        print(f"| {k} | {cases[k]['scene']} | {truth} | {s['raises']} ({', '.join(s['raise_signs']) or '-'}) | "
              f"{conf} / {s['dismissed']} | {s['outcome']} | "
              f"{'' if s.get('raised_after_s') is None else '%+.2f' % s['raised_after_s']} | "
              f"{'' if s.get('confirmed_after_s') is None else '%+.1f' % s['confirmed_after_s']} | "
              f"{s['look_s_median']} | {s['sam_cost_usd']:.2f} |")
    groups = {"twin bugs": [k for k in scored if cases[k]["source"] == "twin" and cases[k]["positive"]],
              "twin controls": [k for k in scored if cases[k]["source"] == "twin" and not cases[k]["positive"]],
              "live, contact": [k for k in scored if cases[k]["source"] == "live" and cases[k]["positive"]],
              "live, no contact": [k for k in scored if cases[k]["source"] == "live" and not cases[k]["positive"]]}
    print("\n| set | runs | caught | missed | false alarms | Glimmer raises | SAM dismissed | SAM $ |")
    print("|---|---|---|---|---|---|---|---|")
    for g, ks in groups.items():
        ss = [scored[k] for k in ks]
        print(f"| {g} | {len(ss)} | {sum(s['outcome'] == 'caught' for s in ss)} | {sum(s['outcome'] == 'miss' for s in ss)} | "
              f"{sum(s['outcome'].startswith('false') for s in ss)} | {sum(s['raises'] for s in ss)} | "
              f"{sum(s['dismissed'] for s in ss)} | {sum(s['sam_cost_usd'] for s in ss):.2f} |")
    (OUT / "scored.json").write_text(json.dumps(scored, indent=1))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=("render", "run", "table"))
    ap.add_argument("cases", nargs="*")
    a = ap.parse_args()
    {"render": render, "run": lambda: run(a.cases), "table": table}[a.cmd]()


if __name__ == "__main__":
    main()
