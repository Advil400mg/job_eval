"""Extraction regression tests: navigation cleanup, location provenance.

Run:  python3 -m unittest tests/test_extract.py -v
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.extract import _clean_job_text, _parse_location, extract, visible_text  # noqa: E402


class NavigationCleanup(unittest.TestCase):
    """Navigation and related-offer noise must not enter job_text."""

    def test_strips_skip_to_content(self):
        original = (
            "Aller au contenu principal\n\n"
            "CDI Développeur junior Python H/F\n\n"
            "Nous recherchons un développeur junior."
        )
        cleaned = _clean_job_text(original)
        self.assertNotIn("Aller au contenu", cleaned)
        self.assertIn("CDI Développeur junior", cleaned)
        self.assertIn("développeur junior", cleaned)

    def test_skip_to_content_does_not_drop_advertised_role(self):
        """The word 'principal' in 'Aller au contenu principal' is NAV, not senior."""
        text = (
            "Aller au contenu principal\n\n"
            "CDI Développeur junior Python H/F\n\n"
            "Nous recherchons un développeur junior. "
            "Minimum un an d'expérience."
        )
        cleaned = _clean_job_text(text)
        self.assertIn("développeur junior", cleaned)
        self.assertIn("Minimum un an d'expérience", cleaned)

    def test_related_offers_removed(self):
        text = (
            "CDI Junior SOC Analyst H/F\n\n"
            "Surveiller les alertes de sécurité.\n\n"
            "Des offres d'emplois recommandées\n"
            "- Senior Développeur Full Stack CDI - Paris - 55000€\n"
            "- Architecte Cloud Confirmé CDI - Lyon - 70000€\n"
        )
        cleaned = _clean_job_text(text)
        self.assertIn("Junior SOC Analyst", cleaned)
        self.assertNotIn("Senior Développeur", cleaned)
        self.assertNotIn("Architecte Cloud Confirmé", cleaned)

    def test_related_offers_heading_stripped(self):
        text = (
            "CDI Junior Développeur.\n\n"
            "Offres similaires\n"
            "Senior Tech Lead CDI - Paris - 65000€\n"
        )
        cleaned = _clean_job_text(text)
        self.assertNotIn("Senior Tech Lead", cleaned)
        self.assertNotIn("Offres similaires", cleaned)

    def test_preserves_offer_body_after_nav_strip(self):
        """Real role content must survive cleanup intact."""
        text = (
            "Aller au contenu principal\n"
            "Menu\n"
            "Accueil > Offres > Détail\n\n"
            "CDI Consultant junior cybersécurité H/F\n\n"
            "Vous interviendrez sur des missions de sécurité offensive.\n"
            "Formation et mentorat assurés par un consultant senior.\n"
        )
        cleaned = _clean_job_text(text)
        self.assertIn("Consultant junior cybersécurité", cleaned)
        self.assertIn("missions de sécurité offensive", cleaned)
        self.assertIn("mentorat assurés par un consultant senior", cleaned)

    def test_french_breadcrumb_stripped(self):
        text = "Accueil > Emploi\nCDI Développeur"
        cleaned = _clean_job_text(text)
        self.assertIn("CDI Développeur", cleaned)
        self.assertNotIn("Accueil > Emploi", cleaned)

    def test_skip_to_menu_stripped(self):
        text = "Aller au menu\n\nPoste junior CDI"
        cleaned = _clean_job_text(text)
        self.assertNotIn("Aller au menu", cleaned)
        self.assertIn("Poste junior CDI", cleaned)

    def test_english_skip_to_content_stripped(self):
        text = "Skip to main content\n\nJunior Developer CDI"
        cleaned = _clean_job_text(text)
        self.assertNotIn("Skip to main", cleaned)
        self.assertIn("Junior Developer CDI", cleaned)


class LocationProvenance(unittest.TestCase):
    """Location parsing and provenance tracking."""

    def test_paris_france(self):
        parsed = _parse_location("Paris, France")
        self.assertEqual(parsed["location_city"], "Paris")
        self.assertEqual(parsed["location_country"], "France")
        self.assertEqual(parsed["location_provenance"], "extraite")

    def test_lyon(self):
        parsed = _parse_location("Lyon")
        self.assertEqual(parsed["location_city"], "Lyon")
        self.assertIsNone(parsed["location_country"])
        self.assertEqual(parsed["location_provenance"], "extraite")

    def test_brussels_belgium(self):
        parsed = _parse_location("Bruxelles, Belgique")
        self.assertEqual(parsed["location_city"], "Bruxelles")
        self.assertEqual(parsed["location_country"], "Belgique")

    def test_unknown_location(self):
        parsed = _parse_location("Non renseignée")
        self.assertIsNone(parsed["location_city"])
        self.assertIsNone(parsed["location_country"])
        self.assertEqual(parsed["location_provenance"], "non renseignée")

    def test_empty_location(self):
        parsed = _parse_location("")
        self.assertIsNone(parsed["location_city"])
        self.assertEqual(parsed["location_provenance"], "non renseignée")

    def test_multi_word_city(self):
        parsed = _parse_location("Saint-Germain-en-Laye")
        self.assertIn("Saint-Germain", parsed["location_city"] or "")

    def test_postal_code_with_city(self):
        parsed = _parse_location("Paris 75001")
        self.assertIn("Paris", parsed["location_city"] or "")


class ExtractIntegration(unittest.TestCase):
    """End-to-end extraction with synthetic HTML."""

    def test_nav_not_in_extracted_text(self):
        """'Aller au contenu principal' must be absent from extraction result."""
        html = (
            "<html><body>"
            "<a href='#main'>Aller au contenu principal</a>"
            "<h1>CDI Junior Analyste</h1>"
            "<p>Poste junior en CDI à Paris pour profil débutant.</p>"
            "</body></html>"
        )
        result = extract("https://example.com/job/1", html)
        self.assertNotIn("Aller au contenu", result["job_text"])
        self.assertIn("Junior Analyste", result["job_text"])

    def test_related_offers_absent(self):
        """Senior jobs in 'offres recommandées' not in extracted text."""
        html = (
            "<html><body>"
            "<h1>CDI Junior Dev</h1>"
            "<p>Poste junior en CDI.</p>"
            "<h2>Des offres d'emplois recommandées</h2>"
            "<ul><li>Senior Architecte CDI Paris 70000€</li></ul>"
            "</body></html>"
        )
        result = extract("https://example.com/job/2", html)
        self.assertNotIn("Senior Architecte", result["job_text"])

    def test_location_provenance_jsonld(self):
        """Location from JSON-LD JobPosting carries provenance."""
        html = (
            '<html><head>'
            '<script type="application/ld+json">'
            '{"@type":"JobPosting","title":"Junior Dev","jobLocation":'
            '{"@type":"Place","address":{"addressLocality":"Lyon","addressCountry":"FR"}}}'
            '</script>'
            '</head><body><h1>Junior Dev</h1><p>CDI junior à Lyon.</p></body></html>'
        )
        result = extract("https://example.com/job/3", html)
        self.assertEqual(result["location"], "Lyon, FR")
        self.assertIn("JSON-LD", result.get("location_provenance", ""))
        self.assertEqual(result.get("location_city"), "Lyon")

    def test_location_provenance_text(self):
        """Location from 'Localisation:' regex carries provenance."""
        html = (
            "<html><body>"
            "<h1>CDI Dev</h1>"
            "<p>Localisation : Toulouse, France</p>"
            "<p>Poste en CDI.</p>"
            "</body></html>"
        )
        result = extract("https://example.com/job/4", html)
        self.assertEqual(result["location"], "Toulouse, France")
        self.assertIn("Localisation", result.get("location_provenance", ""))

    def test_recommendation_date_and_location_are_not_offer_metadata(self):
        html = (
            "<html><body><h1>Junior Analyst</h1>"
            "<p>Poste en CDI pour débutant.</p>"
            "<h2>Des offres d'emplois recommandées</h2>"
            "<p>Localisation : Berlin, Deutschland</p>"
            "<p>En ligne depuis le 12 septembre 2026</p>"
            "</body></html>"
        )
        offer = extract("https://example.test/role", html)
        self.assertIsNone(offer["published_at"])
        self.assertEqual(offer["location"], "Non renseignée")
        self.assertNotIn("Berlin", offer["job_text"])

    def test_real_contract_and_salary_survive_cleanup(self):
        text = "Senior Quant CDI Berlin 90000€\nMissions de modélisation.\n"
        self.assertIn("Senior Quant CDI Berlin 90000€", _clean_job_text(text))

    def test_jsonld_country_as_object(self):
        html = (
            '<script type="application/ld+json">'
            '{"@type":"JobPosting","title":"Analyst",'
            '"jobLocation":{"address":{"addressLocality":"Berlin",'
            '"addressCountry":{"name":"Germany"}}}}'
            '</script><h1>Analyst</h1><p>Permanent role.</p>'
        )
        offer = extract("https://example.test/analyst", html)
        self.assertEqual(offer["location_country"], "Germany")
        self.assertEqual(offer["location_provenance"], "JSON-LD jobLocation")

    def test_visible_text_basic(self):
        html = "<html><body><h1>Titre</h1><p>Contenu.</p></body></html>"
        text = visible_text(html)
        self.assertIn("Titre", text)
        self.assertIn("Contenu", text)


if __name__ == "__main__":
    unittest.main()