"""Offline tests for first-launch CV onboarding."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pymupdf

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import onboarding
from engine import render_cv_pdf


MASTER = {
    "version": 1,
    "identity": {
        "name": "Ada Example",
        "headline_default": "Security Engineer",
        "email": "ada@example.test",
        "phone": "+00 123",
        "linkedin": "linkedin.com/in/ada",
        "mobility": "Brussels",
        "languages_line": "French, English",
    },
    "headline_words": ["Security", "Engineer"],
    "experiences": [{
        "id": "example_job", "title": "Security intern", "place": "Example Corp",
        "dates": "2025", "bullets": ["Analysed security alerts"], "tags": ["security"],
    }],
    "education": [{
        "id": "example_degree", "title": "Cybersecurity degree", "place": "Example School",
        "dates": "2024", "bullets": ["Network security"],
    }],
    "skill_groups": [{"id": "security", "label": "Security", "text": "SIEM, networks"}],
    "projects": [{"id": "lab", "title": "Home lab", "text": "Security monitoring lab"}],
    "eligibility_defense_only": [],
    "gap_notes_for_email": [],
}


class OnboardingTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.settings = {
            "profile_path": self.root / "PROFILE.json",
            "data_dir": self.root,
            "api_key_set": True,
            "openrouter": {"endpoint": "https://example.test", "model": "model"},
            "cv": {"master_path": self.root / "CV_MASTER.json", "model": ""},
        }
        self.settings_patch = mock.patch.object(onboarding.config, "settings", return_value=self.settings)
        self.settings_patch.start()

    def tearDown(self):
        self.settings_patch.stop()
        self.tmp.cleanup()

    @staticmethod
    def text_pdf() -> bytes:
        document = pymupdf.open()
        page = document.new_page()
        text = (
            "Ada Example - Security Engineer - ada@example.test\n"
            "Security internship at Example Corp in 2025. Analysed security alerts and networks.\n"
            "Cybersecurity degree at Example School in 2024. Skills: SIEM, network security.\n"
        ) * 5
        page.insert_textbox(pymupdf.Rect(40, 40, 550, 800), text, fontsize=9)
        result = document.tobytes()
        document.close()
        return result

    def test_status_requires_both_generated_files(self):
        current = onboarding.status()
        self.assertTrue(current["needed"])
        self.assertEqual(set(current["missing"]), {"PROFILE.json", "CV_MASTER.json"})
        self.settings["profile_path"].write_text(
            '{"criteria":[{"id":"fit","name":"Fit","description":"Fit","weight":1}]}',
            encoding="utf-8",
        )
        current = onboarding.status()
        self.assertEqual(current["missing"], ["CV_MASTER.json"])

    def test_success_creates_master_profile_and_source_pdf(self):
        with mock.patch.object(onboarding, "_generate_master", return_value=MASTER):
            result = onboarding.initialize(
                self.text_pdf(), "ada.pdf", "Security Engineer\nSOC analyst",
                "Brussels, Luxembourg", 3, 45,
            )
        self.assertFalse(onboarding.status()["needed"])
        self.assertEqual(result["candidate"], "Ada Example")
        profile = json.loads(self.settings["profile_path"].read_text(encoding="utf-8"))
        master = json.loads(self.settings["cv"]["master_path"].read_text(encoding="utf-8"))
        self.assertEqual(master["identity"]["name"], "Ada Example")
        self.assertGreaterEqual(len(profile["criteria"]), 5)
        self.assertEqual(profile["search"]["experience_filter"]["reject_if_minimum_required_years_gte"], 3)
        self.assertEqual(profile["search"]["max_age_days"], 45)
        self.assertTrue((self.root / "source_cv.pdf").is_file())

    def test_image_only_pdf_is_rejected_without_partial_files(self):
        document = pymupdf.open()
        document.new_page()
        content = document.tobytes()
        document.close()
        with self.assertRaisesRegex(onboarding.OnboardingError, "couche texte"):
            onboarding.initialize(content, "scan.pdf", "", "", 2, 30)
        self.assertFalse(self.settings["profile_path"].exists())
        self.assertFalse(self.settings["cv"]["master_path"].exists())

    def test_invalid_llm_answer_is_retried_once(self):
        valid = MASTER
        with (mock.patch.object(onboarding.config, "resolve_api_key", return_value="test-key"),
              mock.patch.object(onboarding, "_call_llm", side_effect=[{}, valid]) as request):
            generated = onboarding._generate_master("CV text " * 100, "ada.pdf")
        self.assertEqual(generated["identity"]["name"], "Ada Example")
        self.assertEqual(request.call_count, 2)

    def test_generated_master_can_render_a_one_page_cv(self):
        master = onboarding._normalise_master(MASTER, "ada.pdf")
        tailoring = {
            "headline": "Security Engineer",
            "experience_order": ["example_job"],
            "experience_bullets": {"example_job": ["Analysed security alerts"]},
            "education_order": ["example_degree"],
            "education_bullets": {"example_degree": ["Network security"]},
            "skill_groups_order": ["security"],
            "projects_order": ["lab"],
        }
        output = self.root / "rendered.pdf"
        pages, _ = render_cv_pdf.render(master, tailoring, output)
        self.assertEqual(pages, 1)
        self.assertGreater(output.stat().st_size, 1_000)

    def test_validation_rejects_incomplete_master(self):
        master = onboarding._normalise_master({"identity": {"name": ""}}, "empty.pdf")
        self.assertIn("identity.name manquant", onboarding.validate_master(master))


if __name__ == "__main__":
    unittest.main(verbosity=2)
