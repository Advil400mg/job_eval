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

    # ── Navigation cleanup regressions ─────────────────────────────────────

    def test_skip_to_content_does_not_create_false_senior_hit(self):
        """'principal' in 'Aller au contenu principal' must not match _SENIOR."""
        text = ("Aller au contenu principal\n\n"
                "CDI Développeur junior Python H/F\n\n"
                "Nous recherchons un développeur junior.")
        facts = extract_facts({"job_text": text})
        self.assertEqual(facts["junior"]["value"], True)

    def test_related_offer_senior_not_confused_with_advertised_role(self):
        """Senior job cards in 'offres recommandées' must not make offer senior."""
        from app.extract import _clean_job_text
        text = _clean_job_text(
            "CDI Développeur junior Python H/F\n\n"
            "Offres similaires\n"
            "Senior Architecte CDI - Paris - 70000€"
        )
        facts = extract_facts({"job_text": text})
        self.assertEqual(facts["junior"]["value"], True)

    def test_breadcrumb_nav_does_not_create_senior_hit(self):
        """Breadcrumb-style nav menus must not be scanned for seniority."""
        text = ("Accueil > Emploi > Détail\n"
                "CDI Analyste junior, zéro à deux ans d'expérience.")
        facts = extract_facts({"job_text": text})
        self.assertEqual(facts["junior"]["value"], True)

    def test_english_skip_to_content_safe(self):
        text = ("Skip to main content\n"
                "Junior Developer CDI - 0 to 2 years experience.")
        facts = extract_facts({"job_text": text})
        self.assertEqual(facts["junior"]["value"], True)

    # ── Contract-type extraction regressions ───────────────────────────────

    def test_cdd_extracted_as_fixed_term(self):
        text = "CDD Développeur Python, 12 mois renouvelable."
        facts = extract_facts({"job_text": text})
        self.assertEqual(facts["contract"]["value"], "fixed_term")
        self.assertEqual(facts["contract"]["status"], "known")
        self.assertIn(facts["contract"]["evidence"], text)

    def test_fixed_term_english_extracted(self):
        text = "Fixed-term contract for a junior DevOps engineer, 6 months."
        facts = extract_facts({"job_text": text})
        self.assertEqual(facts["contract"]["value"], "fixed_term")
        self.assertEqual(facts["contract"]["status"], "known")

    def test_befristet_extracted(self):
        text = "Befristete Stelle als Junior Entwickler, CDD, 24 Monate."
        facts = extract_facts({"job_text": text})
        self.assertEqual(facts["contract"]["value"], "fixed_term")

    def test_freelance_extracted(self):
        text = ("Mission freelance pour consultant junior en cybersécurité. "
                "Durée 6 mois renouvelables.")
        facts = extract_facts({"job_text": text})
        self.assertEqual(facts["contract"]["value"], "freelance")
        self.assertEqual(facts["contract"]["status"], "known")

    def test_freelance_independant_extracted(self):
        text = "Mission indépendante en cybersécurité, portage salarial."
        facts = extract_facts({"job_text": text})
        self.assertEqual(facts["contract"]["value"], "freelance")

    def test_cdd_and_cdi_contradictory(self):
        text = "CDI ou CDD au choix du candidat, poste junior."
        facts = extract_facts({"job_text": text})
        self.assertEqual(facts["contract"]["status"], "contradictory")

    def test_internship_and_freelance_contradictory(self):
        text = "Stage de fin d'études ou mission freelance au choix."
        facts = extract_facts({"job_text": text})
        self.assertEqual(facts["contract"]["status"], "contradictory")

    def test_permanent_internship_contradictory_preserved(self):
        text = "CDI avec stage obligatoire de 6 mois en début de contrat."
        facts = extract_facts({"job_text": text})
        self.assertEqual(facts["contract"]["status"], "contradictory")

    def test_past_internship_not_mistaken_for_contract(self):
        """A past internship mentioned as experience is not the contract type."""
        text = ("CDI en support technique. Un stage préalable en entreprise "
                "est un plus mais pas obligatoire.")
        facts = extract_facts({"job_text": text})
        self.assertEqual(facts["contract"]["value"], "permanent")
        self.assertEqual(facts["contract"]["status"], "known")

    def test_past_freelance_experience_does_not_conflict_with_cdi(self):
        text = "Contrat CDI. Une expérience en freelance est un plus."
        self.assertEqual(extract_facts({"job_text": text})["contract"]["value"], "permanent")

    def test_independent_personality_is_not_freelance_contract(self):
        text = "Poste CDI. Nous cherchons un consultant indépendant d’esprit."
        self.assertEqual(extract_facts({"job_text": text})["contract"]["value"], "permanent")

    def test_temporary_freelance_mission_does_not_imply_cdd(self):
        text = "Freelance, mission temporaire de 6 mois."
        self.assertEqual(extract_facts({"job_text": text})["contract"]["value"], "freelance")

    def test_no_contract_type_returns_unknown(self):
        text = ("Poste de niveau junior. Compétences Python et Linux requises. "
                "Aucune information sur le type de contrat.")
        facts = extract_facts({"job_text": text})
        self.assertEqual(facts["contract"]["status"], "unknown")
        self.assertIsNone(facts["contract"]["value"])

    def test_apprenticeship_as_internship(self):
        text = "Apprenticeship position for cybersecurity analyst."
        facts = extract_facts({"job_text": text})
        self.assertEqual(facts["contract"]["value"], "internship")
        self.assertEqual(facts["contract"]["status"], "known")

    def test_apprenticeship_curly_apostrophe(self):
        facts = extract_facts({"job_text": "Contrat d’alternance pour développeur."})
        self.assertEqual(facts["contract"]["value"], "internship")

    def test_praktikum_as_internship(self):
        text = "Praktikum im Bereich Cybersicherheit, 6 Monate."
        facts = extract_facts({"job_text": text})
        self.assertEqual(facts["contract"]["value"], "internship")

    def test_cdd_negated_not_extracted(self):
        text = "Ce n'est pas un CDD mais un CDI junior."
        facts = extract_facts({"job_text": text})
        self.assertEqual(facts["contract"]["value"], "permanent")
        self.assertEqual(facts["contract"]["status"], "known")

    def test_freelance_negated_not_extracted(self):
        text = "Poste en CDI, pas de mission freelance."
        facts = extract_facts({"job_text": text})
        self.assertEqual(facts["contract"]["value"], "permanent")


if __name__ == "__main__":
    unittest.main()