"""blinkflow.qnx.probe and the QNX-vs-host verdict, on the host only (no VM, no key, no simulator).

    python3 -m unittest tests.test_qnx_probe -v
"""
import json
import pathlib
import subprocess
import sys
import unittest

from blinkflow.qnx.__main__ import compare
from blinkflow.qnx.target import PROBE

SIL = pathlib.Path(__file__).resolve().parent.parent / "examples" / "purple-box-sil"


def probe(brain, *extra):
    r = subprocess.run([sys.executable, "-B", str(PROBE), str(SIL / "run.jsonl.gz"), *extra], cwd=brain,
                       env={"PYTHONPATH": str(brain / "src")}, capture_output=True, text=True, check=True)
    return json.loads(r.stdout)


class Probe(unittest.TestCase):
    def test_recording_brain_reproduces_its_run(self):
        p = probe(SIL / "brain-before")
        self.assertEqual((p["ticks"], p["differing"]), (289, 0))

    def test_fixed_brain_answers_differently(self):
        p = probe(SIL / "brain-after")
        self.assertEqual(p["ticks"], 289)
        self.assertGreater(p["differing"], 200)


class Verdict(unittest.TestCase):
    def setUp(self):
        self.a = probe(SIL / "brain-before", "--dump")

    def variant(self, i, field, value):
        b = json.loads(json.dumps(self.a))
        b["answers"][i][field] = value
        b["sha256"] = "changed"
        return b

    def test_identical(self):
        self.assertEqual(compare(self.a, self.a)["verdict"], "identical")

    def test_one_ulp_is_same_decisions(self):
        vyaw = float(self.a["answers"][100][2])
        b = self.variant(100, 2, repr(vyaw + 1.1102230246251565e-16 if vyaw else 5e-324))
        v = compare(self.a, b)
        self.assertEqual((v["verdict"], v["ticks_apart"], v["first_tick_apart"]), ("same decisions", 1, 100))

    def test_other_state_is_different_decisions(self):
        b = self.variant(100, 3, "brake")
        self.assertEqual(compare(self.a, b)["verdict"], "different decisions")


if __name__ == "__main__":
    unittest.main()
