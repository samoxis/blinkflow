"""prove.control: each scene's own obstacle is followed, and a scene where it was seen in no frame has no verdict
(audit #4, Nov 1). The example's Oct 31 control passed its low cube with a "brown step" in 0 of 220 frames.

    python3 -m pytest tests
"""
import json
import pathlib
import tempfile
import unittest
from unittest import mock

from blinkflow import prove

# the example run 20261031-235414's control evidence as it was (examples/ gets each new public run)
DATA = pathlib.Path(__file__).resolve().parent / "data"


def evidence_of(scene):
    return json.loads((DATA / f"control-{scene}-20261031.json").read_text())


def judge(ev, kind):
    with mock.patch.object(prove, "travel", return_value=2.5):
        return prove.judge(ev, record=None, kind=kind)


class Judge(unittest.TestCase):
    def test_the_examples_low_cube_has_no_verdict(self):
        ev = evidence_of("low_cube")
        self.assertEqual(ev["tracking"]["object"]["frames_with_mask"], 0)
        for kind in ("fall", "contact"):          # as named then (a hazard), and as the scene defines it
            j = judge(ev, kind)
            self.assertFalse(j["clean"])
            self.assertFalse(j["valid"])
            self.assertEqual(j["why"], "no verdict: object not seen")

    def test_a_seen_obstacle_kept_at_a_distance_is_clean(self):
        j = judge(evidence_of("corner"), "contact")
        self.assertTrue(j["clean"])
        self.assertEqual(j["why"], "no contact, no fall; closest gap 50 px")

    def test_ledge_0_px_on_screen_is_not_a_contact_and_says_why(self):
        # the gray block's mask touched the robot's on screen with the feet ~110 px above that block's base
        j = judge(evidence_of("ledge"), "contact")
        self.assertFalse(j["contact"])
        self.assertTrue(j["clean"])
        self.assertIn("closest gap 0 px on screen, the feet 110 px short of the gray block's base", j["why"])


class Control(unittest.TestCase):
    def run_control(self, object_frames):
        """control() with the twin and SAM 3.1 stubbed: -> (result, see calls)."""
        calls = []

        def see(meta, out, follow=None, tag=None, **kw):
            calls.append((pathlib.Path(out).name, follow))
            frames = object_frames if follow else 0
            return {"names": {"robot": "white robot", "object": follow[1] if follow else "something",
                              "object_is": "object", "named_by": "glimmer" if not follow else "incident"},
                    "tracking": {"robot": {"frames_with_mask": 200}, "object": {"frames_with_mask": frames}},
                    "contacts": {"whole_mask": None, "base": None, "body": None}, "base": None,
                    "fall": {"first": None}, "closest": frames and {"gap_px": 40.0, "brain_s": 9.0}}

        with tempfile.TemporaryDirectory() as tmp:
            meta = pathlib.Path(tmp) / "meta.json"
            meta.write_text(json.dumps({"record": None, "video": "x.mp4"}))
            with mock.patch.object(prove, "replay", return_value=meta), \
                    mock.patch.object(prove, "every_nth", return_value=meta), \
                    mock.patch.object(prove.see, "see", side_effect=see), \
                    mock.patch.object(prove, "travel", return_value=2.5), \
                    mock.patch.object(prove.events, "emit"):
                (pathlib.Path(tmp) / "control").mkdir()           # replay makes it in a real run
                return prove.control(pathlib.Path(tmp) / "control"), calls

    def test_each_scene_follows_its_own_obstacle_and_nothing_is_named(self):
        result, calls = self.run_control(object_frames=70)
        follows = {f for _, f in calls}
        self.assertEqual(follows, {("white robot", "orange cube"), ("white robot", "yellow floor"),
                                   ("white robot", "red barrier"), ("white robot", "blue block")})
        self.assertTrue(all(c["clean"] and c["named_by"] == "scene" for c in result.values()))
        self.assertEqual(result["ledge"]["kind"], "fall")          # the ledge is a hazard: a fall is its incident

    def test_obstacle_not_found_falls_back_to_naming_and_then_has_no_verdict(self):
        result, calls = self.run_control(object_frames=0)
        self.assertEqual(sorted(n for n, _ in calls), sorted(["evidence", "evidence-named"] * 4))
        for c in result.values():
            self.assertFalse(c["clean"])
            self.assertFalse(c["valid"])
            self.assertEqual(c["why"], "no verdict: object not seen")


if __name__ == "__main__":
    unittest.main()
