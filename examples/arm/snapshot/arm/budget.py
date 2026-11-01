"""Persistent, repo-wide USD reservations; failures retain their maximum charge."""
import fcntl
import json
import pathlib
import threading
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
CAP = 3.0
LOCK = threading.Lock()


def book(usd, what):
    folder = ROOT/".budget"
    folder.mkdir(exist_ok=True)
    with LOCK, (folder/"lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        p = folder/"spend.jsonl"
        if not p.exists():
            prior=ROOT/"examples/arm/models.json"
            if prior.exists():
                with p.open("w") as fh:
                    fh.write(json.dumps({"t":time.time(),"usd":json.loads(prior.read_text())["repo_spend_usd"],
                                         "what":"prior public repo spend"})+"\n")
        rows = [json.loads(s) for s in p.read_text().splitlines()] if p.exists() else []
        total = sum(r["usd"] for r in rows)
        if total+usd > CAP+1e-9:
            raise RuntimeError(f"STOP: repo budget ${total:.5f} + ${usd:.5f} exceeds ${CAP:.2f}")
        with p.open("a") as fh:
            fh.write(json.dumps({"t":time.time(),"usd":usd,"what":what})+"\n")
    return usd


def total():
    p=ROOT/".budget/spend.jsonl"
    if p.exists():return sum(json.loads(s)["usd"] for s in p.read_text().splitlines())
    prior=ROOT/"examples/arm/models.json"
    return json.loads(prior.read_text())["repo_spend_usd"] if prior.exists() else 0.


def configure():
    """Reuse BlinkFlow requests, parser, cache and pricing; keep all state here."""
    from blinkflow import models, sam
    sam.CACHE=ROOT/".cache/sam"
    models.SPEND=ROOT/".budget/sam.jsonl"
    models.WONDER_SPEND=ROOT/".budget/wonder.jsonl"
    models.reserve=lambda path,usd,budget,knob,what: book(usd,what)
    models.settle=lambda path,reserved,actual,what: book(actual-reserved,"settle "+what)
    sam.sam_reserve=lambda frames,what: book(frames*models.SAM_PER_FRAME,what)
