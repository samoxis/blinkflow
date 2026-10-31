"""fix.fix: the control in every other scene is part of the acceptance (audit, Oct 31). A change that removes
the incident but leaves another scene not clean is undone and never committed; "fixed", the clock's stop and
the commit come only after a clean control; --skip-control is the only way round it, and it is reported.
Every model, render and git call is replaced: nothing here touches the target or the network.

    python3 -m unittest discover tests
"""
import contextlib
import io
import json
import pathlib
import tempfile
import unittest
from unittest import mock

from blinkflow import fix

BEFORE = {"valid": True, "incident": True, "fixed": False, "incident_s": 11.46, "first_contact_s": 11.46,
          "reading": "base", "travel_m": 3.0, "fell_s": None, "closest_gap_px": 0, "closest_s": 11.46}
GONE = {"valid": True, "incident": False, "fixed": True, "incident_s": None, "fell_s": None, "problems": [],
        "closest_gap_px": 106.0, "closest_s": 12.1, "travel_m": 2.8}
CHANGE = {"diff": "-a = 1\n+a = 2\n", "stat": "1 file changed", "files": ["brain.toml"]}


def scenes(dirty=()):
    return {s: {"clean": s not in dirty, "why": "touched the gray block at t = 6.10 s" if s in dirty else "no contact, no fall",
                "names": ["white robot", "gray block"]} for s in ("low_cube", "ledge", "corner", "doorway")}


class Control(unittest.TestCase):
    def run_fix(self, controls, attempts, control=True):
        """The loop with `controls` as prove.control's answers, one per call -> (done, calls in order)."""
        tmp = pathlib.Path(tempfile.mkdtemp())
        ev = tmp / "incident"
        ev.mkdir()
        (ev / "evidence.json").write_text(json.dumps({"names": {"robot": "white robot", "object": "purple box"},
                                                      "incident": "contact"}))
        (ev / "diagnosis.json").write_text(json.dumps({"cause_key": "brain.toml::[obstacle] margin",
                                                       "cause": {"what": "the margin is too small."}}))
        order = []
        mc = {"seconds": 20.0, "outcome": "completed", "summary": "widened the margin", "problems": [],
              "session": "s", "change": CHANGE}
        patches = [
            mock.patch.object(fix, "checkpoint", return_value="base0000"),
            mock.patch.object(fix, "undo", side_effect=lambda base, why="": order.append(("undo", why))),
            mock.patch.object(fix, "git", side_effect=lambda *a, **k: order.append(("git",) + a) or "fix00000\n"),
            mock.patch.object(fix, "muse_code", return_value=mc),
            mock.patch.object(fix, "finish", side_effect=lambda run, snap, evdir, ev, diag, done, *a: done),
            mock.patch.object(fix, "diagnosis_text", return_value=""),
            mock.patch.object(fix, "workspace_text", return_value={}),
            mock.patch.object(fix, "PROMPT", "{incident}{diagnosis}"),
            mock.patch.object(fix.events, "begin"), mock.patch.object(fix.events, "clock", return_value=0.0),
            mock.patch.object(fix.events, "emit", side_effect=lambda kind, **k: order.append(("emit", kind))),
            mock.patch.object(fix.models, "warm_glimmer"), mock.patch.object(fix.models, "glimmer_vram", return_value={}),
            mock.patch.object(fix.diagnose, "diagnose"),
            mock.patch.object(fix.prove, "render", return_value=(tmp / "meta.json", 1.0)),
            mock.patch.object(fix.prove, "look", return_value=BEFORE),
            mock.patch.object(fix.prove, "prove", return_value=GONE),
            mock.patch.object(fix.prove, "control", side_effect=lambda out: order.append(("control",)) or controls.pop(0)),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        done = fix.fix(tmp / "snap.json", evidence=ev, attempts=attempts, out=tmp / "run", control=control)
        return done, order

    def test_dirty_control_rolls_back(self):
        done, order = self.run_fix([scenes(dirty=("low_cube",))], attempts=1)
        self.assertFalse(done["fixed"])
        self.assertFalse(done["kept"])
        self.assertTrue(done["attempts"][0]["control_failed"])
        self.assertIn("control was not clean", done["stopped"])
        self.assertTrue(any(o[0] == "undo" and "control is not clean" in o[1] for o in order))
        self.assertFalse(any(o[:2] == ("git", "commit") for o in order))
        self.assertNotIn(("emit", "clock.stop"), order)

    def test_dirty_then_clean_retries_and_stops_the_clock_after_control(self):
        done, order = self.run_fix([scenes(dirty=("ledge",)), scenes()], attempts=2)
        self.assertTrue(done["fixed"] and done["kept"])
        self.assertEqual([a["kept"] for a in done["attempts"]], [False, True])
        self.assertNotIn("stopped", done)
        last_control = max(i for i, o in enumerate(order) if o == ("control",))
        self.assertGreater(order.index(("emit", "clock.stop")), last_control)
        self.assertGreater(next(i for i, o in enumerate(order) if o[:2] == ("git", "commit")), last_control)

    def test_skip_control_is_explicit_and_reported(self):
        done, order = self.run_fix([], attempts=1, control=False)
        self.assertTrue(done["fixed"])
        self.assertTrue(done["control_skipped"])
        self.assertNotIn(("control",), order)

    def test_auto_keeps_the_control(self):
        with mock.patch("sys.argv", ["fix", "snap.json", "--auto"]), \
             mock.patch.object(fix, "fix", return_value={"run": "r", "fixed": False, "kept": False, "seconds": 0,
                                                          "attempts": []}) as f, \
             contextlib.redirect_stdout(io.StringIO()):
            fix.main()
        self.assertIs(f.call_args.args[-1], True)


if __name__ == "__main__":
    unittest.main()
