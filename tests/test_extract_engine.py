"""Offer extraction used by CV tailoring must share the V3.0.1 parser."""
import unittest
from unittest import mock

from app import extract as extractor
from engine import tailor_cv
from tests.test_extract_v301 import URL, page, posting


class CVOfferExtraction(unittest.TestCase):
    def test_cv_and_evaluation_use_same_clean_content(self):
        raw = page(posting(), encoded=True)
        with mock.patch.object(tailor_cv.safe_network, "fetch_text", return_value=raw):
            text, metadata, saved_html = tailor_cv.fetch_offer(URL)
        offer = extractor.extract(URL, raw)
        self.assertEqual(text, offer["job_text"])
        self.assertEqual(metadata["title"], offer["title"])
        self.assertEqual(metadata["company"], "Exemple Réseaux")
        self.assertEqual(metadata["location"], "Menton, FR")
        self.assertEqual(saved_html, raw)

    def test_cv_does_not_use_portal_as_employer(self):
        raw = page(posting(hiringOrganization=None))
        with mock.patch.object(tailor_cv.safe_network, "fetch_text", return_value=raw):
            _, metadata, _ = tailor_cv.fetch_offer(URL)
        self.assertEqual(metadata["company"], "Non renseigné")
        self.assertEqual(metadata["site"], "Portail Exemple")

    def test_cv_metadata_retains_contract_array_without_inventing_cdi(self):
        with mock.patch.object(tailor_cv.safe_network, "fetch_text", return_value=page(posting())):
            _, metadata, _ = tailor_cv.fetch_offer(URL)
        self.assertIn("INTERN", metadata["contract"])
        self.assertIn("FULL_TIME", metadata["contract"])
        self.assertNotIn("CDI", metadata["contract"])

    def test_shared_helpers_handle_graphs_and_encoded_attributes(self):
        raw = page({"@graph": [posting()]}, encoded=True)
        obj = tailor_cv.json_ld_job(raw)
        self.assertIsNotNone(obj)
        assert obj is not None
        self.assertEqual(obj["title"], "Ingénieur réseau junior H/F")
        self.assertEqual(tailor_cv.html_to_text('<p data-action="click->foo#bar">Contenu.</p>'),
                         "Contenu.")
        self.assertEqual(tailor_cv.meta_content('<meta content="A &amp; B" property="og:site_name">',
                                               "og:site_name"), "A & B")

    def test_network_failure_is_not_hidden(self):
        with mock.patch.object(tailor_cv.safe_network, "fetch_text",
                               side_effect=RuntimeError("network failure")):
            with self.assertRaisesRegex(RuntimeError, "network failure"):
                tailor_cv.fetch_offer(URL)


if __name__ == "__main__":
    unittest.main()
