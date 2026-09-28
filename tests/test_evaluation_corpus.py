"""Deterministic validation of the synthetic evaluation corpus."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from scripts import benchmark_evaluation

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "tests" / "corpus" / "v1"


class EvaluationCorpusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.profile, cls.cases = benchmark_evaluation.load_corpus(CORPUS)

    def test_distribution_and_unique_ids(self):
        self.assertEqual(len(self.cases), 30)
        self.assertEqual(len({case["id"] for case in self.cases}), 30)
        for expected in benchmark_evaluation.CLASSES:
            self.assertEqual(sum(case["expected_class"] == expected for case in self.cases), 10)

    def test_expected_evidence_is_verbatim(self):
        for case in self.cases:
            text = case["offer"]["job_text"]
            expected = case["expected"]
            for excerpt in expected.get("evidence_contains", []) + expected["facts"].get("evidence", []):
                self.assertIn(excerpt, text, f"{case['id']}: preuve absente du texte")

    def test_review_matches_corrected_corpus(self):
        review = (ROOT / "tests" / "corpus" / "REVIEW-v1.md").read_text(encoding="utf-8")
        self.assertEqual(review.count("Validation : [x]"), len(self.cases))
        for case in self.cases:
            self.assertIn(f"### {case['id']} —", review)
            for excerpt in case["expected"]["evidence_contains"]:
                self.assertIn(f"« {excerpt} »", review, case["id"])
        by_id = {case["id"]: case for case in self.cases}
        self.assertIsNone(by_id["SYNTH-014-I"]["expected"]["facts"]["experience_min"])
        self.assertNotIn("experience", by_id["SYNTH-016-I"]["expected"]["gates"])
        for identifier in ("SYNTH-020-I", "SYNTH-023-A"):
            self.assertIsNone(by_id[identifier]["expected"]["facts"]["contract"])

    def test_profile_is_synthetic_and_valid_for_benchmark(self):
        self.assertEqual(self.profile["candidate"]["name"], "Candidat synthétique")
        self.assertGreaterEqual(len(self.profile["criteria"]), 4)
        self.assertEqual(self.profile["search"]["experience_filter"]["reject_if_minimum_required_years_gte"], 2)

    def test_offline_benchmark_is_repeatable_without_fake_jev_result(self):
        first = [benchmark_evaluation.offline_record(case, self.profile) for case in self.cases]
        second = [benchmark_evaluation.offline_record(case, self.profile) for case in self.cases]
        self.assertEqual(first, second)
        self.assertTrue(all("jev" not in record and "decision" not in record for record in first))
        rows = [{"id": case["id"], "gate_results": record["gate_results"]}
                for case, record in zip(self.cases, first)]
        metrics = benchmark_evaluation.gate_metrics(
            rows, {case["id"]: case for case in self.cases})
        self.assertGreater(metrics["checked"], 0)
        self.assertLessEqual(metrics["correct"], metrics["checked"])

    def test_qualifying_score_with_optional_low_confidence_is_not_ambiguous(self):
        record = {"status": "ok", "decision": {"status": "qualified", "unknowns": [], "warnings": []},
                  "jev": {"low_confidence_criteria": ["location_fit"]}, "gate_results": []}
        self.assertEqual(benchmark_evaluation.classify(record), "compatible")

    def test_blocking_gate_cannot_be_labeled_ambiguous(self):
        cases = json.loads(json.dumps(self.cases))
        case = next(case for case in cases if case["id"] == "SYNTH-028-I")
        case["expected_class"] = "ambiguous"
        with self.assertRaisesRegex(ValueError, "porte bloquante"):
            benchmark_evaluation.validate_corpus(self.profile, cases)

    def test_rejects_evidence_not_present_in_offer(self):
        cases = json.loads(json.dumps(self.cases))
        cases[0]["expected"]["facts"]["evidence"].append("citation absente de cette annonce")
        with self.assertRaisesRegex(ValueError, "preuve absente"):
            benchmark_evaluation.validate_corpus(self.profile, cases)

    def test_case_files_are_valid_json_objects(self):
        for path in sorted((CORPUS / "cases").glob("*.json")):
            self.assertIsInstance(json.loads(path.read_text(encoding="utf-8")), dict)


if __name__ == "__main__":
    unittest.main(verbosity=2)
