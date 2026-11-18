"""Replay a recording through a fresh brain and fingerprint every answer. Runs the same on the QNX
target and on the host, so the two fingerprints can be compared exactly.

    PYTHONPATH=src python3 probe.py RUN.jsonl.gz [brain.toml] [--dump]

Uses only the brain's own modules (microduck_brain.record.read, .brain.Brain, .config.load) and the
standard library. Prints one JSON object:
  ticks, differing (from the recorded command, at upstream's 1e-4 tolerance), first_difference_s,
  sha256 (over the exact repr of every replayed command kind, vx, vyaw and the state name), states,
  python (version, platform); with --dump also "answers", every tick's exact (kind, vx, vyaw, state).
"""
import hashlib
import json
import os
import sys

from microduck_brain import config
from microduck_brain.brain import Brain
from microduck_brain.record import read


def main(argv):
    dump = "--dump" in argv
    argv = [a for a in argv if a != "--dump"]
    path = argv[0]
    toml = argv[1] if len(argv) > 1 else ("brain.toml" if os.path.exists("brain.toml") else None)
    brain = Brain(config.load(toml))
    h = hashlib.sha256()
    ticks = differing = 0
    first = t0 = None
    states, answers = {}, []
    for tick in read(path):
        cmd = brain.tick(tick.inputs)
        state = brain.state_name
        if t0 is None:
            t0 = tick.inputs.now
        ticks += 1
        states[state] = states.get(state, 0) + 1
        answer = (cmd.kind, cmd.vx, cmd.vyaw, state)
        h.update(repr(answer).encode())
        if dump:
            answers.append([cmd.kind, repr(cmd.vx), repr(cmd.vyaw), state])
        same = cmd.kind == tick.cmd.kind and abs(cmd.vx - tick.cmd.vx) < 1e-4 and abs(cmd.vyaw - tick.cmd.vyaw) < 1e-4
        if not same:
            differing += 1
            if first is None:
                first = round(tick.inputs.now - t0, 6)
    out = {"ticks": ticks, "differing": differing, "first_difference_s": first, "sha256": h.hexdigest(),
           "states": states, "python": f"{sys.version.split()[0]} {sys.platform}"}
    if dump:
        out["answers"] = answers
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
