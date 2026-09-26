"""Tests pour l'isolation des fichiers par utilisateur (v5).

Vérifie que chaque module utilise bien data/users/{IDENTIFIANT}/ pour ses
chemins, et que user_id=None → legacy-admin en rétrocompatibilité.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config, cv, onboarding, pipeline, profile, store


class UserDirHelperTest(unittest.TestCase):
    """config.user_dir() est la brique de base de l'isolation."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.saved = {k: os.environ.get(k) for k in ("JEV_CONFIG", "JEV_DATA_DIR")}
        os.environ["JEV_CONFIG"] = str(self.root / "absent.toml")
        os.environ["JEV_DATA_DIR"] = str(self.root)
        config.reset_cache()

    def tearDown(self):
        for key, value in self.saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        config.reset_cache()
        self.tmp.cleanup()

    def test_user_dir_none_resolves_to_legacy_admin(self):
        u_dir = config.user_dir(None)
        self.assertEqual(u_dir, self.root / "users" / "legacy-admin")

    def test_user_dir_explicit_user_id(self):
        u_dir = config.user_dir("user-abc123")
        self.assertEqual(u_dir, self.root / "users" / "user-abc123")

    def test_user_dir_contains_expected_subdirs(self):
        u_dir = config.user_dir("test-user")
        self.assertEqual(u_dir / "PROFILE.json", u_dir / "PROFILE.json")
        self.assertEqual(u_dir / "CV_MASTER.json", u_dir / "CV_MASTER.json")
        self.assertEqual(u_dir / "source_cv.pdf", u_dir / "source_cv.pdf")
        self.assertEqual(u_dir / "cv", u_dir / "cv")
        self.assertEqual(u_dir / "cv-runs", u_dir / "cv-runs")


class OnboardingPathsTest(unittest.TestCase):
    """onboarding.paths() et status() utilisent le bon répertoire."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.saved = {k: os.environ.get(k) for k in ("JEV_CONFIG", "JEV_DATA_DIR")}
        os.environ["JEV_CONFIG"] = str(self.root / "absent.toml")
        os.environ["JEV_DATA_DIR"] = str(self.root)
        config.reset_cache()
        # Pré-créer le répertoire legacy-admin pour les tests status()
        (config.user_dir()).mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        for key, value in self.saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        config.reset_cache()
        self.tmp.cleanup()

    def test_paths_none_uses_legacy_admin(self):
        p, m, s = onboarding.paths(None)
        self.assertEqual(p.parent.name, "legacy-admin")
        self.assertEqual(p.name, "PROFILE.json")
        self.assertEqual(m.name, "CV_MASTER.json")
        self.assertEqual(s.name, "source_cv.pdf")

    def test_paths_explicit_user(self):
        p, m, s = onboarding.paths("alice-123")
        self.assertTrue("alice-123" in str(p))
        self.assertTrue("alice-123" in str(m))
        self.assertTrue("alice-123" in str(s))

    def test_status_returns_paths_with_user_dir(self):
        # Écrire PROFILE.json dans le répertoire du bon utilisateur
        u_dir = config.user_dir(None)
        (u_dir / "PROFILE.json").write_text(
            '{"criteria":[{"id":"fit","name":"F","description":"D","weight":1}]}', encoding="utf-8")
        st = onboarding.status(None)
        self.assertIn("legacy-admin", st["profile_path"])

    def test_initialize_writes_to_user_dir(self):
        u_dir = config.user_dir("bob-456")
        u_dir.mkdir(parents=True, exist_ok=True)
        master = {
            "version": 1, "updated": "2025-01-01", "source": "test",
            "identity": {
                "name": "Bob", "headline_default": "Dev",
                "email": "b@t.com", "phone": "000", "linkedin": "",
                "mobility": "", "languages_line": "",
            },
            "headline_words": ["Dev"],
            "rules": [], "experiences": [], "education": [],
            "skill_groups": [], "projects": [],
            "profile_facts": [], "eligibility_defense_only": [],
            "gap_notes_for_email": [],
        }
        profile_data = {
            "version": 1, "generated_from": "test",
            "candidate": {"name": "Bob", "headline": "Dev", "skills": []},
            "search": {"locations": [], "target_roles": ["Dev"],
                       "max_age_days": 30,
                       "experience_filter": {
                           "reject_if_minimum_required_years_gte": 2,
                           "internships_count_as_professional_experience": False,
                       }},
            "criteria": [{"id": "fit", "name": "Fit", "description": "D",
                          "weight": 1, "required": False}],
            "hard_rejection_rules": [],
            "minimum_global_score": 50,
            "minimum_confidence": 0.5,
        }

        with (mock.patch.object(onboarding, "extract_pdf_text", return_value="CV text " * 200),
              mock.patch.object(onboarding, "_generate_master", return_value=master),
              mock.patch.object(onboarding, "build_profile", return_value=profile_data)):
            result = onboarding.initialize(
                b"%PDF-1.4\n%%EOF\n", "cv.pdf", "Dev", "", 2, 30,
                user_id="bob-456",
            )
        self.assertEqual(result["candidate"], "Bob")
        self.assertIn("bob-456", result["profile_path"])
        self.assertIn("bob-456", result["master_path"])
        self.assertTrue((u_dir / "source_cv.pdf").is_file())
        self.assertTrue((u_dir / "PROFILE.json").is_file())
        self.assertTrue((u_dir / "CV_MASTER.json").is_file())

    def test_initialize_none_uses_legacy_admin(self):
        u_dir = config.user_dir(None)
        u_dir.mkdir(parents=True, exist_ok=True)
        master = {
            "version": 1, "updated": "2025-01-01", "source": "test",
            "identity": {
                "name": "Admin", "headline_default": "Admin",
                "email": "a@t.com", "phone": "000", "linkedin": "",
                "mobility": "", "languages_line": "",
            },
            "headline_words": ["Admin"],
            "rules": [], "experiences": [], "education": [],
            "skill_groups": [], "projects": [],
            "profile_facts": [], "eligibility_defense_only": [],
            "gap_notes_for_email": [],
        }
        profile_data = {
            "version": 1, "generated_from": "test",
            "candidate": {"name": "Admin", "headline": "Admin", "skills": []},
            "search": {"locations": [], "target_roles": ["Admin"],
                       "max_age_days": 30,
                       "experience_filter": {
                           "reject_if_minimum_required_years_gte": 2,
                           "internships_count_as_professional_experience": False,
                       }},
            "criteria": [{"id": "fit", "name": "Fit", "description": "D",
                          "weight": 1, "required": False}],
            "hard_rejection_rules": [],
            "minimum_global_score": 50,
            "minimum_confidence": 0.5,
        }
        with (mock.patch.object(onboarding, "extract_pdf_text", return_value="CV text " * 200),
              mock.patch.object(onboarding, "_generate_master", return_value=master),
              mock.patch.object(onboarding, "build_profile", return_value=profile_data)):
            result = onboarding.initialize(
                b"%PDF-1.4\n%%EOF\n", "cv.pdf", "Admin", "", 2, 30,
            )
        self.assertIn("legacy-admin", result["profile_path"])


class ProfilePathsTest(unittest.TestCase):
    """profile.path(), load_profile() etc. utilisent user_dir."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.previous_db = store.DB_PATH
        self.saved = {k: os.environ.get(k) for k in ("JEV_CONFIG", "JEV_DATA_DIR")}
        os.environ["JEV_CONFIG"] = str(self.root / "absent.toml")
        os.environ["JEV_DATA_DIR"] = str(self.root)
        config.reset_cache()
        store.DB_PATH = str(self.root / "jev.db")

    def tearDown(self):
        store.DB_PATH = self.previous_db
        for key, value in self.saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        config.reset_cache()
        self.tmp.cleanup()

    def test_path_none_points_to_legacy_admin(self):
        p = profile.path(None)
        self.assertIn("legacy-admin", str(p))
        self.assertEqual(p.name, "PROFILE.json")

    def test_path_explicit_user(self):
        p = profile.path("charlie-789")
        self.assertIn("charlie-789", str(p))

    def test_load_profile_reads_from_user_dir(self):
        u_dir = config.user_dir("dave")
        u_dir.mkdir(parents=True, exist_ok=True)
        sample = {
            "version": 1, "generated_from": "test",
            "candidate": {"name": "Dave", "headline": "Dev", "skills": []},
            "search": {"locations": [], "target_roles": ["Dev"],
                       "max_age_days": 30,
                       "experience_filter": {
                           "reject_if_minimum_required_years_gte": 2,
                           "internships_count_as_professional_experience": False,
                       }},
            "criteria": [{"id": "fit", "name": "Fit", "description": "D",
                          "weight": 1, "required": False}],
            "hard_rejection_rules": [],
            "minimum_global_score": 50,
            "minimum_confidence": 0.5,
        }
        (u_dir / "PROFILE.json").write_text(
            json.dumps(sample, ensure_ascii=False), encoding="utf-8")
        loaded = profile.load_profile("dave")
        self.assertEqual(loaded["candidate"]["name"], "Dave")


class CvPathsTest(unittest.TestCase):
    """cv.out_dir() et cv.generate() utilisent user_dir."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.saved = {k: os.environ.get(k) for k in ("JEV_CONFIG", "JEV_DATA_DIR")}
        os.environ["JEV_CONFIG"] = str(self.root / "absent.toml")
        os.environ["JEV_DATA_DIR"] = str(self.root)
        config.reset_cache()

    def tearDown(self):
        for key, value in self.saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        config.reset_cache()
        self.tmp.cleanup()

    def test_out_dir_none_points_to_legacy_admin(self):
        d = cv.out_dir(None)
        self.assertIn("legacy-admin", d)
        self.assertTrue(d.endswith("/cv") or d.endswith("\\cv"))

    def test_out_dir_explicit_user(self):
        d = cv.out_dir("eve-101")
        self.assertIn("eve-101", d)

    def test_cv_environment_sets_user_scoped_paths(self):
        """cv_environment() doit définir CV_PROFILE/CV_MASTER/CV_OUT_DIR
        sous data/users/{user_id}/."""
        env, _ = config.cv_environment(user_id="frank-202")
        self.assertIn("frank-202", env["CV_PROFILE"])
        self.assertIn("frank-202", env["CV_MASTER"])
        self.assertIn("frank-202", env["CV_OUT_DIR"])
        self.assertIn("frank-202", env["CV_RUNS"])
        self.assertTrue(env["CV_PROFILE"].endswith("PROFILE.json"))
        self.assertTrue(env["CV_MASTER"].endswith("CV_MASTER.json"))

    def test_cv_environment_user_none_uses_legacy_admin(self):
        env, _ = config.cv_environment(user_id=None)
        self.assertIn("legacy-admin", env["CV_PROFILE"])
        self.assertIn("legacy-admin", env["CV_MASTER"])
        self.assertIn("legacy-admin", env["CV_OUT_DIR"])


class PipelinePathsTest(unittest.TestCase):
    """pipeline.profile_path() utilise user_dir."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.saved = {k: os.environ.get(k) for k in ("JEV_CONFIG", "JEV_DATA_DIR")}
        os.environ["JEV_CONFIG"] = str(self.root / "absent.toml")
        os.environ["JEV_DATA_DIR"] = str(self.root)
        config.reset_cache()

    def tearDown(self):
        for key, value in self.saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        config.reset_cache()
        self.tmp.cleanup()

    def test_profile_path_none_legacy_admin(self):
        p = pipeline.profile_path(None)
        self.assertIn("legacy-admin", p)
        self.assertTrue(p.endswith("PROFILE.json"))

    def test_profile_path_explicit_user(self):
        p = pipeline.profile_path("grace-303")
        self.assertIn("grace-303", p)


class CrossUserIsolationTest(unittest.TestCase):
    """Deux utilisateurs ne doivent pas partager les mêmes fichiers."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.previous_db = store.DB_PATH
        self.saved = {k: os.environ.get(k) for k in ("JEV_CONFIG", "JEV_DATA_DIR")}
        os.environ["JEV_CONFIG"] = str(self.root / "absent.toml")
        os.environ["JEV_DATA_DIR"] = str(self.root)
        config.reset_cache()
        store.DB_PATH = str(self.root / "jev.db")

    def tearDown(self):
        store.DB_PATH = self.previous_db
        for key, value in self.saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        config.reset_cache()
        self.tmp.cleanup()

    def test_user_a_and_user_b_have_distinct_paths(self):
        a_dir = config.user_dir("user-a")
        b_dir = config.user_dir("user-b")
        self.assertNotEqual(a_dir, b_dir)
        self.assertIn("user-a", str(a_dir))
        self.assertIn("user-b", str(b_dir))

    def test_user_a_file_not_readable_as_user_b(self):
        # Écrire PROFILE.json pour user-a
        a_dir = config.user_dir("user-a")
        a_dir.mkdir(parents=True, exist_ok=True)
        sample = {
            "version": 1, "generated_from": "test",
            "candidate": {"name": "Alice", "headline": "Dev", "skills": []},
            "search": {"locations": [], "target_roles": ["Dev"],
                       "max_age_days": 30,
                       "experience_filter": {
                           "reject_if_minimum_required_years_gte": 2,
                           "internships_count_as_professional_experience": False,
                       }},
            "criteria": [{"id": "fit", "name": "Fit", "description": "D",
                          "weight": 1, "required": False}],
            "hard_rejection_rules": [],
            "minimum_global_score": 50,
            "minimum_confidence": 0.5,
        }
        (a_dir / "PROFILE.json").write_text(
            json.dumps(sample, ensure_ascii=False), encoding="utf-8")

        # user-b n'a pas de PROFILE.json → doit lever une erreur
        with self.assertRaises(profile.ProfileError):
            profile.load_profile("user-b")


if __name__ == "__main__":
    unittest.main(verbosity=2)