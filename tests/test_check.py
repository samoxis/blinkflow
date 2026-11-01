"""diagnose.check: "grounded" only when every check holds: the file, its lines and its function are real,
and the key frames and log ticks cited exist (audit, Oct 31); and every citation passes: no path outside the
target, no lines outside the named function, no missing frame beside a real one, no file or line that does not
exist (audit #3, Nov 1).

    python3 -m unittest discover tests
"""
import unittest

from blinkflow import diagnose

FILES = {"src/microduck_brain/depth.py": "\n".join(["# depth"] * 300 + ["def drop_zones(frame, pose, cfg):"]
                                                   + ["    pass"] * 30),
         "brain.toml": "[obstacle]\nside_memory_seconds = 0.0 # remember wall returns\nmin_zones = 2\n"}
FRAMES = [{"tag": "K1"}, {"tag": "K2"}]
TICKS = [11.20, 11.21]


def answer(file="src/microduck_brain/depth.py", function="drop_zones", start=301, end=320,
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


    # audit #3 (a): the file name matches, the path does not exist in the target
    def test_a_path_not_in_the_target_is_not_grounded_even_with_the_right_name(self):
        c = self.check(file="src/microduck_brain/planning/depth.py")
        self.assertFalse(c["file_ok"])
        self.assertFalse(c["grounded"])

    def test_a_bare_name_of_one_target_file_is_that_file(self):
        self.assertTrue(self.check(file="depth.py")["grounded"])

    # audit #3 (b): lines in the file, but not in the function the cause names
    def test_lines_outside_the_named_function_are_not_grounded(self):
        c = self.check(start=290, end=295)
        self.assertTrue(c["lines_ok"] and c["function_ok"])
        self.assertFalse(c["lines_in_function"])
        self.assertFalse(c["grounded"])

    def test_a_config_line_that_does_not_set_the_named_key_is_not_grounded(self):
        self.assertTrue(self.check(file="brain.toml", function="[obstacle] side_memory_seconds", start=2, end=2)["grounded"])
        self.assertFalse(self.check(file="brain.toml", function="[obstacle] side_memory_seconds", start=3, end=3)["grounded"])

    # audit #3 (c): one reference names a frame that was sent and one that was not
    def test_a_missing_frame_beside_a_real_one_is_not_grounded(self):
        c = self.check(refs=(("frame", "K1 K9"), ("log", "brain log t=11.20")))
        self.assertIn("K9", c["bad_refs"])
        self.assertFalse(c["grounded"])

    # audit #3 (d): any extra citation of a file or line that does not exist
    def test_an_extra_citation_of_a_missing_file_is_not_grounded(self):
        c = self.check(refs=(("frame", "K1"), ("log", "brain log t=11.20"), ("code", "src/microduck_brain/planner.py:12")))
        self.assertFalse(c["grounded"])

    def test_an_extra_citation_of_a_missing_line_is_not_grounded(self):
        c = self.check(refs=(("frame", "K1"), ("log", "brain log t=11.20"), ("code", "depth.py:305-310 and 900")))
        self.assertEqual(c["bad_refs"], ["depth.py:900"])
        self.assertFalse(c["grounded"])

    def test_real_extra_citations_stay_grounded(self):
        c = self.check(refs=(("frame", "K1"), ("log", "brain log t=11.20"),
                             ("code", "src/microduck_brain/depth.py:305-310, 312 and brain.toml line 2")))
        self.assertEqual(c["bad_refs"], [])
        self.assertTrue(c["grounded"])


if __name__ == "__main__":
    unittest.main()
