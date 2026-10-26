"""Does a fix hold in the live simulator? Scorer-side check, not part of the agent.

    python3 tools/live_check.py --before <rev> --after <rev> [-n 5] [--seconds 12] [--report <fix run dir>]

Runs the live scenario (blinkflow.sim: simulator, Viser window, capture, brain for --seconds) N times
with the target checked out at each revision, alternating before / after, and counts the runs in which
the robot touched the demo box. Contacts come from the simulator's own log
(~/blinkflow-runs/contacts-*.csv), matched to each run by time. Only this scorer reads that log.
The live stack runs on four wall clocks, so runs of the same brain differ (DEVLOG, Oct 26 17:41);
hence N runs per side rather than one.
"""
import argparse
import json
import pathlib
import subprocess
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent), str(HERE)]
from blinkflow import sim  # noqa: E402
from repeatability import first_contact  # noqa: E402

TARGET = pathlib.Path.home() / "duck-target"
OUT = pathlib.Path.home() / "blinkflow-runs" / "live-check"


def git(*args):
    return subprocess.run(["git", *args], cwd=TARGET, capture_output=True, text=True, check=True).stdout.strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--before", required=True, help="target revision without the fix")
    ap.add_argument("--after", required=True, help="target revision with the fix")
    ap.add_argument("-n", type=int, default=5, help="runs per revision")
    ap.add_argument("--seconds", type=float, default=12)
    ap.add_argument("--report", help="a fix run dir: append the result to its report.md")
    a = ap.parse_args()
    if git("status", "--porcelain"):
        raise SystemExit(f"{TARGET} has uncommitted changes")
    branch = git("rev-parse", "--abbrev-ref", "HEAD")
    revs = {"before": git("rev-parse", a.before), "after": git("rev-parse", a.after)}
    out = OUT / time.strftime("%Y%m%d-%H%M%S")
    runs = []
    try:
        for i in range(a.n):
            for side in ("before", "after"):
                git("checkout", "-q", "--detach", revs[side])
                meta = sim.run(TARGET, a.seconds, f"{sim.CAM_DIR}/shots_incident.json", out / side)
                c = first_contact(meta)
                runs.append({"side": side, "rev": revs[side][:7], "run": i + 1, "snapshot": meta["path"],
                             "record": meta["record"], "contact": c is not None,
                             "first_contact_s": c and round(c[0], 3), "body": c and c[1]})
                print(json.dumps(runs[-1]), flush=True)
    finally:
        git("checkout", "-q", branch)
    summary = {}
    for side in ("before", "after"):
        rs = [r for r in runs if r["side"] == side]
        summary[side] = {"rev": revs[side][:7], "runs": len(rs), "contacts": sum(r["contact"] for r in rs),
                         "first_contact_s": [r["first_contact_s"] for r in rs if r["contact"]]}
    doc = {"seconds": a.seconds, "summary": summary, "runs": runs}
    (out / "live-check.json").write_text(json.dumps(doc, indent=1))
    print(json.dumps(summary, indent=1))
    if a.report:
        b, f = summary["before"], summary["after"]
        fmt = lambda s: ", ".join(f"{t:.2f}" for t in s["first_contact_s"]) or "-"
        text = ["", "## Live check (scorer: the simulator's own contact log)", "",
                f"The live scenario, {a.n} runs per revision, alternating, {a.seconds:.0f} s of brain each "
                f"(`tools/live_check.py`, `{out / 'live-check.json'}`).", "",
                "| target | runs | runs with contact | first contact (s after the brain starts) |", "|---|---|---|---|",
                f"| before `{b['rev']}` | {b['runs']} | {b['contacts']} | {fmt(b)} |",
                f"| after `{f['rev']}` | {f['runs']} | {f['contacts']} | {fmt(f)} |", ""]
        report = pathlib.Path(a.report).expanduser() / "report.md"
        report.write_text(report.read_text() + "\n".join(text))


if __name__ == "__main__":
    main()
