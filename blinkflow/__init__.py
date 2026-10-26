import os
import pathlib

# The brain BlinkFlow works on. ~/duck-target unless BLINKFLOW_TARGET names a copy (the bug suite's).
TARGET = pathlib.Path(os.environ.get("BLINKFLOW_TARGET") or pathlib.Path.home() / "duck-target").expanduser().resolve()
if "microduck-brain" in str(TARGET):
    raise SystemExit(f"refusing target {TARGET}: never the original brain")
