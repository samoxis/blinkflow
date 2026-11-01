"""Replay one input log through two snapshots using upstream record.replay."""

import argparse
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def json_bytes(value):
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True,
                       allow_nan=False) + "\n").encode("utf-8")


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(json_bytes(value))


def trace(recording, source):
    """No brain is imported in the parent, nor from the original checkout."""
    recording, source = Path(recording).resolve(), Path(source).resolve()
    if not (source / "brain.toml").is_file():
        raise ValueError("brain snapshot must contain brain.toml and src/microduck_brain/")
    worker = Path(__file__).with_name("_worker.py")
    completed = subprocess.run(
        [sys.executable, "-B", "-S", "-P", str(worker), str(recording), str(source)],
        env={"PYTHONPATH": str(source / "src"), "PYTHONDONTWRITEBYTECODE": "1",
             "PYTHONHASHSEED": "0", "LC_ALL": "C.UTF-8"},
        cwd=source, capture_output=True, text=True, check=True, timeout=60,
    )
    result = json.loads(completed.stdout)
    if not result["rows"]:
        raise ValueError("recording contains no ticks")
    times = [r["t"] for r in result["rows"]]
    if any(not math.isfinite(t) for t in times) or any(b <= a for a, b in zip(times, times[1:])):
        raise ValueError("recording timestamps must be finite and strictly increasing")
    if times != [r["t"] for r in result["recorded"]]:
        raise ValueError("observer tick times do not match upstream read")
    result["fingerprint"] = {
        name: sha256(source / name) for name in ["brain.toml", *result["modules"]]
    }
    return result


def recorded_match(a, b):
    """Upstream recorder rounds to 5 decimals; its replay uses 1e-4 tolerance."""
    return a[0] == b[0] and abs(a[1] - b[1]) < 1e-4 and abs(a[2] - b[2]) < 1e-4


def compare_traces(recording, a, b, impact=None):
    if a["recorded"] != b["recorded"]:
        raise ValueError("snapshots decoded different recorded ticks")
    if len(a["rows"]) != len(b["rows"]):
        raise ValueError("snapshots emitted different numbers of ticks")
    start = a["rows"][0]["t"]
    ticks = []
    for index, (ra, rb) in enumerate(zip(a["rows"], b["rows"], strict=True)):
        if ra["t"] != rb["t"]:
            raise ValueError("snapshot tick timestamps differ")
        ticks.append({"index": index, "t": ra["t"], "elapsed_s": ra["t"] - start,
                      "cmd_A": ra["cmd"], "cmd_B": rb["cmd"],
                      "state_A": ra["state"], "state_B": rb["state"], "why_B": rb["why"]})
    first = next((t for t in ticks if t["cmd_A"] != t["cmd_B"]), None)
    first_tolerant = next((t for t in ticks if not recorded_match(t["cmd_A"], t["cmd_B"])), None)
    contact = None
    if impact is not None:
        elapsed = impact["cited_tick_elapsed_s"]
        # BlinkFlow's evidence cites a timestamp rounded to milliseconds.
        matches = [t for t in ticks if round(t["elapsed_s"], 3) == elapsed]
        if len(matches) != 1:
            raise ValueError("impact citation must identify exactly one recorded tick")
        matched = matches[0]
        if impact.get("recorded_cmd") != a["recorded"][matched["index"]]["cmd"]:
            raise ValueError("impact command does not match the cited recorded tick")
        pixel_time = impact["pixel_contact_elapsed_s"]
        if not math.isfinite(pixel_time) or not 0 <= pixel_time <= ticks[-1]["elapsed_s"]:
            raise ValueError("pixel contact must lie within the recording")
        if min(ticks, key=lambda t: abs(t["elapsed_s"] - pixel_time))["index"] != matched["index"]:
            raise ValueError("cited impact tick is not nearest the pixel contact")
        contact = {"index": matched["index"], "t": matched["t"],
                   "elapsed_s": matched["elapsed_s"], "citation": impact,
                   "pixel_to_tick_offset_s": matched["elapsed_s"] - pixel_time}
    totals = {
        "ticks": len(ticks),
        "command_differences": sum(t["cmd_A"] != t["cmd_B"] for t in ticks),
        "state_differences": sum(t["state_A"] != t["state_B"] for t in ticks),
        "duration_s": ticks[-1]["elapsed_s"],
    }
    for label, run in (("A", a), ("B", b)):
        mismatches = sum(not recorded_match(row["cmd"], old["cmd"])
                         for row, old in zip(run["rows"], run["recorded"], strict=True))
        if mismatches != run["upstream"]["differing"] or len(ticks) != run["upstream"]["ticks"]:
            raise ValueError("observer disagrees with upstream replay aggregate")
        totals[f"{label}_vs_recorded_command_differences"] = mismatches
        totals[f"{label}_vs_recorded_state_differences"] = sum(
            row["state"] != old["state"] for row, old in zip(run["rows"], run["recorded"], strict=True))
    lead = contact["t"] - first["t"] if contact and first else None
    return {
        "format": 1, "mode": "open-loop decision divergence; not an outcome proof",
        "replay_engine": "microduck_brain.record.replay (pre-existing), with a per-tick observer",
        "recording_sha256": sha256(recording),
        "brain_A_sha256": a["fingerprint"], "brain_B_sha256": b["fingerprint"],
        "command_comparison": "exact kind, vx, vyaw; unrounded brain outputs",
        "recorded_comparison": "upstream tolerance: same kind, abs(speed delta) < 1e-4",
        "time_origin": "t is the original input timestamp; elapsed_s is t minus first input timestamp",
        "why_B_meaning": "upstream input safety/hold reason when holding; null otherwise; no avoidance reason exposed",
        "impact": contact, "first_divergence": first,
        "first_divergence_at_upstream_tolerance": first_tolerant,
        "lead_to_impact_tick_s": lead,
        "lead_to_pixel_contact_s": contact["citation"]["pixel_contact_elapsed_s"] - first["elapsed_s"]
        if contact and first else None,
        "diverges_before_impact_tick": first["t"] < contact["t"] if contact and first else False,
        "diverges_before_pixel_contact": first["elapsed_s"] < contact["citation"]["pixel_contact_elapsed_s"]
        if contact and first else False,
        "totals": totals, "ticks": ticks,
    }


def replay(recording, source_a, source_b, impact=None):
    return compare_traces(recording, trace(recording, source_a), trace(recording, source_b), impact)


def find_impact(recording, supplied=None):
    if supplied is not None:
        return json.loads(Path(supplied).read_text())
    sidecar = Path(recording).parent / "impact.json"
    if sidecar.is_file():
        return json.loads(sidecar.read_text())
    # The literal brief command also works on the original incident path, which
    # has no SIL sidecar. Reuse the public citation only for byte-identical input.
    example = Path(__file__).resolve().parents[2] / "examples" / "purple-box-sil"
    if (example / "run.jsonl.gz").is_file() and sha256(recording) == sha256(example / "run.jsonl.gz"):
        return json.loads((example / "impact.json").read_text())
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("recording", type=Path)
    parser.add_argument("--a", required=True, type=Path, help="snapshot root: brain.toml and src/")
    parser.add_argument("--b", required=True, type=Path, help="snapshot root: brain.toml and src/")
    parser.add_argument("--impact", type=Path, help="impact citation JSON; auto-detect impact.json beside recording")
    parser.add_argument("--out", default=Path("divergence.json"), type=Path)
    args = parser.parse_args()
    if args.impact and not args.impact.is_file():
        parser.error("explicit --impact file does not exist")
    impact = find_impact(args.recording, args.impact)
    result = replay(args.recording, args.a, args.b, impact)
    write_json(args.out, result)
    print(json.dumps({"sha256": sha256(args.out), "totals": result["totals"],
                      "first_divergence": result["first_divergence"],
                      "lead_to_impact_tick_s": result["lead_to_impact_tick_s"]}, sort_keys=True))


if __name__ == "__main__":
    main()
