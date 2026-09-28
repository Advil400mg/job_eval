"""Isolated v2.6 onboarding and profile-policy API regression tests."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from app import config, pipeline, security, store
from app.main import app


class ProfilePolicyApi(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.previous_db = store.DB_PATH
        self.saved = {key: os.environ.get(key) for key in (
            "JEV_CONFIG", "JEV_DATA_DIR", "JEV_AUTH_PASSWORD", "JEV_SESSION_SECRET",
        )}
        os.environ["JEV_CONFIG"] = str(Path(self.tmp.name) / "absent.toml")
        os.environ["JEV_DATA_DIR"] = self.tmp.name
        os.environ["JEV_AUTH_PASSWORD"] = "isolated-test-password"
        os.environ["JEV_SESSION_SECRET"] = "a" * 40
        config.reset_cache()
        security._signing_key.cache_clear()
        security.LIMITER = security.RateLimiter()
        store.DB_PATH = str(Path(self.tmp.name) / "jev.db")

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

    def test_manual_profile_preview_confirmation_and_no_cv(self):
        with TestClient(app) as client:
            login = client.post("/login", data={
                "identifier": "admin", "password": "isolated-test-password", "next": "/",
            }, follow_redirects=False)
            self.assertEqual(login.status_code, 303)
            client.headers["Origin"] = "http://testserver"
            blocked = client.post("/api/evaluate", json={"urls": ["https://example.test/job"]})
            self.assertEqual(blocked.status_code, 428)
            data = {
                "name": "Example Person", "target_roles": "Senior Quant",
                "locations": "Deutschland\nBerlin, DE", "preferred_locations": "Berlin, DE",
                "skills": "Python\nStatistics", "languages_line": "Deutsch B2, English C1",
                "seniority": "senior", "candidate_years": 8,
                "reject_experience_years": 12,
                "contract_types": ["permanent", "freelance"],
            }
            created = client.post("/api/onboarding/manual", json=data)
            self.assertEqual(created.status_code, 200, created.text)
            setup = client.get("/api/onboarding").json()
            self.assertFalse(setup["needed"])
            self.assertFalse(setup["cv_available"])
            self.assertEqual(client.post("/api/onboarding/manual", json=data).status_code, 409)
            current = client.get("/api/profile").json()
            self.assertFalse(current["profile"]["search"]["confirmed"])
            self.assertEqual(current["profile"]["search"]["locations"], ["Deutschland", "Berlin, DE"])
            self.assertEqual(current["profile"]["search"]["preferred_locations"], ["Berlin, DE"])
            self.assertEqual(client.post("/api/evaluate", json={
                "urls": ["https://example.test/job"],
            }).status_code, 428)
            preview = client.post("/api/profile/preview", json={
                "profile": current["profile"], "expected_revision": current["revision"],
            })
            self.assertEqual(preview.status_code, 200, preview.text)
            self.assertIn("Senior Quant", preview.json()["profile_context"]["target_roles"])
            self.assertIn("Deutschland", next(c["description"] for c in
                          preview.json()["criteria"] if c["id"] == "location_fit"))

            modified = current["profile"]
            modified["search"]["preferred_locations"].append("München, DE")
            saved = client.put("/api/profile", json={
                "profile": modified, "expected_revision": current["revision"],
            })
            self.assertEqual(saved.status_code, 200, saved.text)
            self.assertEqual(client.post("/api/evaluate", json={
                "urls": ["https://example.test/job"],
            }).status_code, 428)
            stale = client.post("/api/profile/preview", json={
                "profile": modified, "expected_revision": current["revision"],
            })
            self.assertEqual(stale.status_code, 409)
            modified["search"]["confirmed"] = True
            confirmed = client.put("/api/profile", json={
                "profile": modified, "expected_revision": saved.json()["revision"],
            })
            self.assertEqual(confirmed.status_code, 200, confirmed.text)
            fake_record = {"url": "https://example.test/job", "status": "ok", "stage": "done"}
            with mock.patch.object(pipeline, "evaluate_text", return_value=fake_record) as evaluate:
                result = client.post("/api/evaluate/manual", json={
                    "url": "https://example.test/job", "text": "Offer details " * 50,
                    "title": "Quant", "company": "Example", "location": "Berlin",
                })
            self.assertEqual(result.status_code, 200, result.text)
            self.assertEqual(evaluate.call_args.args[2]["search"]["seniority"], "senior")
            self.assertEqual(client.get(f"/api/runs/{result.json()['run_id']}").json()["status"], "done")


if __name__ == "__main__":
    unittest.main()
