"""FastAPI v2.2 integration tests."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402
from app import accounts, config, pipeline, security, store  # noqa: E402
from app.main import app  # noqa: E402


class ApiV22(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.previous_db = store.DB_PATH
        self.saved = {key: os.environ.get(key) for key in (
            "JEV_CONFIG", "JEV_DATA_DIR", "JEV_AUTH_PASSWORD", "JEV_SESSION_SECRET",
        )}
        os.environ["JEV_CONFIG"] = str(self.root / "missing.toml")
        os.environ["JEV_DATA_DIR"] = str(self.root)
        os.environ.pop("JEV_AUTH_PASSWORD", None)
        os.environ["JEV_SESSION_SECRET"] = "z" * 40
        config.reset_cache()
        security._signing_key.cache_clear()
        security.LIMITER = security.RateLimiter()
        store.DB_PATH = str(self.root / "jev.db")
        accounts.create_user(
            "tester", "integration-password", "tester@example.test",
            role="admin", user_id="test-admin",
        )
        profile = {
            "version": 1, "candidate": {"name": "Test", "headline": "Engineer", "skills": []},
            "search": {"locations": ["Brussels"], "target_roles": ["Engineer"],
                       "max_age_days": 30, "experience_filter": {
                           "reject_if_minimum_required_years_gte": 2,
                           "internships_count_as_professional_experience": False}},
            "criteria": [{"id": "fit", "name": "Fit", "description": "Role fit",
                          "weight": 1, "required": False}],
            "hard_rejection_rules": [], "minimum_global_score": 68,
            "minimum_confidence": 0.5,
        }
        master = {
            "identity": {"name": "Test", "headline_default": "Engineer", "email": "",
                         "phone": "", "linkedin": "", "mobility": "", "languages_line": ""},
            "experiences": [], "education": [], "skill_groups": [], "projects": [],
            "headline_words": [],
        }
        user_dir = config.user_dir("test-admin")
        user_dir.mkdir(parents=True)
        (user_dir / "PROFILE.json").write_text(json.dumps(profile), encoding="utf-8")
        (user_dir / "CV_MASTER.json").write_text(json.dumps(master), encoding="utf-8")

    def login(self, client: TestClient) -> None:
        client.headers["Origin"] = "http://testserver"
        response = client.post("/login", data={
            "identifier": "tester", "password": "integration-password", "next": "/",
        }, follow_redirects=False)
        self.assertEqual(response.status_code, 303)

    def tearDown(self):
        store.DB_PATH = self.previous_db
        for key, value in self.saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        config.reset_cache()
        security._signing_key.cache_clear()
        self.tmp.cleanup()

    def test_profile_update_historique_et_conflit(self):
        with TestClient(app) as client:
            self.login(client)
            current = client.get("/api/profile").json()
            changed = current["profile"]
            changed["minimum_global_score"] = 74
            response = client.put("/api/profile", json={
                "profile": changed, "expected_revision": current["revision"],
            })
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["profile"]["minimum_global_score"], 74)
            self.assertGreaterEqual(len(client.get("/api/profile/history").json()["versions"]), 2)
            conflict = client.put("/api/profile", json={
                "profile": changed, "expected_revision": current["revision"],
            })
            self.assertEqual(conflict.status_code, 409)

    def test_cycle_candidature_et_exports(self):
        with TestClient(app) as client, mock.patch("app.main.network.validate_url"):
            self.login(client)
            created = client.post("/api/applications", json={
                "url": "https://example.com/job", "title": "Security Engineer",
                "company": "Example", "location": "Brussels",
            })
            self.assertEqual(created.status_code, 200)
            application = created.json()
            updated = client.patch(f"/api/applications/{application['id']}", json={
                "revision": application["revision"], "status": "applied",
                "applied_at": "2026-09-25", "follow_up_at": "2026-10-02",
                "contact_email": "recruiter@example.com",
            })
            self.assertEqual(updated.status_code, 200)
            detail = client.get(f"/api/applications/{application['id']}").json()
            self.assertEqual(detail["status"], "applied")
            self.assertGreaterEqual(len(detail["events"]), 2)
            self.assertIn("Security Engineer", client.get("/api/applications/export?fmt=csv").text)
            self.assertEqual(client.get("/api/applications/export?fmt=json").json()[0]["status"], "applied")

    def test_evaluation_manuelle_persiste_un_resultat(self):
        record = {
            "url": "http://127.0.0.1/private", "status": "ok", "stage": "done",
            "title": "Manual role", "company": "Example", "location": "Brussels",
            "published_at": "2026-09-25", "gate_results": [],
            "decision": {"status": "qualified", "hard_gate_failures": []},
            "jev": {"global_score": 80, "criteria": []},
        }
        with TestClient(app) as client, \
                mock.patch.object(pipeline, "evaluate_text", return_value=record):
            self.login(client)
            response = client.post("/api/evaluate/manual", json={
                "url": "http://127.0.0.1/private", "title": "Manual role",
                "company": "Example", "location": "Brussels",
                "published_at": "2026-09-25", "text": "A" * 500,
            })
            self.assertEqual(response.status_code, 200)
            run = client.get(f"/api/runs/{response.json()['run_id']}").json()
            self.assertEqual(run["status"], "done")
            self.assertEqual(run["results"][0]["title"], "Manual role")
            self.assertEqual(run["results"][0]["url"], "http://127.0.0.1/private")


if __name__ == "__main__":
    unittest.main(verbosity=2)
