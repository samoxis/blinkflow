"""Compare open-loop onset against the existing deterministic-twin recordings."""

import argparse
from pathlib import Path

from .replay import compare_traces, recorded_match, sha256, trace, write_json


def check(before_recording, after_recording, source_a, source_b):
    a = trace(before_recording, source_a)
    b = trace(before_recording, source_b)
    after = trace(after_recording, source_b)
    comparison = compare_traces(before_recording, a, b)
    old, new = a["recorded"], after["recorded"]
    if len(old) != len(new) or [r["t"] for r in old] != [r["t"] for r in new]:
        raise ValueError("twin recordings must have matching tick counts and times")
    recorded_first = next((i for i, (x, y) in enumerate(zip(old, new, strict=True))
                           if x["cmd"] != y["cmd"]), None)
    first = comparison["first_divergence"]
    if first is None or recorded_first is None or first["index"] != recorded_first:
        raise ValueError("SIL divergence does not coincide with recorded twin command divergence")
    prefix = recorded_first + 1
    if any(x["inputs_sha256"] != y["inputs_sha256"] for x, y in zip(old[:prefix], new[:prefix])):
        raise ValueError("twin sensor inputs already differ at/before the first command difference")
    if a["upstream"]["differing"] or after["upstream"]["differing"]:
        raise ValueError("a twin baseline fails to reproduce its own recorded commands")
    if any(x["state"] != y["state"] for run in (a, after)
           for x, y in zip(run["rows"], run["recorded"], strict=True)):
        raise ValueError("a twin baseline fails to reproduce its recorded states")
    if not recorded_match(first["cmd_B"], new[recorded_first]["cmd"]):
        raise ValueError("fixed SIL command does not match the after-twin at divergence")
    return {
        "format": 1, "passed": True,
        "scope": "open-loop onset sanity only; later SIL inputs are not the after-twin trajectory",
        "before_recording_sha256": sha256(before_recording),
        "after_recording_sha256": sha256(after_recording),
        "ticks_per_recording": len(old), "first_divergence": first,
        "recorded_first_divergence": {"index": recorded_first, "t": old[recorded_first]["t"],
                                      "cmd_before": old[recorded_first]["cmd"],
                                      "cmd_after": new[recorded_first]["cmd"]},
        "identical_input_prefix_ticks": prefix,
        "before_baseline_command_differences": a["upstream"]["differing"],
        "after_baseline_command_differences": after["upstream"]["differing"],
        "fixed_SIL_matches_after_command_at_onset": True,
        "totals_on_before_inputs": comparison["totals"],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("before_recording", type=Path)
    parser.add_argument("after_recording", type=Path)
    parser.add_argument("--a", required=True, type=Path)
    parser.add_argument("--b", required=True, type=Path)
    parser.add_argument("--out", default=Path("twin-sanity.json"), type=Path)
    args = parser.parse_args()
    result = check(args.before_recording, args.after_recording, args.a, args.b)
    write_json(args.out, result)
    print(f"Twin onset sanity passed: tick {result['first_divergence']['index']}, "
          f"t={result['first_divergence']['t']} s")


if __name__ == "__main__":
    main()
