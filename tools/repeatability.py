"""Do two runs of the same scenario agree? Scorer-side check, not part of the agent.

    python tools/repeatability.py runA.json runB.json [--sheet out.png]

Reports, for two snapshots taken by `blinkflow.sim`:
  * brain logs: the first tick where the commands differ;
  * video: when the incident shot's camera cut happens, seconds after the brain's first tick;
  * ground truth: first contact, seconds after the brain's first tick, from the simulator's own
    contact log (~/blinkflow-runs/contacts-*.csv). Only this scorer reads that file.
"""
import argparse
import csv
import glob
import gzip
import json
import pathlib
import subprocess

import numpy as np

W, H = 160, 125


def frames(path):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-vf", f"scale={W}:{H},format=gray",
                          "-f", "rawvideo", "-"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(-1, H, W).astype(np.float32)


def brain_log(path):
    with gzip.open(path, "rt") as f:
        next(f)
        return [json.loads(line) for line in f]


def first_contact(meta):
    """Earliest contact in any contacts file that overlaps this run, relative to the brain start."""
    t0, t1 = meta["brain_start"], meta["t1_epoch"]
    hits = []
    for p in glob.glob(str(pathlib.Path.home() / "blinkflow-runs" / "contacts-*.csv")):
        for row in list(csv.reader(open(p)))[1:]:
            if t0 - 1 <= float(row[0]) <= t1:
                hits.append((float(row[0]) - t0, row[2]))
    return min(hits) if hits else None


def cut_time(f, meta):
    """Seconds after the brain start of the hardest cut in the clip (the incident shot's camera cut)."""
    i = int(np.abs(np.diff(f, axis=0)).mean(axis=(1, 2)).argmax()) + 1
    return meta["t0_epoch"] + i / meta["fps"] - meta["brain_start"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("a")
    ap.add_argument("b")
    ap.add_argument("--sheet", help="write the contact frame of both runs side by side")
    a_ = ap.parse_args()
    A, B = (json.loads(pathlib.Path(p).read_text()) for p in (a_.a, a_.b))

    la, lb = brain_log(A["record"]), brain_log(B["record"])
    div = next((i for i, (x, y) in enumerate(zip(la, lb)) if x["cmd"] != y["cmd"]), None)
    t_div = None if div is None else la[div]["t"] - la[0]["t"]
    same_states = [r["state"] for r in la] == [r["state"] for r in lb]

    xa, xb = cut_time(frames(A["path"]), A), cut_time(frames(B["path"]), B)
    ca, cb = first_contact(A), first_contact(B)
    report = {
        "brain_logs": {"ticks": [len(la), len(lb)], "same_state_sequence": same_states,
                       "first_command_difference_s": t_div},
        "video_camera_cut_s": {"a": round(xa, 3), "b": round(xb, 3),
                               "delta_frames": round((xb - xa) * A["fps"], 1)},
        "first_contact_s": {"a": ca, "b": cb,
                            "delta_s": None if not (ca and cb) else round(cb[0] - ca[0], 3)},
    }
    print(json.dumps(report, indent=2))

    if a_.sheet and (ca or cb):
        t = (ca or cb)[0]
        ins = []
        for m in (A, B):
            ins += ["-ss", f"{m['brain_start'] + t - m['t0_epoch']:.3f}", "-i", m["path"]]
        subprocess.run(["ffmpeg", "-v", "error", "-y", *ins, "-filter_complex",
                        "[0:v]scale=640:-2[l];[1:v]scale=640:-2[r];[l][r]hstack",
                        "-frames:v", "1", a_.sheet], check=True)


if __name__ == "__main__":
    main()
