"""Offline unit tests for the gates and the extraction helpers (stdlib only).

Run:  python3 tests/test_gates.py
"""

from __future__ import annotations

import os
import sys
import unittest
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import gates  # noqa: E402
from app.extract import parse_french_date  # noqa: E402

PROFILE = {
    "search": {
        "max_age_days": 30,
        "experience_filter": {"reject_if_minimum_required_years_gte": 2},
    }
}


class DateParsing(unittest.TestCase):
    def test_formats(self):
        self.assertEqual(parse_french_date("28/08/2026"), "2026-08-28")
        self.assertEqual(parse_french_date("28.08.2026"), "2026-08-28")
        self.assertEqual(parse_french_date("2026-08-28"), "2026-08-28")
        self.assertEqual(parse_french_date("22 septembre 2026"), "2026-09-22")
        self.assertEqual(parse_french_date("3 août 2026"), "2026-08-03")
        self.assertIsNone(parse_french_date("Non renseigné"))
        self.assertIsNone(parse_french_date("il y a peu"))

    def test_snippet_not_a_date(self):
        # a cached snippet must not be mistaken for a proven publication date
        self.assertIsNone(parse_french_date("Offre publiée récemment"))


class ContractGate(unittest.TestCase):
    def test_internship_is_hard_fail(self):
        res = gates.contract_gate("Stage de 6 mois au sein du SOC. Convention étudiant requise.")
        self.assertEqual(res["status"], "fail")
        self.assertTrue(res["hard"])

    def test_permanent_contract_passes(self):
        res = gates.contract_gate("Nature de l'emploi : CDI — temps plein. Employeur : ACME.")
        self.assertEqual(res["status"], "pass")

    def test_unknown_contract_is_not_a_pass(self):
        res = gates.contract_gate("Nous recherchons un ingénieur réseau motivé.")
        self.assertEqual(res["status"], "unknown")


class ExperienceGate(unittest.TestCase):
    def test_two_years_minimum_is_hard_fail(self):
        res = gates.experience_gate("Minimum 2 ans d'expérience en cybersécurité.")
        self.assertEqual(res["status"], "fail")

    def test_range_without_junior_mention_fails(self):
        res = gates.experience_gate("Vous justifiez de 1 à 3 ans d'expérience en réseau.")
        self.assertEqual(res["status"], "fail")

    def test_junior_mention_near_range_passes_or_warns(self):
        res = gates.experience_gate(
            "Poste ouvert aux débutants (0 à 2 ans d'expérience) en sécurité réseau.")
        self.assertEqual(res["status"], "pass")

    def test_unstated_experience_line_passes(self):
        res = gates.experience_gate("Expérience souhaitée : Non renseigné")
        self.assertEqual(res["status"], "pass")

    def test_silence_is_unknown_not_pass(self):
        res = gates.experience_gate("Missions : administrer les serveurs Linux.")
        self.assertEqual(res["status"], "unknown")


class FreshnessGate(unittest.TestCase):
    def test_recent_passes(self):
        iso = (date.today() - timedelta(days=5)).isoformat()
        self.assertEqual(gates.freshness_gate(iso, 30)["status"], "pass")

    def test_old_fails(self):
        iso = (date.today() - timedelta(days=90)).isoformat()
        self.assertEqual(gates.freshness_gate(iso, 30)["status"], "fail")

    def test_missing_date_fails(self):
        self.assertEqual(gates.freshness_gate(None, 30)["status"], "fail")


class AvailabilityGate(unittest.TestCase):
    def test_withdrawn_offer_fails(self):
        res = gates.availability_gate("L'offre que vous souhaitez afficher n'est plus disponible.")
        self.assertEqual(res["status"], "fail")

    def test_future_deadline_passes(self):
        future = (date.today() + timedelta(days=30)).strftime("%d/%m/%Y")
        res = gates.availability_gate(f"Date limite de candidature : {future}")
        self.assertEqual(res["status"], "pass")

    def test_past_deadline_fails(self):
        past = (date.today() - timedelta(days=1)).strftime("%d/%m/%Y")
        res = gates.availability_gate(f"Date limite de candidature : {past}")
        self.assertEqual(res["status"], "fail")


class Decision(unittest.TestCase):
    def setUp(self):
        self.pass_gates = [
            {"gate": "contract_type", "status": "pass", "hard": True, "reason": ""},
            {"gate": "freshness", "status": "pass", "hard": True, "reason": ""},
        ]

    def test_qualified_requires_jev_and_gates(self):
        res = gates.decide({"jev_approved": True}, self.pass_gates)
        self.assertEqual(res["status"], "qualified")

    def test_jev_refusal_is_rejected(self):
        res = gates.decide({"jev_approved": False}, self.pass_gates)
        self.assertEqual(res["status"], "rejected")

    def test_gate_failure_on_approved_offer_is_jev_excluded(self):
        bad = [{"gate": "freshness", "status": "fail", "hard": True, "reason": "vieille"}]
        res = gates.decide({"jev_approved": True}, bad)
        self.assertEqual(res["status"], "jev_excluded")
        self.assertEqual(res["hard_gate_failures"][0]["gate"], "freshness")

    def test_soft_failure_does_not_exclude(self):
        soft = [{"gate": "contract_type", "status": "fail", "hard": False, "reason": "x"}]
        res = gates.decide({"jev_approved": True}, soft)
        self.assertEqual(res["status"], "qualified")


if __name__ == "__main__":
    unittest.main(verbosity=2)