"""A second robot for BlinkFlow; the original repositories are read-only."""
import os
import pathlib

# Set before importing any BlinkFlow module, including its TARGET constant.
os.environ["BLINKFLOW_TARGET"] = str(pathlib.Path(__file__).resolve().parent)
