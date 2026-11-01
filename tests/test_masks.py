"""blinkflow.masks: the run lengths give back the mask, and every SAM 3.1 reply in the example has its decoded
masks beside it, made from its exact bytes (the report reads those, with no decoder).

    python3 -m pytest tests
"""
import hashlib
import json
import pathlib
import unittest

import numpy as np

from blinkflow import masks

EXAMPLE = pathlib.Path(__file__).resolve().parent.parent / "examples/purple-box"


class Runs(unittest.TestCase):
    def test_round_trip(self):
        rng = np.random.default_rng(0)
        for shape in ((1, 1), (3, 5), (40, 17)):
            for fill in (0.0, 0.3, 1.0):
                m = (rng.random(shape) < fill).astype(np.uint8)
                runs = masks.rle(m)
                self.assertEqual(bytes(masks.unrle(runs, m.size)), m.tobytes())

    def test_zeros_first(self):
        self.assertEqual(masks.rle(np.array([[1, 1, 0]])), [0, 2, 1])
        self.assertEqual(masks.rle(np.array([[0, 1, 1]])), [1, 2])

    def test_runs_must_cover_the_box(self):
        with self.assertRaises(ValueError):
            masks.unrle([2, 2], 5)


class Example(unittest.TestCase):
    def test_every_reply_has_its_masks(self):
        replies = sorted(EXAMPLE.rglob("sam-*.txt"))
        self.assertEqual(len(replies), 14)
        for r in replies:
            doc = json.loads(masks.path_of(r).read_text())
            self.assertEqual(doc["format"], masks.FORMAT, r)
            self.assertEqual(doc["sha256"], hashlib.sha256(r.read_bytes()).hexdigest(), r)
            for found in doc["frames"].values():
                for i in found:
                    self.assertEqual(sum(i["rle"]), i["w"] * i["h"], r)


if __name__ == "__main__":
    unittest.main()
