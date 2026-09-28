"""Source-backed review and non-regression of the configured Jev score."""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from app import evaluation, gates
from app.job_facts import extract_facts

ROOT = Path(__file__).resolve().parents[1] / "tests" / "corpus" / "v1"
PROFILE = json.loads((ROOT / "profile.json").read_text(encoding="utf-8"))


class EvaluationAssessmentTests(unittest.TestCase):
    def assess(self, suffix, result):
        case = json.loads((ROOT / "cases" / f"synth-{suffix}.json").read_text(encoding="utf-8"))
        offer = {**case["offer"], "published_at": "2090-01-01"}
        facts = extract_facts(offer)
        # Freshness is out of scope here: explicitly verified by its own gate tests.
        gate_results = [gates.contract_gate(offer["job_text"], facts),
                        gates.experience_gate(offer["job_text"], facts=facts)]
        return evaluation.assess_evaluation(result, facts, gate_results, offer, PROFILE), offer

    def test_uncertain_work_conditions_need_review_not_automatic_qualification(self):
        result = {"jev_approved": True, "global_score": 69, "minimum_global_score": 68,
                  "criteria": [], "dimensions": [{"id": "clarity", "score": 60, "confidence": 0.7}]}
        assessment, offer = self.assess("027-a", result)
        self.assertEqual(assessment["decision"]["status"], "review_required")
        self.assertIn("unknown:work_conditions", assessment["quality_flags"])
        self.assertEqual(result["global_score"], 69)
        for item in assessment["missing_information"]:
            if item["evidence"]:
                self.assertIn(item["evidence"], offer["job_text"])

    def test_language_requirement_without_candidate_level_needs_review(self):
        assessment, _ = self.assess("030-a", {"jev_approved": True, "global_score": 86,
                                          "minimum_global_score": 68, "criteria": []})
        self.assertTrue(assessment["review_required"])
        self.assertIn("unknown:candidate_english_level", assessment["quality_flags"])

    def test_cv_english_level_is_known_in_new_and_legacy_profiles(self):
        result = {"jev_approved": True, "global_score": 85, "criteria": []}
        offer = {"job_text": "English is mandatory for customer meetings."}
        profiles = (
            {"candidate": {"languages_line": "Français C2, anglais B2"}},
            {"candidate": {"languages": {"en": "B2"}}},
            {"criteria": [{"id": "language_fit", "description":
                           "Les langues exigées sont compatibles avec le CV : Français, anglais (C1)."}]},
        )
        for profile in profiles:
            with self.subTest(profile=profile):
                assessment = evaluation.assess_evaluation(result, {}, [], offer, profile)
                self.assertNotIn("unknown:candidate_english_level", assessment["quality_flags"])
                self.assertEqual(assessment["decision"]["status"], "qualified")

    def test_language_name_or_french_level_is_not_english_proficiency(self):
        result = {"jev_approved": True, "global_score": 85, "criteria": []}
        offer = {"job_text": "English is mandatory for customer meetings."}
        for line in ("French C2, English", "English, French C2", "French, English"):
            with self.subTest(line=line):
                profile = {"candidate": {"languages_line": line}}
                assessment = evaluation.assess_evaluation(result, {}, [], offer, profile)
                self.assertIn("unknown:candidate_english_level", assessment["quality_flags"])

    def test_paraphrased_english_requirement_and_optional_english(self):
        result = {"jev_approved": True, "global_score": 86,
                  "minimum_global_score": 68, "criteria": []}
        for text in (
            "L'anglais est la seule langue utilisée par l'équipe et les clients.",
            "Applicants must communicate in English with every customer.",
            "Un niveau courant en anglais est obligatoire pour les échanges.",
            "La maîtrise de l'anglais est indispensable pour parler aux clients.",
        ):
            with self.subTest(text=text):
                offer = {"job_text": text}
                assessment = evaluation.assess_evaluation(result, {}, [], offer, PROFILE)
                self.assertTrue(assessment["review_required"])
                evidence = next(item["evidence"] for item in assessment["missing_information"]
                                if item["field"] == "candidate_english_level")
                self.assertIn(evidence, text)
        optional = evaluation.assess_evaluation(
            result, {}, [], {"job_text": "English is optional for this role."}, PROFILE)
        self.assertNotIn("unknown:candidate_english_level", optional["quality_flags"])

    def test_adjacent_sentence_can_explain_unknown_on_call_conditions(self):
        variants = (
            "Des astreintes sont prévues chaque mois. Leur fréquence et leur indemnisation ne sont pas communiquées.",
            "Des déplacements et astreintes sont prévus ; leurs modalités et leur fréquence restent à définir.",
        )
        result = {"jev_approved": True, "global_score": 85,
                  "minimum_global_score": 68, "criteria": []}
        for text in variants:
            with self.subTest(text=text):
                assessment = evaluation.assess_evaluation(result, {}, [],
                                                           {"job_text": text}, PROFILE)
                self.assertIn("unknown:work_conditions", assessment["quality_flags"])
                evidence = next(item["evidence"] for item in assessment["missing_information"]
                                if item["field"] == "work_conditions")
                self.assertIn(evidence, text)

    def test_source_backed_unknown_assignment_does_not_depend_on_jev_confidence(self):
        for confidence, low_confidence in ((0.46, ["junior_fit"]), (0.5, [])):
            with self.subTest(confidence=confidence):
                result = {"jev_approved": False, "minimum_confidence": 0.5,
                          "global_score": 37, "minimum_global_score": 68,
                          "low_confidence_criteria": low_confidence,
                          "criteria": [{"id": "junior_fit", "required": True,
                                        "passed": True, "score": 62, "confidence": confidence},
                                       {"id": "technical_fit", "required": True,
                                        "passed": False, "score": 38, "confidence": 0.58}]}
                assessment, _ = self.assess("024-a", result)
                self.assertEqual(assessment["decision"]["status"], "review_required")
                self.assertIn("unknown:first_assignment", assessment["quality_flags"])

    def test_unknown_assignment_survives_rewording_of_the_same_fact(self):
        result = {"jev_approved": False, "global_score": 37,
                  "minimum_global_score": 68, "minimum_confidence": 0.5,
                  "criteria": [{"id": "technical_fit", "required": True,
                                "passed": False, "score": 38, "confidence": 0.58}]}
        variants = (
            "Le premier client, les outils et la durée de mission ne sont pas connus.",
            "L'équipe ne sait pas encore à quel client ni avec quels outils le consultant interviendra.",
        )
        for text in variants:
            with self.subTest(text=text):
                assessment = evaluation.assess_evaluation(
                    result, {}, [], {"job_text": text}, PROFILE)
                self.assertEqual(assessment["decision"]["status"], "review_required")
                self.assertIn("unknown:first_assignment", assessment["quality_flags"])
                self.assertIn(assessment["missing_information"][0]["evidence"], text)

    def test_clear_technical_rejection_not_overridden_by_missing_experience(self):
        result = {"jev_approved": False, "minimum_confidence": 0.5,
                  "criteria": [{"id": "technical_fit", "required": True, "passed": False,
                                "score": 2, "min_score": 55, "confidence": 0.94}]}
        assessment, _ = self.assess("014-i", result)
        self.assertEqual(assessment["decision"]["status"], "rejected")
        self.assertFalse(assessment["review_required"])
        self.assertIn("unknown:experience_min", assessment["quality_flags"])


if __name__ == "__main__":
    unittest.main()
