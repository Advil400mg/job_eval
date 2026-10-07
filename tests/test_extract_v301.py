"""Synthetic extraction regressions for the V3.0.1 DOM/content pipeline."""
from __future__ import annotations

import json
import unittest
from datetime import date, timedelta
from unittest import mock

from app import extract as extractor
from app import pipeline

URL = "https://jobs.example.test/roles/network-junior"
DESCRIPTION = (
    "<h2>Missions</h2><p>Vous administrez les systèmes Linux et les équipements réseau. "
    "Vous analysez les incidents, automatisez les contrôles et maintenez les services.</p>"
    "<ul><li>Surveillance des alertes et diagnostic TCP/IP.</li>"
    "<li>Documentation des changements et amélioration des procédures.</li></ul>"
)


def posting(**changes):
    obj = {
        "@type": "JobPosting", "url": URL,
        "title": "Ingénieur réseau junior H/F",
        "hiringOrganization": {"@type": "Organization", "name": "Exemple Réseaux"},
        "jobLocation": {"address": {"addressLocality": "Menton", "addressCountry": "FR"}},
        "datePosted": (date.today() - timedelta(days=2)).isoformat() + "T08:00:00Z",
        "employmentType": ["INTERN", "FULL_TIME"],
        "description": DESCRIPTION,
    }
    obj.update(changes)
    return obj


def page(obj=None, *, encoded=False, body=None):
    kind = "application/ld&#x2B;json" if encoded else "application/ld+json"
    script = "" if obj is None else (
        f'<script type="{kind}">{json.dumps(obj, ensure_ascii=False)}</script>'
    )
    content = body if body is not None else (
        '<main><h1>Ingénieur réseau junior H/F</h1>' + DESCRIPTION + '</main>'
    )
    return (
        '<html><head><meta property="og:site_name" content="Portail Exemple">'
        '<title>Portail des emplois</title>' + script + '</head><body>'
        '<nav data-action="click->menu#open">Navigation confidentielle du portail</nav>'
        + content + '<footer>Mentions et offres du portail</footer></body></html>'
    )


class StructuredOffer(unittest.TestCase):
    def test_encoded_jsonld_mime_type(self):
        offer = extractor.extract(URL, page(posting(), encoded=True))
        self.assertEqual(offer["company"], "Exemple Réseaux")
        self.assertEqual(offer["title"], "Ingénieur réseau junior H/F")
        self.assertEqual(offer["location"], "Menton, FR")
        self.assertEqual(offer["location_city"], "Menton")
        self.assertEqual(offer["location_country"], "FR")
        self.assertIn("JSON-LD", offer["published_at_provenance"])

    def test_jsonld_graph_and_type_array(self):
        obj = {"@context": "https://schema.org", "@graph": [
            {"@type": "Organization", "name": "Portail Exemple"},
            posting(**{"@type": ["Thing", "JobPosting"]}),
        ]}
        self.assertEqual(extractor.extract(URL, page(obj))["company"], "Exemple Réseaux")

    def test_jsonld_script_attributes_whitespace(self):
        raw = page(posting()).replace('type="application/ld+json"',
                                     "type = 'application/ld+json'")
        self.assertEqual(extractor.extract(URL, raw)["company"], "Exemple Réseaux")

    def test_description_not_the_surrounding_page_is_offer_content(self):
        body = ('<main><h1>Ingénieur réseau junior H/F</h1>' + DESCRIPTION +
                '</main><aside>Architecte senior : dix ans obligatoires, poste à Sydney.</aside>')
        offer = extractor.extract(URL, page(posting(), body=body))
        self.assertIn("diagnostic TCP/IP", offer["job_text"])
        self.assertNotIn("Architecte senior", offer["job_text"])
        self.assertNotIn("Sydney", offer["job_text"])
        self.assertNotIn("Navigation confidentielle", offer["job_text"])

    def test_verified_metadata_is_available_beside_the_description(self):
        offer = extractor.extract(URL, page(posting()))
        self.assertIn(offer["title"], offer["job_text"])
        self.assertIn("Exemple Réseaux", offer["job_text"])
        self.assertIn("Menton", offer["job_text"])

    def test_description_preserves_requirements_and_lists(self):
        description = (DESCRIPTION + "<p>Minimum 3 ans d'expérience obligatoire.</p>"
                       "<p>Python souhaité, non obligatoire.</p>")
        text = extractor.extract(URL, page(posting(description=description)))["job_text"]
        self.assertIn("Minimum 3 ans d'expérience obligatoire.", text)
        self.assertIn("Python souhaité, non obligatoire.", text)
        self.assertIn("Surveillance des alertes", text)

    def test_recommended_jobposting_is_not_selected_first(self):
        other = posting(url="https://jobs.example.test/roles/other",
                        title="Architecte confirmé", hiringOrganization={"name": "Autre Société"})
        offer = extractor.extract(URL, page([other, posting()]))
        self.assertEqual(offer["company"], "Exemple Réseaux")
        self.assertEqual(offer["title"], "Ingénieur réseau junior H/F")

    def test_ambiguous_job_list_is_reported_not_arbitrarily_selected(self):
        jobs = [posting(url="https://jobs.example.test/roles/a"),
                posting(url="https://jobs.example.test/roles/b", title="Autre poste")]
        with self.assertRaises(ValueError):
            extractor.extract(URL, page(jobs))

    def test_country_object_and_single_location_array(self):
        loc = [{"address": {"addressLocality": "Menton", "addressCountry": {"name": "France"}}}]
        offer = extractor.extract(URL, page(posting(jobLocation=loc)))
        self.assertEqual(offer["location"], "Menton, France")
        self.assertEqual(offer["location_country"], "France")

    def test_company_is_not_the_portal_name_when_employer_unknown(self):
        offer = extractor.extract(URL, page(posting(hiringOrganization=None)))
        self.assertEqual(offer["company"], "Non renseigné")
        self.assertNotIn("Portail Exemple", offer["company"])

    def test_wrongly_typed_fields_do_not_crash(self):
        obj = posting(title={"invalid": True}, hiringOrganization=42,
                      jobLocation="unknown", datePosted=None, description=["invalid"])
        offer = extractor.extract(URL, page(obj))
        self.assertEqual(offer["company"], "Non renseigné")
        self.assertEqual(offer["location"], "Non renseignée")
        self.assertIsNone(offer["published_at"])

    def test_future_cdi_sentence_is_not_removed_from_source(self):
        extra = "<p>Possibilité de CDI après le stage, sans engagement d'embauche.</p>"
        text = extractor.extract(URL, page(posting(description=DESCRIPTION + extra)))["job_text"]
        self.assertIn("CDI après le stage", text)
        # Contract interpretation is intentionally the separate V3.0.2 scope.


class DOMAndFallback(unittest.TestCase):
    def test_angle_bracket_inside_attribute_does_not_leak(self):
        raw = '<div data-action="click->controller#open"><p>Mission technique.</p></div>'
        text = extractor.visible_text(raw)
        self.assertEqual(text, "Mission technique.")
        self.assertNotIn("controller", text)

    def test_script_style_svg_and_comments_are_not_visible_text(self):
        raw = ('<script>invisibleScript()</script><style>.fake{color:red}</style>'
               '<svg><text>Hidden drawing</text></svg><!-- hidden comment -->'
               '<p>Mission visible.</p>')
        text = extractor.visible_text(raw)
        self.assertEqual(text, "Mission visible.")

    def test_inline_words_and_block_separators_survive(self):
        text = extractor.visible_text('<p>Configurer <strong>Linux</strong> et le réseau.</p>'
                                      '<p>Analyser les alertes.</p>')
        self.assertEqual(text, "Configurer Linux et le réseau.\nAnalyser les alertes.")

    def test_html_entities_are_decoded(self):
        text = extractor.visible_text('<p>Réseau &amp; sécurité&nbsp;: seuil &lt; 5.</p>')
        self.assertEqual(text, "Réseau & sécurité : seuil < 5.")

    def test_malformed_html_remains_readable(self):
        text = extractor.visible_text('<div><p>Administration Linux<p>Analyse réseau')
        self.assertIn("Administration Linux", text)
        self.assertIn("Analyse réseau", text)

    def test_main_content_without_jsonld(self):
        raw = page(body='<main><h1>Analyste réseau</h1>' + DESCRIPTION +
                   '<p>Employeur : Exemple Réseaux</p>'
                   '<p>Localisation : Menton, France</p></main>'
                   '<aside>Senior ailleurs en Suisse</aside>')
        offer = extractor.extract(URL, raw)
        self.assertEqual(offer["company"], "Exemple Réseaux")
        self.assertEqual(offer["location"], "Menton, France")
        self.assertNotIn("Senior ailleurs", offer["job_text"])

    def test_related_section_with_wrapped_heading_is_removed(self):
        raw = page(body='<main><h1>Analyste réseau</h1>' + DESCRIPTION +
                   '<h2>Ces offres pourraient aussi<br>vous intéresser</h2>'
                   '<p>Localisation : Amsterdam, NL</p>'
                   '<p>Senior architecte confirmé.</p></main>')
        offer = extractor.extract(URL, raw)
        self.assertEqual(offer["location"], "Non renseignée")
        self.assertNotIn("Amsterdam", offer["job_text"])
        self.assertNotIn("Senior architecte", offer["job_text"])

    def test_invalid_jsonld_can_fall_back_to_real_body(self):
        raw = page(body='<main><h1>Analyste réseau</h1>' + DESCRIPTION + '</main>')
        raw = raw.replace('</head>', '<script type="application/ld+json">{not json}</script></head>')
        offer = extractor.extract(URL, raw)
        self.assertIn("diagnostic TCP/IP", offer["job_text"])
        self.assertEqual(offer["company"], "Non renseigné")

    def test_trafilatura_is_used_when_no_description_or_main_section(self):
        body = '<div><h1>Analyste réseau</h1>' + DESCRIPTION + '</div>'
        with mock.patch.object(extractor.trafilatura, "extract", return_value="Contenu pertinent extrait.") as clean:
            offer = extractor.extract(URL, page(body=body))
        clean.assert_called_once()
        self.assertIn("Contenu pertinent extrait.", offer["job_text"])

    def test_empty_page_does_not_create_an_offer(self):
        with self.assertRaises(ValueError):
            extractor.extract(URL, '<html><body><script>fake()</script></body></html>')

    def test_parser_and_cleaner_do_not_fetch_embedded_resources(self):
        raw = page(body='<div><h1>Analyste réseau</h1>' + DESCRIPTION +
                   '<img src="http://127.0.0.1/private"><iframe src="http://169.254.169.254/metadata">'
                   '</iframe></div>')
        with mock.patch("socket.create_connection", side_effect=AssertionError("unexpected network")) as connect:
            offer = extractor.extract(URL, raw)
        self.assertIn("Linux", offer["job_text"])
        connect.assert_not_called()

    def test_multiple_locations_are_not_assigned_an_arbitrary_single_city(self):
        locations = [{"address": {"addressLocality": city, "addressCountry": "FR"}}
                     for city in ("Menton", "Lyon")]
        offer = extractor.extract(URL, page(posting(jobLocation=locations)))
        self.assertEqual(offer["location"], "Non renseignée")
        self.assertIsNone(offer["location_city"])
        self.assertIn("plusieurs lieux", offer["location_provenance"])
        self.assertIn("Menton, FR", offer["job_text"])
        self.assertIn("Lyon, FR", offer["job_text"])

    def test_duplicate_jobposting_nodes_are_not_a_false_ambiguity(self):
        obj = posting()
        offer = extractor.extract(URL, page([obj, obj]))
        self.assertEqual(offer["company"], "Exemple Réseaux")

    def test_related_dom_sections_are_pruned_before_trafilatura(self):
        raw = page(body='<div><h1>Analyste réseau</h1>' + DESCRIPTION +
                   '<h2>Offres similaires</h2><p>Architecte senior à Amsterdam.</p></div>'
                   '<div>Autre contenu après les recommandations.</div>')
        with mock.patch.object(extractor.trafilatura, "extract", return_value="Mission pertinente.") as clean:
            offer = extractor.extract(URL, raw)
        source = clean.call_args.args[0]
        self.assertNotIn("Amsterdam", source)
        self.assertNotIn("Autre contenu après", source)
        self.assertIn("Mission pertinente.", offer["job_text"])

    def test_extraction_failure_does_not_call_jev(self):
        with (mock.patch.object(pipeline, "fetch_html", return_value='<html><body></body></html>'),
              mock.patch.object(pipeline.jev, "evaluate") as jev):
            result = pipeline.evaluate_url(URL, {})
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["stage"], "extract")
        jev.assert_not_called()


if __name__ == "__main__":
    unittest.main()
