import gzip
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from blinkflow.sil.recheck import DEFAULT_EXAMPLE, inventory, recheck, verify_inventory
from blinkflow.sil.replay import compare_traces, find_impact, json_bytes, replay, sha256, trace
from blinkflow.sil.report import markdown
from blinkflow.sil.sanity import check as twin_check


class IncidentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.example = DEFAULT_EXAMPLE
        cls.recording = cls.example / "run.jsonl.gz"
        cls.a, cls.b = (cls.example / f"brain-{name}" for name in ("before", "after"))
        cls.impact = json.loads((cls.example / "impact.json").read_text())
        cls.data = replay(cls.recording, cls.a, cls.b, cls.impact)

    def test_two_fresh_replays_are_byte_identical_to_published_result(self):
        second = replay(self.recording, self.a, self.b, self.impact)
        first_bytes, second_bytes = json_bytes(self.data), json_bytes(second)
        self.assertEqual(first_bytes, second_bytes)
        self.assertEqual(first_bytes, (self.example / "divergence.json").read_bytes())
        self.assertEqual(hashlib.sha256(first_bytes).hexdigest(), sha256(self.example / "divergence.json"))

    def test_same_brain_has_zero_divergence(self):
        data = replay(self.recording, self.a, self.a, self.impact)
        self.assertEqual(data["totals"]["command_differences"], 0)
        self.assertEqual(data["totals"]["state_differences"], 0)
        self.assertIsNone(data["first_divergence"])
        self.assertIsNone(data["lead_to_impact_tick_s"])
        self.assertFalse(data["diverges_before_impact_tick"])
        self.assertIn("does not diverge before the recorded impact tick", markdown(data))
        self.assertIn("No command divergence", markdown(data))

    def test_measured_fix_diverges_before_both_impact_references(self):
        data = self.data
        first = data["first_divergence"]
        self.assertEqual(first["index"], 42)
        self.assertEqual(first["t"], 54904.671337092)
        self.assertAlmostEqual(first["elapsed_s"], 2.10486630199739, places=10)
        self.assertEqual(first["cmd_A"], ["move", 0.24, 0.2552380952380953])
        self.assertEqual(first["cmd_B"], ["move", 0.24, 0.25531240141981854])
        self.assertEqual((first["state_A"], first["state_B"]), ("forward", "forward"))
        self.assertLess(abs(first["cmd_B"][2] - first["cmd_A"][2]), 1e-4)
        self.assertEqual(data["first_divergence_at_upstream_tolerance"]["index"], 50)
        self.assertEqual(data["impact"]["index"], 218)
        self.assertAlmostEqual(data["lead_to_impact_tick_s"], 8.820459136004501, places=10)
        self.assertAlmostEqual(data["lead_to_pixel_contact_s"], 8.79813369800261, places=9)
        self.assertTrue(data["diverges_before_impact_tick"])
        self.assertTrue(data["diverges_before_pixel_contact"])
        self.assertEqual(data["totals"]["command_differences"], 236)
        self.assertEqual(data["totals"]["A_vs_recorded_command_differences"], 0)
        self.assertEqual(data["totals"]["A_vs_recorded_state_differences"], 0)

    def test_late_divergence_is_reported_as_negative(self):
        a = trace(self.recording, self.a)
        b = trace(self.recording, self.a)
        # Fabricated measurement probe, never a claim about the known fix.
        b["rows"][-1]["cmd"] = ["move", 0.0, 1.4]
        b["upstream"]["differing"] = 1
        data = compare_traces(self.recording, a, b, self.impact)
        self.assertLess(data["lead_to_impact_tick_s"], 0)
        self.assertFalse(data["diverges_before_impact_tick"])
        self.assertIn("does not diverge before the recorded impact tick", markdown(data))

    def test_twin_onset_matches_actual_after_run(self):
        result = twin_check(self.example / "sanity/before.jsonl.gz",
                            self.example / "sanity/after.jsonl.gz", self.a, self.b)
        self.assertTrue(result["passed"])
        self.assertEqual(result["first_divergence"]["index"], 34)
        self.assertEqual(result["first_divergence"]["t"], 4.7)
        self.assertEqual(result["identical_input_prefix_ticks"], 35)
        self.assertEqual(result["before_baseline_command_differences"], 0)
        self.assertEqual(result["after_baseline_command_differences"], 0)
        self.assertEqual(json_bytes(result), (self.example / "twin-sanity.json").read_bytes())

    def test_recheck_works_with_python_socket_operations_denied(self):
        # Parent hook and each worker hook fail on any attempted socket use.
        program = (
            "import runpy,sys\n"
            "def offline(event,args):\n"
            "    if event.startswith('socket.'): raise RuntimeError('network forbidden by test')\n"
            "sys.addaudithook(offline)\n"
            "sys.argv=['blinkflow.sil.recheck']\n"
            "runpy.run_module('blinkflow.sil.recheck',run_name='__main__')\n"
        )
        run = subprocess.run([sys.executable, "-B", "-c", program],
                             cwd=Path(__file__).resolve().parent.parent,
                             capture_output=True, text=True, check=True, timeout=60)
        result = json.loads(run.stdout)
        self.assertTrue(result["passed"])
        self.assertTrue(result["twin_sanity_passed"])
        self.assertEqual(result["divergence_sha256"], sha256(self.example / "divergence.json"))

    def test_recheck_from_relocated_bundle_and_detects_tampering(self):
        with tempfile.TemporaryDirectory() as temp:
            copied = Path(temp) / "bundle"
            shutil.copytree(self.example, copied)
            self.assertTrue(recheck(copied)["passed"])
            with (copied / "brain-after/brain.toml").open("a") as stream:
                stream.write("\n# tampered test copy\n")
            with self.assertRaisesRegex(ValueError, "integrity mismatch"):
                recheck(copied)

    def test_impact_citation_must_match_one_real_tick_and_its_command(self):
        for change, message in (({"cited_tick_elapsed_s": 10.0}, "exactly one"),
                                ({"recorded_cmd": ["stop", 0.0, 0.0]}, "command"),
                                ({"pixel_contact_elapsed_s": 1.0}, "nearest")):
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, message):
                replay(self.recording, self.a, self.b, {**self.impact, **change})

    def test_known_recording_without_sidecar_gets_hash_bound_citation(self):
        with tempfile.TemporaryDirectory() as temp:
            copied = Path(temp) / "incident.gz"
            shutil.copyfile(self.recording, copied)
            self.assertEqual(find_impact(copied), self.impact)
            copied.write_bytes(b"unrelated recording")
            self.assertIsNone(find_impact(copied))

    def test_unknown_format_and_empty_recording_fail(self):
        with tempfile.TemporaryDirectory() as temp:
            recording = Path(temp) / "bad.jsonl"
            recording.write_text('{"kind":"other", "format":1}\n')
            with self.assertRaises(subprocess.CalledProcessError) as failure:
                replay(recording, self.a, self.b)
            self.assertIn("not a microduck-brain recording", failure.exception.stderr)
            recording.write_text('{"kind":"microduck-brain-run", "format":1}\n')
            with self.assertRaisesRegex(ValueError, "no ticks"):
                replay(recording, self.a, self.b)

    def test_worker_does_not_inherit_credentials_or_ambient_pythonpath(self):
        with tempfile.TemporaryDirectory() as temp:
            copied = Path(temp) / "brain"
            shutil.copytree(self.a, copied)
            init = copied / "src/microduck_brain/__init__.py"
            with init.open("a") as stream:
                stream.write("\nimport os\nassert 'SIL_TEST_CREDENTIAL' not in os.environ\n")
            with patch.dict("os.environ", {"SIL_TEST_CREDENTIAL": "synthetic-test-marker",
                                            "PYTHONPATH": str(self.b / "src")}):
                result = replay(self.recording, copied, self.a)
            self.assertEqual(result["totals"]["command_differences"], 0)

    def test_worker_audit_hook_blocks_socket_creation(self):
        with tempfile.TemporaryDirectory() as temp:
            copied = Path(temp) / "brain"
            shutil.copytree(self.a, copied)
            with (copied / "src/microduck_brain/__init__.py").open("a") as stream:
                stream.write("\nimport socket\nsocket.socket()\n")
            with self.assertRaises(subprocess.CalledProcessError) as failure:
                trace(self.recording, copied)
            self.assertIn("socket operations are disabled", failure.exception.stderr)

    def test_minimal_snapshot_import_closure_and_complete_public_scan(self):
        pattern = re.compile(
            rb"/home/|/mnt/[a-z]/users/|[a-z]:[\\/]users[\\/]|"
            rb"sk-[a-z0-9]{16,}|gh[pousr]_[a-z0-9]{20,}|"
            rb"BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY", re.I)
        for p in self.example.rglob("*"):
            if not p.is_file():
                continue
            raw = gzip.decompress(p.read_bytes()) if p.suffix == ".gz" else p.read_bytes()
            self.assertIsNone(pattern.search(raw), p.relative_to(self.example))
        for source in (self.a, self.b):
            imported = trace(self.recording, source)["modules"]
            expected = {"brain.toml", "LICENSE", "NOTICE", *imported}
            actual = {p.relative_to(source).as_posix() for p in source.rglob("*") if p.is_file()}
            self.assertEqual(expected, actual)
        self.assertEqual(inventory(self.example), verify_inventory(self.example))


if __name__ == "__main__":
    unittest.main()
