"""BlinkFlow's QNX target.

    python3 -m blinkflow.qnx vm build|up|down
    python3 -m blinkflow.qnx info
    python3 -m blinkflow.qnx walk [--brain DIR] [--seconds 20] [--out DIR]   # headless simulator, brain on QNX
    python3 -m blinkflow.qnx replay RUN.jsonl.gz [--brain DIR]                # same answers on QNX as recorded?

The full loop runs with the brain on QNX through --target qnx:
    python3 -m blinkflow.watch live --target qnx --loop
    python3 -m blinkflow.sim --target qnx
"""
import argparse
import gzip
import json
import os
import pathlib
import subprocess
import sys
import time

from .. import TARGET
from . import vm
from .target import PROBE, Target

HOME = pathlib.Path.home()
SIM = HOME / "microduck"
RUNS = HOME / "blinkflow-runs"


def states(record):
    """Seconds spent in each brain state, and tick count, from a record."""
    out, n, last = {}, 0, None
    with gzip.open(record, "rt") as f:
        next(f)
        for line in f:
            r = json.loads(line)
            if last:
                out[last[1]] = out.get(last[1], 0) + r["t"] - last[0]
            last, n = (r["t"], r["state"]), n + 1
    return n, {k: round(v, 1) for k, v in out.items()}


def walk(brain, seconds, out):
    """The demo scene without windows, the brain on QNX for `seconds`."""
    env = {**os.environ, "DUCK_SIM_SCENE": "demo", "DUCK_SIM_VIEWER": "0", "DUCK_VISER": "0",
           "DUCK_SIM_RL": str(HOME / "microduck_rl"),
           "PATH": f"{HOME}/.cargo/bin:{HOME}/.local/bin:{os.environ['PATH']}"}
    out.mkdir(parents=True, exist_ok=True)
    t = Target()
    deployed = t.deploy(brain)
    subprocess.run([str(SIM / "scripts" / "duck-sim")], cwd=SIM, env=env, check=True, stdout=subprocess.DEVNULL)
    try:
        time.sleep(5)
        b = t.launch(seconds, out / "run.jsonl.gz")
        rc = b.wait(seconds + 60)
    finally:
        subprocess.run([str(SIM / "scripts" / "duck-sim"), "down"], cwd=SIM, env=env,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    ticks, per_state = states(out / "run.jsonl.gz")
    doc = {"rc": rc, "target": t.info(), "deployed": deployed, "ticks": ticks, "seconds_per_state": per_state,
           "clock": {"epoch_offset": b.epoch_offset, "rtt_ms": round(b.rtt * 1000, 2)},
           "record": str(out / "run.jsonl.gz")}
    (out / "walk.json").write_text(json.dumps(doc, indent=1))
    return doc


def compare(q, h):
    """Verdict on two probes of the same brain and recording: identical (bit for bit), same decisions
    (every command kind and state equal, numbers apart by at most max_abs), or different decisions."""
    ticks = [i for i, (x, y) in enumerate(zip(q["answers"], h["answers"])) if x != y]
    decisions = [i for i in ticks if (q["answers"][i][0], q["answers"][i][3]) != (h["answers"][i][0], h["answers"][i][3])]
    worst = max((abs(float(q["answers"][i][k]) - float(h["answers"][i][k])) for i in ticks for k in (1, 2)), default=0.0)
    verdict = ("identical" if q["sha256"] == h["sha256"] and q["ticks"] == h["ticks"]
               else "different decisions" if decisions or q["ticks"] != h["ticks"] else "same decisions")
    return {"verdict": verdict, "ticks_apart": len(ticks), "first_tick_apart": ticks[0] if ticks else None,
            "decisions_apart": len(decisions), "max_abs": worst}


def replay(record, brain):
    """The recording through the same brain on QNX and on the host (blinkflow.qnx.probe), every answer compared."""
    brain = brain.resolve()
    t = Target()
    deployed = t.deploy(brain)
    on_qnx = t.replay(record, dump=True)
    here = subprocess.run([sys.executable, "-B", str(PROBE), str(pathlib.Path(record).resolve()), "--dump"], cwd=brain,
                          env={**os.environ, "PYTHONPATH": str(brain / "src")}, capture_output=True, text=True, check=True)
    on_host = json.loads(here.stdout)
    return {"record": str(record), "deployed": deployed, "target": t.info(), "ticks": on_qnx["ticks"],
            "differing_from_record": {"qnx": on_qnx["differing"], "host": on_host["differing"]},
            "first_difference_s": on_qnx["first_difference_s"], "states": on_qnx["states"],
            "python": {"qnx": on_qnx["python"], "host": on_host["python"]},
            "sha256": {"qnx": on_qnx["sha256"][:16], "host": on_host["sha256"][:16]},
            "qnx_vs_host": compare(on_qnx, on_host)}


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python3 -m blinkflow.qnx", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("vm", help="the QEMU target: build, up, down")
    v.add_argument("action", choices=["build", "up", "down"])
    sub.add_parser("info", help="what the target is")
    w = sub.add_parser("walk", help="headless simulator, brain on QNX")
    w.add_argument("--brain", default=str(TARGET))
    w.add_argument("--seconds", type=float, default=20)
    w.add_argument("--out", help=f"default {RUNS}/qnx-<stamp>")
    r = sub.add_parser("replay", help="replay a recording on QNX and on the host, compare")
    r.add_argument("record")
    r.add_argument("--brain", default=str(TARGET))
    a = ap.parse_args(argv)
    if a.cmd == "vm":
        res = {"build": vm.build, "up": vm.up, "down": vm.down}[a.action]()
        doc = {"vm": a.action, "pid": res, "dir": str(vm.VM)}
    elif a.cmd == "info":
        doc = Target().info()
    elif a.cmd == "walk":
        out = pathlib.Path(a.out).expanduser() if a.out else RUNS / time.strftime("qnx-%Y%m%d-%H%M%S")
        doc = walk(pathlib.Path(a.brain).expanduser(), a.seconds, out)
    else:
        doc = replay(a.record, pathlib.Path(a.brain).expanduser())
    print(json.dumps(doc, indent=1))
    apart = doc.get("qnx_vs_host", {}).get("verdict") == "different decisions"
    return 0 if doc.get("rc", 0) == 0 and not apart else 1


if __name__ == "__main__":
    sys.exit(main())
