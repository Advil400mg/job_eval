"""Source-backed fact extraction regressions for junior cyber job offers."""
from __future__ import annotations

import unittest

from app.job_facts import extract_facts


class JobFactsTests(unittest.TestCase):
    def test_past_internship_does_not_change_permanent_contract(self):
        text = ("CDI en SOC à Bruxelles. Une première expérience de stage est "
                "appréciée. Poste junior ouvert aux jeunes diplômés.")
        facts = extract_facts({"job_text": text})
        self.assertEqual(facts["contract"]["value"], "permanent")
        self.assertIsNone(facts["experience_min"]["value"])
        self.assertIn(facts["contract"]["evidence"], text)

    def test_explicit_internship_fails_even_if_not_permanent_is_mentioned(self):
        text = ("Stage de fin d'études de six mois. Il ne s'agit pas d'un emploi "
                "permanent et une convention d'école est obligatoire.")
        facts = extract_facts({"job_text": text})
        self.assertEqual(facts["contract"]["value"], "internship")
        self.assertEqual(facts["contract"]["status"], "known")

    def test_preferred_years_are_not_mandatory(self):
        text = ("Permanent junior role. Three years of experience is preferred "
                "but not mandatory; recent graduates may apply.")
        facts = extract_facts({"job_text": text})
        self.assertEqual(facts["experience_preferred"]["value"], 3)
        self.assertIsNone(facts["experience_min"]["value"])

    def test_less_than_one_year_accepts_zero_experience(self):
        for text in ("Moins d'un an d'expérience accepté.",
                     "Graduate role with less than one year of professional experience."):
            with self.subTest(text=text):
                self.assertEqual(extract_facts({"job_text": text})["experience_min"]["value"], 0)

    def test_written_years_and_range_are_extracted(self):
        text = "CDI senior exige cinq à huit ans d'expérience."
        facts = extract_facts({"job_text": text})
        self.assertEqual(facts["experience_min"]["value"], 5)
        self.assertEqual(facts["experience_max"]["value"], 8)
        for fact in facts.values():
            if fact["evidence"]:
                self.assertIn(fact["evidence"], text)

    def test_programme_duration_is_not_prior_experience(self):
        text = ("Graduate programme junior en CDI. Une année passée au sein "
                "des équipes pour apprendre le métier ; expérience terrain acquise "
                "pendant cette première année.")
        facts = extract_facts({"job_text": text})
        self.assertIsNone(facts["experience_min"]["value"])
        self.assertEqual(facts["junior"]["value"], True)

    def test_programme_duration_does_not_mask_an_explicit_minimum(self):
        text = ("Junior en CDI : une année passée à apprendre le métier. "
                "Le poste exige 3 ans d'expérience professionnelle.")
        facts = extract_facts({"job_text": text})
        self.assertEqual(facts["experience_min"]["value"], 3)
        self.assertIn(facts["experience_min"]["evidence"], text)

    def test_career_progression_does_not_make_the_current_role_senior(self):
        text = "CDI junior ; progression vers un poste senior après formation."
        facts = extract_facts({"job_text": text})
        self.assertEqual(facts["junior"]["status"], "known")
        self.assertEqual(facts["junior"]["value"], True)
        actual_requirement = ("CDI junior ; progression vers un poste senior plus tard, "
                              "mais nous exigeons un architecte confirmé dès l'embauche.")
        self.assertEqual(extract_facts({"job_text": actual_requirement})["junior"]["status"],
                         "contradictory")

    def test_senior_mentor_is_not_a_senior_job_requirement(self):
        for text in (
            "Junior permanent cloud role. A senior engineer provides structured training.",
            "CDI junior, de zéro à deux ans. Une formation AppSec et un binômage avec un senior sont inclus.",
            "Permanent junior SOC role. A named senior analyst reviews investigations each week.",
            "CDI junior. Une ingénieure senior relit les changements sensibles.",
        ):
            with self.subTest(text=text):
                self.assertEqual(extract_facts({"job_text": text})["junior"]["value"], True)
        genuinely_senior = ("Malgré l'intitulé junior, le CDI exige trois à cinq ans. "
                            "Le poste est senior et dirige les revues d'architecture.")
        self.assertEqual(extract_facts({"job_text": genuinely_senior})["junior"]["status"],
                         "contradictory")

    def test_absent_level_is_not_inferred_from_negated_junior_or_senior(self):
        text = "L'annonce ne mentionne ni junior ni senior et ne précise aucune année."
        facts = extract_facts({"job_text": text})
        self.assertEqual(facts["junior"]["status"], "unknown")
        self.assertIsNone(facts["experience_min"]["value"])


if __name__ == "__main__":
    unittest.main()
