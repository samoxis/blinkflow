"""Empirical frozen-code cases plus labelled controls for every classification."""

from collections import Counter
import copy
import gzip
import hashlib
import json
from pathlib import Path
import re
import shutil
import tempfile
import unittest

from blinkflow.sil.recheck import recheck_suite, verify_inventory
from blinkflow.sil.replay import compare_traces, json_bytes, trace
from blinkflow.sil.suite import (CASE_ORDER, CLASSES, DEFAULT_SUITE, analyze, load_cases,
                       measure_case, report_markdown, summary_markdown)


def fabricated_trace(changes):
    """Classification probes only: these are not measured suite cases."""
    ticks = [{"index": i, "t": float(i), "elapsed_s": float(i),
              "cmd_A": ["move", 0.24, 0.1], "cmd_B": ["move", 0.24, 0.1],
              "state_A": "forward", "state_B": "forward", "why_B": None}
             for i in range(6)]
    ticks[0].update(cmd_A=["stop", 0.0, 0.0], cmd_B=["stop", 0.0, 0.0],
                    state_A="hold", state_B="hold")
    for index, change in changes.items():
        ticks[index].update(change)
    return {"ticks": ticks,
            "first_divergence": next((t for t in ticks if t["cmd_A"] != t["cmd_B"]), None),
            "impact": {"t": 4.0, "index": 4, "elapsed_s": 4.0,
                       "citation": {"pixel_contact_elapsed_s": 4.01, "event_kind": "contact"}}}


class ClassificationTests(unittest.TestCase):
    def test_discrete_stop_at_first_difference_is_supported(self):
        analysis = analyze(fabricated_trace({2: {"cmd_B": ["stop", 0.0, 0.0], "state_B": "brake"}}))
        self.assertEqual(analysis["classification"], CLASSES[0])
        self.assertEqual(analysis["first_state_divergence"]["index"], 2)
        self.assertEqual(analysis["supported_discrete_decision"]["index"], 2)
        self.assertEqual(analysis["first_B_stop_or_turn_command"]["index"], 0)
        self.assertEqual(analysis["first_B_differential_stop_or_turn"]["index"], 2)

    def test_continuous_first_is_not_promoted_by_later_preimpact_stop(self):
        analysis = analyze(fabricated_trace({1: {"cmd_B": ["move", 0.24, 0.100000001]},
                                            2: {"cmd_B": ["stop", 0.0, 0.0], "state_B": "brake"}}))
        self.assertEqual(analysis["classification"], CLASSES[1])
        self.assertEqual(analysis["first_state_divergence"]["lead_to_impact_tick_s"], 2.0)
        self.assertFalse(analysis["first_state_divergence"]["within_shared_command_prefix"])
        self.assertIsNone(analysis["supported_discrete_decision"])

    def test_no_difference_and_at_or_after_impact_are_negative(self):
        for changes in ({}, {4: {"cmd_B": ["stop", 0.0, 0.0], "state_B": "brake"}},
                        {5: {"cmd_B": ["stop", 0.0, 0.0], "state_B": "brake"}}):
            with self.subTest(changes=changes):
                analysis = analyze(fabricated_trace(changes))
                self.assertEqual(analysis["classification"], CLASSES[2])
                self.assertIsNone(analysis["supported_discrete_decision"])

    def test_in_place_turn_is_decisive_but_walking_steering_is_continuous(self):
        turn = analyze(fabricated_trace({2: {"cmd_B": ["move", 0.0, 1.4], "state_B": "turn"}}))
        steer = analyze(fabricated_trace({2: {"cmd_B": ["move", 0.24, 1.4]}}))
        self.assertEqual(turn["classification"], CLASSES[0])
        self.assertEqual(steer["classification"], CLASSES[1])
        self.assertIsNone(steer["first_B_differential_stop_or_turn"])


class FrozenSuiteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = DEFAULT_SUITE
        _, cls.cases = load_cases(cls.root)
        cls.results = {m["bug"]: measure_case(cls.root / m["bug"]) for m in cls.cases}

    def test_all_eight_empirical_results_in_original_order(self):
        self.assertEqual(tuple(self.results), CASE_ORDER)
        expected = {
            "b3": (145, 145, 2.85, CLASSES[0]),
            "b4": (68, 118, 6.7, CLASSES[1]),
            "b6": (34, 176, 10.7, CLASSES[1]),
            "b7": (37, 37, 8.2, CLASSES[0]),
            "b8": (34, 112, 16.7, CLASSES[1]),
            "b9": (68, 118, 6.7, CLASSES[1]),
            "b10": (37, 37, 8.2, CLASSES[0]),
            "b11": (37, 37, 8.2, CLASSES[0]),
        }
        for bug, (exact, state, lead, label) in expected.items():
            with self.subTest(bug=bug):
                data = self.results[bug]
                analysis = data["suite_analysis"]
                self.assertEqual(analysis["first_exact_divergence"]["index"], exact)
                self.assertEqual(analysis["first_state_divergence"]["index"], state)
                self.assertAlmostEqual(analysis["first_exact_divergence"]["lead_to_impact_tick_s"], lead)
                self.assertEqual(analysis["classification"], label)
                self.assertEqual(analysis["first_B_stop_or_turn_command"]["index"], 0)
                self.assertEqual(analysis["first_B_differential_stop_or_turn"]["cmd_B"], ["stop", 0.0, 0.0])
                self.assertEqual(data["totals"]["A_vs_recorded_command_differences"], 0)
                self.assertEqual(data["totals"]["A_vs_recorded_state_differences"], 0)
        counts = Counter(d["suite_analysis"]["classification"] for d in self.results.values())
        self.assertEqual(counts, {CLASSES[0]: 4, CLASSES[1]: 4})

    def test_two_fresh_replays_per_case_match_published_bytes(self):
        for bug, first in self.results.items():
            with self.subTest(bug=bug):
                second = measure_case(self.root / bug)
                self.assertEqual(json_bytes(first), json_bytes(second))
                self.assertEqual(json_bytes(first), (self.root / bug / "divergence.json").read_bytes())

    def test_real_recorded_A_equals_A_control_has_no_divergence(self):
        # A measured negative control, not a ninth suite bug or an invented failure.
        case = self.root / "b3"
        a = trace(case / "run.jsonl.gz", case / "brain-before")
        b = trace(case / "run.jsonl.gz", case / "brain-before")
        data = compare_traces(case / "run.jsonl.gz", a, b,
                              json.loads((case / "impact.json").read_text()))
        analysis = analyze(data)
        self.assertEqual(data["totals"]["command_differences"], 0)
        self.assertEqual(analysis["classification"], CLASSES[2])
        self.assertIsNone(analysis["first_exact_divergence"])
        self.assertIsNone(analysis["first_state_divergence"])
        self.assertIsNone(analysis["first_B_differential_stop_or_turn"])
        data["suite_analysis"] = analysis
        self.assertIn("no-divergence-before-impact", report_markdown(self.cases[0], data))

    def test_phase1_is_continuous_only_under_the_same_policy(self):
        # Add only the event-kind adapter key in memory; published bytes stay unchanged.
        data = json.loads((self.root.parent / "purple-box-sil/divergence.json").read_text())
        data["impact"]["citation"]["event_kind"] = "contact"
        analysis = analyze(data)
        self.assertEqual(analysis["classification"], CLASSES[1])
        self.assertEqual(analysis["first_exact_divergence"]["index"], 42)
        self.assertFalse(analysis["first_state_divergence"]["within_shared_command_prefix"])

    def test_public_event_times_are_saved_pixels_not_scorer_times(self):
        for bug in ("b3", "b4", "b9"):
            self.assertEqual(self.results[bug]["suite_analysis"]["pixel_event_elapsed_s"], 10.125)
            self.assertAlmostEqual(self.results[bug]["impact"]["elapsed_s"], 10.1)
        for bug in ("b7", "b10", "b11"):
            analysis = self.results[bug]["suite_analysis"]
            self.assertEqual(analysis["pixel_event_kind"], "fall")
            self.assertEqual(analysis["pixel_event_elapsed_s"], 10.055)
            self.assertAlmostEqual(self.results[bug]["impact"]["elapsed_s"], 10.05)
            self.assertAlmostEqual(analysis["first_state_divergence"]["lead_to_saved_pixel_event_s"], 8.205)

    def test_recheck_full_suite_and_reject_tampering_and_order_changes(self):
        self.assertEqual(recheck_suite(self.root)["processed"], 8)
        with tempfile.TemporaryDirectory() as temp:
            copied = Path(temp) / "suite"
            shutil.copytree(self.root, copied)
            self.assertTrue(recheck_suite(copied)["passed"])
            (copied / "b7/brain-after/src/microduck_brain/depth.py").write_text("# changed\n")
            with self.assertRaisesRegex(ValueError, "integrity mismatch"):
                recheck_suite(copied)
            suite = json.loads((copied / "suite.json").read_text())
            suite["case_order"] = list(reversed(CASE_ORDER))
            (copied / "suite.json").write_bytes(json_bytes(suite))
            with self.assertRaisesRegex(ValueError, "authoritative table order"):
                load_cases(copied)

    def test_unprocessed_case_is_retained_with_reason_in_summary(self):
        cases = copy.deepcopy(self.cases)
        cases[0].update(status="unprocessed", reason="missing before-twin recording")
        results = {bug: d for bug, d in self.results.items() if bug != "b3"}
        summary = summary_markdown(cases, results)
        self.assertIn("unprocessed: missing before-twin recording", summary)
        self.assertIn("unprocessed: **1**", summary)

    def test_public_payload_hashes_hygiene_and_report_consistency(self):
        pattern = re.compile(rb"/home/|/mnt/[a-z]/users/|[a-z]:[\\/]users[\\/]|sorin|"
                             rb"sk-[a-z0-9]{16,}|gh[pousr]_[a-z0-9]{20,}|"
                             rb"BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY", re.I)
        for path in self.root.rglob("*"):
            if path.is_file():
                raw = gzip.decompress(path.read_bytes()) if path.suffix == ".gz" else path.read_bytes()
                self.assertIsNone(pattern.search(raw), path.relative_to(self.root))
        for metadata in self.cases:
            case = self.root / metadata["bug"]
            raw = gzip.decompress((case / "run.jsonl.gz").read_bytes())
            header, _, payload = raw.partition(b"\n")
            self.assertEqual(json.loads(header)["config"], "brain.toml")
            self.assertEqual(hashlib.sha256(payload).hexdigest(), metadata["recording_provenance"]["tick_payload_sha256"])
            self.assertEqual(report_markdown(metadata, self.results[metadata["bug"]]), (case / "report.md").read_text())
            verify_inventory(case)
        self.assertEqual(summary_markdown(self.cases, self.results), (self.root / "summary.md").read_text())


if __name__ == "__main__":
    unittest.main()
