"""The arm (blinkflow.arm), failure paths: scope, rollback, budget and incomplete pixel evidence.
Needs MuJoCo (mujoco==3.10.0).

    python3 -m pytest tests
"""
import json
import pathlib
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from blinkflow import arm, fix
from blinkflow.arm import budget, prove, run


class Guards(unittest.TestCase):
    def setUp(self):
        self.before = arm.use_target()       # the arm's target for these tests only, then the duck's again
        self.configure = patch.object(prove.arm_see, "configure")   # SAM's arm box: not installed globally
        self.configure.start()

    def tearDown(self):
        self.configure.stop()
        arm.restore(self.before)

    def test_gate_denies_neighbor_and_absolute_paths(self):
        self.assertTrue(fix.outside("edit_file",{"path":"../README.md"}))
        self.assertTrue(fix.outside("read_file",{"path":str(pathlib.Path.home()/"duck-target/brain.toml")}))
        self.assertFalse(fix.outside("edit_file",{"path":"brain.toml"}))

    def test_rollback_preserves_unrelated_work(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=pathlib.Path(tmp)
            (root/"blinkflow/arm").mkdir(parents=True);(root/"blinkflow/arm/brain.toml").write_text("clearance = 0.0\n")
            (root/"README.md").write_text("initial\n")
            def git(*args):
                return subprocess.check_output(["git","-c","user.name=Test","-c","user.email=test@localhost",*args],cwd=root,text=True,stderr=subprocess.DEVNULL)
            git("init","-q");git("add",".");git("commit","-qm","baseline")
            base=git("rev-parse","HEAD").strip()
            (root/"blinkflow/arm/brain.toml").write_text("bad change\n")
            (root/"blinkflow/arm/unwanted.py").write_text("untracked\n")
            (root/"README.md").write_text("unrelated work\n")
            with patch.object(run,"REPO",root):run.rollback(base)
            self.assertEqual((root/"blinkflow/arm/brain.toml").read_text(),"clearance = 0.0\n")
            self.assertFalse((root/"blinkflow/arm/unwanted.py").exists())
            self.assertEqual((root/"README.md").read_text(),"unrelated work\n")

    def test_budget_keeps_prior_spend_and_refuses_before_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=pathlib.Path(tmp);(root/"examples/arm").mkdir(parents=True)
            (root/"examples/arm/models.json").write_text('{"repo_spend_usd":2.99}')
            with patch.object(budget,"STATE",root/"state"),patch.object(budget,"PRIOR",root/"examples/arm/models.json"):
                with self.assertRaisesRegex(RuntimeError,"STOP"):
                    budget.book(.02,"must not be sent")
                self.assertAlmostEqual(budget.total(),2.99)

    def test_one_missing_mask_invalidates_clean_verdict(self):
        root=arm.REPO/"examples/arm/attempt-1"
        ev=json.loads((root/"evidence/evidence.json").read_text())
        ev["tracking"]["robot"]["frames_with_mask"]-=1
        with tempfile.TemporaryDirectory() as tmp, patch.object(prove.see,"see",return_value=ev):
            v=prove.look(root/"twin/meta.json",tmp,reference=.083)
            self.assertFalse(v["valid"])
            self.assertFalse(v["fixed"])

    def test_target_tolerance_rejects_stationary_mask_clean_arm(self):
        root=arm.REPO/"examples/arm/attempt-1"
        ev=json.loads((root/"evidence/evidence.json").read_text())
        with tempfile.TemporaryDirectory() as tmp, patch.object(prove.see,"see",return_value=ev), patch.object(prove,"target_error",return_value=.0201):
            v=prove.look(root/"twin/meta.json",tmp,reference=.083)
            self.assertTrue(v["valid"])
            self.assertFalse(v["target_reached"])
            self.assertFalse(v["fixed"])


if __name__=="__main__":unittest.main()
