"""Isolated observer of the unmodified upstream record.replay driver."""

import json
import hashlib
from dataclasses import asdict
from pathlib import Path
import sys


def _offline(event, args):
    if event.startswith("socket."):
        raise RuntimeError("SIL replay is offline: socket operations are disabled")


sys.addaudithook(_offline)

# PYTHONPATH selects exactly one snapshot. -S -P excludes site packages and cwd.
from microduck_brain import record  # noqa: E402
from microduck_brain.config import load  # noqa: E402


def main():
    recording, source = map(Path, sys.argv[1:])
    rows = []
    original = record.Brain

    class ObservedBrain(original):
        def tick(self, inputs):
            cmd = super().tick(inputs)
            rows.append({
                "t": inputs.now,
                "cmd": [cmd.kind, cmd.vx, cmd.vyaw],
                "state": self.state_name,
                # Upstream has no avoidance-reason API. Never invent one.
                "why": (inputs.safe_reason or self.last_hold_reason or None)
                if self.state_name == "hold" else None,
            })
            return cmd

    # Only the driver module's constructor binding changes, in this subprocess.
    # super().tick and the complete upstream replay/read code remain unchanged.
    record.Brain = ObservedBrain
    try:
        result = record.replay(recording, load(source / "brain.toml"))
    finally:
        record.Brain = original
    recorded = [
        {"t": t.inputs.now, "cmd": [t.cmd.kind, t.cmd.vx, t.cmd.vyaw], "state": t.state,
         "inputs_sha256": hashlib.sha256(json.dumps(asdict(t.inputs), sort_keys=True,
             separators=(",", ":"), allow_nan=False).encode()).hexdigest()}
        for t in record.read(recording)
    ]
    modules = sorted({
        Path(module.__file__).resolve().relative_to(source).as_posix()
        for name, module in sys.modules.items()
        if name == "microduck_brain" or name.startswith("microduck_brain.")
    })
    print(json.dumps({
        "rows": rows, "recorded": recorded, "modules": modules,
        "upstream": {"ticks": result.ticks, "differing": result.differing,
                     "first_difference": result.first_difference},
    }, allow_nan=False))


if __name__ == "__main__":
    main()
