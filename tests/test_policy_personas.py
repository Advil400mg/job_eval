"""Cross-persona, offline acceptance checks; no real CV or offer is used."""

from __future__ import annotations

import unittest
from datetime import date

from app import evaluation, gates, languages, locations, onboarding, policy, profile
from app.job_facts import extract_facts


def person(name: str, role: str, *, years: float | None, places: str,
           languages_line: str, seniority: str, contracts: list[str]) -> dict:
    master = {"identity": {"name": name, "headline_default": role,
                           "languages_line": languages_line},
              "skill_groups": [{"text": "Python, statistics"}]}
    return onboarding.build_personal_profile(
        master, role, places, seniority=seniority, candidate_years=years,
        contract_types=contracts, confirmed=True)


class MultiPersonaPolicyTests(unittest.TestCase):
    def test_senior_quant_in_germany_has_no_hidden_junior_limit(self):
        user = person("Example Candidate", "Senior Quant", years=10,
                      places="Allemagne", languages_line="Deutsch C1, English B2",
                      seniority="senior", contracts=["permanent"])
        self.assertEqual(profile.validate_profile(user), [])
        offer = {"title": "Senior Quant", "location": "Berlin, DE",
                 "location_provenance": "json-ld", "published_at": date.today().isoformat(),
                 "job_text": "Senior Quant in Berlin. Permanent position. 8 to 12 years of experience required. "
                             "Deutsch C1 erforderlich. We develop quantitative models in Python."}
        facts = extract_facts(offer)
        checks = {g["gate"]: g for g in gates.run_gates(offer, user, facts)}
        self.assertEqual(checks["experience"]["status"], "pass")
        self.assertEqual(checks["location"]["status"], "pass")
        self.assertEqual(checks["contract_type"]["status"], "pass")
        self.assertNotIn("cybersecurity", " ".join(c["description"] for c in
                                          policy.effective_criteria(user)).lower())
        self.assertEqual(languages.candidate_levels("Deutsch C1").get("de"), 5)

    def test_junior_profile_explicit_minimum_is_blocking(self):
        user = person("Example Candidate", "Junior Security Analyst", years=0.5,
                      places="France", languages_line="Français C2", seniority="junior",
                      contracts=["permanent"])
        offer = {"title": "Junior Security Analyst", "location": "Toulouse, Occitanie, FR",
                 "location_provenance": "json-ld", "published_at": date.today().isoformat(),
                 "job_text": "Junior Security Analyst CDI Toulouse. 2 ans d'expérience minimum exigés. "
                             "Vous analyserez les incidents de sécurité et les journaux techniques."}
        facts = extract_facts(offer)
        checks = {g["gate"]: g for g in gates.run_gates(offer, user, facts)}
        self.assertEqual(checks["experience"]["status"], "fail")
        self.assertEqual(checks["location"]["status"], "pass")

    def test_unknown_country_never_becomes_a_proven_mismatch(self):
        offer = {"location": "Toulouse", "job_text": "Poste à Toulouse."}
        self.assertEqual(locations.location_gate(offer, ["France"])["status"], "unknown")
        self.assertEqual(locations.country_code("Deutschland"), "DE")
        self.assertEqual(locations.country_code("Allemagne"), "DE")
        self.assertEqual(locations.country_code("France"), "FR")

    def test_remote_location_cannot_hard_reject_city_preferences(self):
        offer = {"location": "Remote Europe", "location_provenance": "JSON-LD jobLocation",
                 "job_text": "Remote Europe position."}
        result = locations.location_gate(offer, ["Berlin", "Paris"])
        self.assertEqual(result["status"], "unknown")
        self.assertFalse(result["hard"])

    def test_extractor_provenance_can_prove_location(self):
        offer = {"location": "Toulouse, Occitanie, FR",
                 "location_provenance": "JSON-LD jobLocation",
                 "job_text": "Architecte quantitatif à Toulouse."}
        self.assertEqual(locations.location_gate(offer, ["France"])["status"], "pass")
        offer["location_provenance"] = "non trouvée"
        self.assertEqual(locations.location_gate(offer, ["France"])["status"], "unknown")

    def test_missing_or_lower_german_level_requests_review_not_fake_score(self):
        source = "Deutsch C1 erforderlich. Vous construirez des modèles quantitatifs en Python."
        user = person("Example Candidate", "Senior Quant", years=10, places="Berlin, DE",
                      languages_line="English C1", seniority="senior", contracts=[])
        offer = {"job_text": source}
        result = {"jev_approved": True, "global_score": 83,
                  "minimum_global_score": 68, "minimum_confidence": 0.5,
                  "criteria": [], "dimensions": []}
        facts = extract_facts(offer)
        assessment = evaluation.assess_evaluation(result, facts, [], offer, user)
        self.assertIn("unknown:candidate_language_level:de", assessment["quality_flags"])
        self.assertEqual(assessment["decision"]["status"], "review_required")
        user["candidate_facts"]["languages_line"] = "Deutsch B2, English C1"
        assessment = evaluation.assess_evaluation(result, facts, [], offer, user)
        self.assertIn("mismatch:candidate_language_level:de", assessment["quality_flags"])
        self.assertEqual(assessment["decision"]["status"], "review_required")
        user["candidate_facts"]["languages_line"] = "Deutsch C1, English C1"
        assessment = evaluation.assess_evaluation(result, facts, [], offer, user)
        self.assertNotIn("unknown:candidate_language_level:de", assessment["quality_flags"])

    def test_contract_not_assumed_in_structured_policy(self):
        user = person("Example Candidate", "Architect", years=None, places="",
                      languages_line="", seniority="any", contracts=[])
        self.assertEqual(gates.contract_gate_for_profile("Stage de six mois", {
            "contract": {"value": "internship", "status": "known", "evidence": "Stage de six mois"}},
            user["search"]["contract_types"])["status"], "pass")

    def test_legacy_profile_retains_original_gate_count(self):
        legacy = {"search": {"max_age_days": 30, "experience_filter": {
            "reject_if_minimum_required_years_gte": 2}}}
        offer = {"job_text": "CDI junior, 1 an d'expérience en cyber.",
                 "published_at": date.today().isoformat()}
        self.assertEqual(len(gates.run_gates(offer, legacy)), 4)
        self.assertIsNone(policy.context(legacy))


if __name__ == "__main__":
    unittest.main()
