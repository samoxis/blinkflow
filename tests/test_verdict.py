"""prove.verdict: a fix is the incident gone, the robot on its feet and still walking (audit, Oct 31).

    python3 -m unittest discover tests
"""
import unittest
from unittest import mock

from blinkflow import prove


def evidence(contact_s=None, fell_s=None):
    """SAM 3.1's evidence as see.py writes it, reduced to what verdict reads."""
    hit = contact_s and {"brain_s": contact_s, "frame": 100}
    return {"contacts": {"whole_mask": hit, "base": hit, "body": None}, "base": {"found": True},
            "fall": {"first": fell_s and {"brain_s": fell_s, "reading": "pixels"}},
            "tracking": {"robot": {"frames_with_mask": 120}, "object": {"frames_with_mask": 300}},
            "closest": {"gap_px": 40.0, "brain_s": 3.5}}


def verdict(ev, walked, reference=3.0, kind="contact"):
    with mock.patch.object(prove, "travel", return_value=walked):
        return prove.verdict(ev, record=None, reference_travel=reference, kind=kind)


class Verdict(unittest.TestCase):
    def test_fell_at_4s_without_contact_is_not_a_fix(self):
        # the audit's case: no contact, because the robot fell at 4 s
        v = verdict(evidence(fell_s=4.0), walked=2.9)
        self.assertFalse(v["incident"])
        self.assertEqual(v["fell_s"], 4.0)
        self.assertFalse(v["fixed"])

    def test_no_contact_no_fall_walking_is_a_fix(self):
        self.assertTrue(verdict(evidence(), walked=2.9)["fixed"])

    def test_standing_still_is_not_a_fix(self):
        v = verdict(evidence(), walked=0.2)
        self.assertFalse(v["valid"])
        self.assertFalse(v["fixed"])

    def test_no_distance_to_compare_is_not_a_fix(self):
        self.assertFalse(verdict(evidence(), walked=2.9, reference=None)["fixed"])

    def test_contact_again_is_not_a_fix(self):
        v = verdict(evidence(contact_s=11.46), walked=2.9)
        self.assertTrue(v["incident"])
        self.assertFalse(v["fixed"])

    def test_fall_incident_still_falling_is_not_a_fix(self):
        v = verdict(evidence(fell_s=10.25), walked=2.9, kind="fall")
        self.assertTrue(v["incident"])
        self.assertFalse(v["fixed"])


if __name__ == "__main__":
    unittest.main()
