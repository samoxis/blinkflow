"""Persistent, repo-wide USD reservations; failures retain their maximum charge."""
import fcntl
import json
import pathlib
import threading
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
CAP = 3.0
PHASE_CAP = 2.0
PHASE = None
RUN = None
LOCK = threading.Lock()


def published_rows():
    rows=[]
    prior=ROOT/"examples/arm/models.json"
    if prior.exists():rows.append({"usd":json.loads(prior.read_text())["repo_spend_usd"],"phase":1,
                                  "run":"public:arm","what":"prior public repo spend"})
    for p in sorted((ROOT/"examples").glob("*/checkpoint.json")):
        if json.loads(p.read_text()).get("phase")==3 and (p.parent/"models.json").exists():
            d=json.loads((p.parent/"models.json").read_text())
            rows.append({"usd":d.get("run_spend_usd",d["total_cost_usd"]),"phase":3,
                         "run":"public:"+p.parent.name,"what":"prior public Phase 3 spend"})
    return rows


def book(usd, what):
    folder = ROOT/".budget"
    folder.mkdir(exist_ok=True)
    with LOCK, (folder/"lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        p = folder/"spend.jsonl"
        if not p.exists():
            with p.open("w") as fh:
                for row in published_rows():fh.write(json.dumps({"t":time.time(),**row})+"\n")
        rows = [json.loads(s) for s in p.read_text().splitlines()] if p.exists() else []
        total = sum(r["usd"] for r in rows)
        phase_total=sum(r["usd"] for r in rows if r.get("phase")==3)
        if PHASE==3 and phase_total+usd>PHASE_CAP+1e-9:
            raise RuntimeError(f"STOP: Phase 3 budget ${phase_total:.5f} + ${usd:.5f} exceeds $2.00")
        if total+usd > CAP+1e-9:
            raise RuntimeError(f"STOP: repo budget ${total:.5f} + ${usd:.5f} exceeds ${CAP:.2f}")
        with p.open("a") as fh:
            fh.write(json.dumps({"t":time.time(),"usd":usd,"what":what,"phase":PHASE,"run":RUN})+"\n")
    return usd


def total():
    p=ROOT/".budget/spend.jsonl"
    if p.exists():return sum(json.loads(s)["usd"] for s in p.read_text().splitlines())
    return sum(r["usd"] for r in published_rows())


def phase_total():
    p=ROOT/".budget/spend.jsonl"
    rows=list(map(json.loads,p.read_text().splitlines())) if p.exists() else published_rows()
    return sum(r["usd"] for r in rows if r.get("phase")==3)


def configure(phase=None,run=None):
    """Reuse BlinkFlow requests, parser, cache and pricing; keep all state here."""
    from blinkflow import models, sam
    global PHASE,RUN
    PHASE,RUN=phase,str(pathlib.Path(run).resolve()) if run else None
    sam.CACHE=ROOT/".cache/sam"
    models.SPEND=ROOT/".budget/sam.jsonl"
    models.WONDER_SPEND=ROOT/".budget/wonder.jsonl"
    models.reserve=lambda path,usd,budget,knob,what: book(usd,what)
    models.settle=lambda path,reserved,actual,what: book(actual-reserved,"settle "+what)
    sam.sam_reserve=lambda frames,what: book(frames*models.SAM_PER_FRAME,what)
