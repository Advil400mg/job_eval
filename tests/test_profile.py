"""Profile validation, concurrency and version history tests."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config, profile, store  # noqa: E402


def sample_profile() -> dict:
    return {
        "version": 1,
        "generated_from": "test",
        "candidate": {"name": "Candidate", "headline": "Engineer", "skills": ["Python"]},
        "search": {
            "locations": ["Brussels"],
            "target_roles": ["Security Engineer"],
            "max_age_days": 30,
            "experience_filter": {
                "reject_if_minimum_required_years_gte": 2,
                "internships_count_as_professional_experience": False,
            },
        },
        "criteria": [{
            "id": "role_fit", "name": "Role fit", "description": "Matches the target role",
            "weight": 5, "required": True, "min_score": 60,
        }],
        "hard_rejection_rules": ["Expired offer"],
        "minimum_global_score": 68,
        "minimum_confidence": 0.5,
    }


class ProfileManagement(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.previous_db = store.DB_PATH
        self.saved = {key: os.environ.get(key) for key in ("JEV_CONFIG", "JEV_DATA_DIR", "JEV_PROFILE")}
        os.environ["JEV_CONFIG"] = str(self.root / "missing.toml")
        os.environ["JEV_DATA_DIR"] = str(self.root)
        os.environ["JEV_PROFILE"] = str(self.root / "PROFILE.json")
        config.reset_cache()
        store.DB_PATH = str(self.root / "jev.db")
        (self.root / "PROFILE.json").write_text(
            json.dumps(sample_profile(), ensure_ascii=False), encoding="utf-8",
        )

    def tearDown(self):
        store.DB_PATH = self.previous_db
        for key, value in self.saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        config.reset_cache()
        self.tmp.cleanup()

    def test_validation_couvre_seuils_recherche_et_criteres(self):
        invalid = sample_profile()
        invalid["minimum_confidence"] = 2
        invalid["search"]["max_age_days"] = 0
        invalid["criteria"][0]["id"] = "Invalid id"
        invalid["criteria"][0]["required"] = False
        invalid["criteria"][0]["min_score"] = "invalid"
        errors = profile.validate_profile(invalid)
        self.assertTrue(any("minimum_confidence" in error for error in errors))
        self.assertTrue(any("max_age_days" in error for error in errors))
        self.assertTrue(any("criteria[0].id" in error for error in errors))
        self.assertTrue(any("criteria[0].min_score" in error for error in errors))

    def test_modification_est_atomique_historisee_et_preserve_identite(self):
        current = profile.current()
        proposed = sample_profile()
        proposed["candidate"] = {"name": "Injected"}
        proposed["minimum_global_score"] = 72
        proposed["search"]["locations"] = ["Luxembourg"]
        result = profile.update_profile(proposed, current["revision"])
        self.assertTrue(result["changed"])
        self.assertEqual(result["profile"]["candidate"]["name"], "Candidate")
        self.assertEqual(profile.load_profile()["minimum_global_score"], 72)
        versions = profile.history()
        self.assertEqual(len(versions), 2)
        self.assertEqual({item["revision"] for item in versions}, {current["revision"], result["revision"]})

    def test_revision_obsolete_est_refusee(self):
        current = profile.current()
        updated = sample_profile()
        updated["minimum_global_score"] = 70
        profile.update_profile(updated, current["revision"])
        with self.assertRaises(profile.ProfileConflict):
            profile.update_profile(sample_profile(), current["revision"])

    def test_restauration_revient_a_une_version_precedente(self):
        current = profile.current()
        updated = sample_profile()
        updated["minimum_global_score"] = 75
        changed = profile.update_profile(updated, current["revision"])
        old_version = next(item for item in profile.history() if item["revision"] == current["revision"])
        restored = profile.restore(old_version["id"], changed["revision"])
        self.assertEqual(restored["profile"]["minimum_global_score"], 68)
        self.assertEqual(profile.load_profile()["minimum_global_score"], 68)


if __name__ == "__main__":
    unittest.main(verbosity=2)
