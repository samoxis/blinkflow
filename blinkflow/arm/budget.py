"""Persistent, repo-wide USD reservations; failures retain their maximum charge."""
import fcntl
import json
import pathlib
import threading
import time

from . import REPO, STATE

# the spend ledger is STATE's; a new one starts from what the public runs spent: examples/arm's ledger total
# (the clearance runs), the bug 2 and voice runs' totals, and what the first bug 2 and voice runs cost (made in
# the arm's own repo, published here until they were re-run with this loop; their ledgers are at 6b2d5a6)
PRIOR = REPO/"examples/arm/models.json"
ELSEWHERE = [REPO/"examples/arm-bug2/models.json", REPO/"examples/arm-voice/models.json"]
REPLACED = 0.18519 + 0.15471
CAP = 3.0
LOCK = threading.Lock()


def book(usd, what):
    folder = STATE/".budget"
    folder.mkdir(parents=True, exist_ok=True)
    with LOCK, (folder/"lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        p = folder/"spend.jsonl"
        if not p.exists():
            if PRIOR.exists():
                with p.open("w") as fh:
                    fh.write(json.dumps({"t":time.time(),"usd":prior(),"what":"prior public repo spend"})+"\n")
        rows = [json.loads(s) for s in p.read_text().splitlines()] if p.exists() else []
        total = sum(r["usd"] for r in rows)
        if total+usd > CAP+1e-9:
            raise RuntimeError(f"STOP: repo budget ${total:.5f} + ${usd:.5f} exceeds ${CAP:.2f}")
        with p.open("a") as fh:
            fh.write(json.dumps({"t":time.time(),"usd":usd,"what":what})+"\n")
    return usd


def total():
    p=STATE/".budget/spend.jsonl"
    if p.exists():return sum(json.loads(s)["usd"] for s in p.read_text().splitlines())
    return prior() if PRIOR.exists() else 0.


def prior():
    return (json.loads(PRIOR.read_text())["repo_spend_usd"]
            + sum(json.loads(p.read_text())["total_cost_usd"] for p in ELSEWHERE if p.exists()) + REPLACED)


def configure():
    """Reuse BlinkFlow requests, parser, cache and pricing; keep all state here."""
    from blinkflow import models, sam
    sam.CACHE=STATE/".cache/sam"
    models.SPEND=STATE/".budget/sam.jsonl"
    models.WONDER_SPEND=STATE/".budget/wonder.jsonl"
    models.reserve=lambda path,usd,budget,knob,what: book(usd,what)
    models.settle=lambda path,reserved,actual,what: book(actual-reserved,"settle "+what)
    sam.sam_reserve=lambda frames,what: book(frames*models.SAM_PER_FRAME,what)
