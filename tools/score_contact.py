"""How far is the first contact BlinkFlow saw from the simulator's own contact log? Scorer-side only.

    python tools/score_contact.py <evidence.json> [...]

Ground truth, never read by the agent:
  live run  ~/blinkflow-runs/contacts-*.csv  (epoch, t_sim, body), matched to the run by time;
  twin run  contacts.csv next to the twin's meta.json  (t_brain, body).
The difference is reported in frames of the clip (nearest frame to the true contact) and in seconds.
"""
import csv
import glob
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from blinkflow.see import load_snapshot  # noqa: E402

RUNS = pathlib.Path.home() / "blinkflow-runs"


def truth(snapshot_path, snap):
    """(seconds after the brain's first tick, body) of the first contact, or None."""
    if snap["kind"] == "twin":
        rows = list(csv.reader(open(pathlib.Path(snapshot_path).parent / "contacts.csv")))[1:]
        return min(((float(r[0]), r[1]) for r in rows), default=None)
    meta = json.loads(pathlib.Path(snapshot_path).read_text())
    t0, t1, hits = meta["brain_start"], meta["t1_epoch"], []
    for p in glob.glob(str(RUNS / "contacts-*.csv")):
        for r in list(csv.reader(open(p)))[1:]:
            if t0 - 1 <= float(r[0]) <= t1:
                hits.append((float(r[0]) - t0, r[2]))
    return min(hits, default=None)


def score(evidence_path):
    ev = json.loads(pathlib.Path(evidence_path).read_text())
    snap = load_snapshot(ev["snapshot"])
    gt = truth(ev["snapshot"], snap)
    seen = ev["first_contact"]
    out = {"evidence": str(evidence_path), "kind": ev["kind"], "names": [ev["names"]["robot"], ev["names"]["object"]],
           "truth": gt and {"brain_s": round(gt[0], 3), "body": gt[1]},
           "seen": seen and {"frame": seen["frame"], "brain_s": seen["brain_s"]}}
    if gt:
        times = snap["brain_time"]
        out["truth"]["frame"] = min(range(len(times)), key=lambda i: abs(times[i] - gt[0]))
    if gt and seen:
        out["delta_frames"] = seen["frame"] - out["truth"]["frame"]
        out["delta_s"] = round(seen["brain_s"] - gt[0], 3)
    return out


if __name__ == "__main__":
    print(json.dumps([score(p) for p in sys.argv[1:]], indent=1))
