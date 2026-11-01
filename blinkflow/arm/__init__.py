"""BlinkFlow's loop on a second robot: a hand-written three-joint MuJoCo arm (scene.xml, brain.py, brain.toml).

This folder is also the arm's target: Muse Code may edit only files under it. run and recheck make it the
target with use_target(); importing the package changes nothing, so the duck's modules keep ~/duck-target.
Runs, the SAM 3.1 cache and the spend ledger live in ~/blinkflow-runs/arm (BLINKFLOW_ARM_STATE moves it).
"""
import os
import pathlib
import sys

import blinkflow

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[1]
REL = str(HERE.relative_to(REPO))                     # "blinkflow/arm", as git names it
STATE = pathlib.Path(os.environ.get("BLINKFLOW_ARM_STATE") or pathlib.Path.home() / "blinkflow-runs/arm").expanduser()
READS_TARGET = ("blinkflow", "blinkflow.fix", "blinkflow.diagnose", "blinkflow.prove")


def use_target():
    """This folder as BlinkFlow's target in every module that reads it (Muse Code's workspace, the gate, the
    audit) and for child processes. Returns the previous targets, for restore()."""
    import blinkflow.fix  # noqa: F401  (loaded now, so it is retargeted too)
    before = {m: sys.modules[m].TARGET for m in READS_TARGET if m in sys.modules}
    before["env"] = os.environ.get("BLINKFLOW_TARGET")
    for m in READS_TARGET:
        if m in sys.modules:
            sys.modules[m].TARGET = HERE
    os.environ["BLINKFLOW_TARGET"] = str(HERE)
    return before


def restore(before):
    env = before.pop("env")
    for m, t in before.items():
        sys.modules[m].TARGET = t
    if env is None:
        os.environ.pop("BLINKFLOW_TARGET", None)
    else:
        os.environ["BLINKFLOW_TARGET"] = env

