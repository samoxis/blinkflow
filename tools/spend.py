"""What the model calls of one day cost, per model and per provider.

    python3 tools/spend.py [--day 2026-10-27] [--root ~/blinkflow-runs]

Reads every models.json under the runs folder written that day. A loop's models.json repeats the calls of
its evidence folders, so each call is counted once, by its content (the "stage" a loop adds is ignored).
Calls an earlier run already paid for and a re-measure reused (`reused`) are not counted. A SAM 3.1 reply
taken from the cache is a call at $0 under "cache".

The daily ledgers that hold the SAM 3.1 and Muse Wonder budgets (sam-spend.jsonl, wonder-spend.jsonl) are
shown beside it: they book a call before it is sent, so they also hold tries that broke off and never
reached a models.json.
"""
import argparse
import datetime
import json
import pathlib


def provider(where):
    if where == "local":
        return "this PC"
    if where == "cached":
        return "cache"
    if "Muse Code" in where:
        return "Meta (Muse Code)"
    if "Baseten" in where:
        return "Baseten"
    if "Meta Model API" in where:
        return "Meta"
    return where


def calls_of_day(root, day):
    """{fingerprint: call} for the calls whose first appearance (oldest models.json) is on `day`."""
    seen = {}
    for f in sorted(root.rglob("models.json"), key=lambda p: p.stat().st_mtime):
        when = datetime.date.fromtimestamp(f.stat().st_mtime).isoformat()
        try:
            calls = json.loads(f.read_text())["calls"]
        except (ValueError, KeyError, OSError):
            continue
        for c in calls:
            if c.get("reused"):
                continue
            key = json.dumps({k: v for k, v in c.items() if k != "stage"}, sort_keys=True)
            seen.setdefault(key, (when, c))
    return [c for when, c in seen.values() if when == day]


def ledger(path, day):
    if not path.exists():
        return None
    return sum(e["usd"] for e in map(json.loads, path.read_text().splitlines()) if e["day"] == day)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--day", default=datetime.date.today().isoformat())
    ap.add_argument("--root", default=str(pathlib.Path.home() / "blinkflow-runs"))
    a = ap.parse_args()
    root = pathlib.Path(a.root).expanduser()
    calls = calls_of_day(root, a.day)
    rows = {}
    for c in calls:
        r = rows.setdefault((provider(c["where"]), c["model"]), {"calls": 0, "in": 0, "out": 0, "frames": 0, "usd": 0.0})
        r["calls"] += 1
        r["in"] += c.get("input_tokens") or 0
        r["out"] += c.get("output_tokens") or 0
        r["frames"] += c.get("frames") or 0
        r["usd"] += c.get("cost_usd") or 0
    print(f"# Model spend, {a.day}\n")
    print("| provider | model | calls | tokens in / out | frames | cost |")
    print("|---|---|---|---|---|---|")
    for (prov, model), r in sorted(rows.items(), key=lambda kv: (kv[0][0], -kv[1]["usd"])):
        tokens = f"{r['in']} / {r['out']}" if r["in"] or r["out"] else "-"
        print(f"| {prov} | {model} | {r['calls']} | {tokens} | {r['frames'] or '-'} | ${r['usd']:.3f} |")
    by = {}
    for (prov, _), r in rows.items():
        by[prov] = by.get(prov, 0) + r["usd"]
    print("\n" + " · ".join(f"{p} ${u:.2f}" for p, u in sorted(by.items())) + f" · **total ${sum(by.values()):.2f}**")
    sam, wonder = ledger(root / "sam-spend.jsonl", a.day), ledger(root / "wonder-spend.jsonl", a.day)
    print(f"\nBudget ledgers (booked before each call, broken-off tries included): "
          f"SAM 3.1 ${sam or 0:.2f}, Muse Wonder ${wonder or 0:.2f}.")


if __name__ == "__main__":
    main()
