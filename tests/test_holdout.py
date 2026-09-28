"""Agent-annotated synthetic holdout for deterministic evaluation gates."""
from __future__ import annotations

import unittest
from collections import Counter
from pathlib import Path

from app.job_facts import extract_facts
from scripts import benchmark_evaluation as bench

ROOT = Path(__file__).resolve().parents[1]
HOLDOUT = ROOT / "tests" / "holdout" / "v1"


class HoldoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.profile, cls.cases = bench.load_corpus(HOLDOUT)

    def test_balance_evidence_and_unambiguous_annotations(self):
        self.assertEqual(len(self.cases), 12)
        self.assertEqual(len({case["id"] for case in self.cases}), 12)
        self.assertEqual(Counter(case["expected_class"] for case in self.cases),
                         Counter({name: 4 for name in bench.CLASSES}))
        for case in self.cases:
            with self.subTest(case=case["id"]):
                text = case["offer"]["job_text"]
                expected = case["expected"]
                self.assertTrue(expected["facts"]["evidence"])
                self.assertTrue(expected["evidence_contains"])
                for quote in (expected["facts"]["evidence"] +
                              expected["evidence_contains"]):
                    self.assertIn(quote, text)
                self.assertEqual(set(expected["gates"]), {"contract_type", "experience"})
                self.assertFalse(case["expected_class"] != "incompatible" and
                                 "fail" in expected["gates"].values())

    def test_facts_and_gates_match_offer_without_jev_or_answer_key_injection(self):
        rows = []
        for case in self.cases:
            with self.subTest(case=case["id"]):
                actual = extract_facts(case["offer"])
                for key in ("contract", "experience_min", "junior"):
                    self.assertEqual(actual[key]["value"], case["expected"]["facts"][key],
                                     f"{case['id']}: {key}")
                    if actual[key]["evidence"]:
                        self.assertIn(actual[key]["evidence"], case["offer"]["job_text"])
                if "experience_max" in case["expected"]["facts"]:
                    self.assertEqual(actual["experience_max"]["value"],
                                     case["expected"]["facts"]["experience_max"])
                record = bench.offline_record(case, self.profile)
                self.assertNotIn("jev", record)
                self.assertNotIn("decision", record)
                statuses = {item["gate"]: item["status"] for item in record["gate_results"]}
                for name, expected_status in case["expected"]["gates"].items():
                    self.assertEqual(statuses[name], expected_status)
                rows.append({"id": case["id"], "gate_results": record["gate_results"]})
        metrics = bench.gate_metrics(rows, {case["id"]: case for case in self.cases})
        self.assertEqual(metrics["checked"], 24)
        self.assertEqual(metrics["correct"], 24)


if __name__ == "__main__":
    unittest.main()
