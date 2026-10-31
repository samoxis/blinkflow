"""diagnose.check: "grounded" only when every check holds: the file, its lines and its function are real,
and the key frames and log ticks cited exist (audit, Oct 31).

    python3 -m unittest discover tests
"""
import unittest

from blinkflow import diagnose

FILES = {"src/microduck_brain/depth.py": "\n".join(["# depth"] * 300 + ["def drop_zones(frame, pose, cfg):"]
                                                   + ["    pass"] * 30)}
FRAMES = [{"tag": "K1"}, {"tag": "K2"}]
TICKS = [11.20, 11.21]


def answer(file="src/microduck_brain/depth.py", function="drop_zones", start=300, end=320,
           refs=(("frame", "K1"), ("log", "brain log t=11.20"))):
    return {"cause": {"file": file, "function": function, "lines": {"start": start, "end": end}},
            "evidence": [{"source": s, "ref": r} for s, r in refs]}


class Check(unittest.TestCase):
    def check(self, **kw):
        return diagnose.check(answer(**kw), FILES, FRAMES, TICKS)

    def test_everything_real_is_grounded(self):
        self.assertTrue(self.check()["grounded"])

    def test_file_not_in_target_is_not_grounded(self):
        # the audit's case: frames and ticks cited, but the file is not the target's
        c = self.check(file="src/microduck_brain/planner.py")
        self.assertFalse(c["file_ok"])
        self.assertTrue(c["frames_cited"] and c["log_ticks_cited"])
        self.assertFalse(c["grounded"])

    def test_lines_past_the_end_are_not_grounded(self):
        self.assertFalse(self.check(start=320, end=900)["grounded"])

    def test_function_not_in_file_is_not_grounded(self):
        self.assertFalse(self.check(function="plan_route")["grounded"])

    def test_no_key_frame_cited_is_not_grounded(self):
        self.assertFalse(self.check(refs=(("log", "brain log t=11.20"),))["grounded"])

    def test_a_frame_that_was_not_sent_is_not_grounded(self):
        self.assertFalse(self.check(refs=(("frame", "K1"), ("frame", "K9"), ("log", "brain log t=11.20")))["grounded"])

    def test_a_tick_that_does_not_exist_is_not_grounded(self):
        self.assertFalse(self.check(refs=(("frame", "K1"), ("log", "brain log t=4.00")))["grounded"])


if __name__ == "__main__":
    unittest.main()
