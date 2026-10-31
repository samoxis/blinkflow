"""The gate is described as what it is: a filter that checks every Muse Code call against the target folder,
not an isolation (audit, Oct 31). Nothing a reader or a viewer of the console sees promises more.

    python3 -m unittest discover tests
"""
import pathlib
import re
import unittest

REPO = pathlib.Path(__file__).resolve().parent.parent
SEEN = ["README.md", "docs/SAFETY.md", "blinkflow/console/static/console.js", "docs/report/console.js"]
PROMISES = [r"in a sandbox", r"inside its sandbox", r"may only touch", r"edits only inside", r"target folder only",
            r"· sandboxed", r"\bisolated\b", r"cannot (touch|reach|leave)"]


class Wording(unittest.TestCase):
    def test_nothing_promises_isolation(self):
        for f in SEEN:
            text = (REPO / f).read_text().lower()
            for p in PROMISES:
                self.assertIsNone(re.search(p, text), f"{f}: {p}")

    def test_the_gate_is_called_a_filter(self):
        for f in ("README.md", "docs/SAFETY.md"):
            self.assertIn("not an isolation", (REPO / f).read_text(), f)


if __name__ == "__main__":
    unittest.main()


class FrozenCodePass(unittest.TestCase):
    """The Oct 28 suite pass is the frozen-code pass, said plainly: 7 of 8 repeat pass 1, it ran before the gate."""

    def test_no_held_out(self):
        for f in ("README.md", "results/bug_suite.md", "docs/SAFETY.md", "docs/RUNNING.md"):
            lines = [l for l in (REPO / f).read_text().splitlines()
                     if re.search(r"held[- ]out", l, re.I) and "It was called the held-out pass until" not in l]
            self.assertEqual(lines, [], f)

    def test_said_plainly(self):
        suite = (REPO / "results/bug_suite.md").read_text().split("## Frozen-code pass")[1]
        self.assertIn("7 of the 8 bugs in this pass repeat a first-pass mutation, and the pass ran before the current gate",
                      suite.split("\n\n")[1])
        readme = (REPO / "README.md").read_text()
        self.assertEqual(readme.count("the pass ran before the current gate"), 2)
