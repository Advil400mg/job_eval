"""End-to-end API isolation between two authenticated users."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from app import accounts, config, security, store
from app.main import app


PROFILE = {
    "version": 1,
    "candidate": {"name": "Test", "headline": "Engineer", "skills": []},
    "search": {"locations": [], "target_roles": ["Engineer"], "max_age_days": 30,
               "experience_filter": {"reject_if_minimum_required_years_gte": 2,
                                     "internships_count_as_professional_experience": False}},
    "criteria": [{"id": "fit", "name": "Fit", "description": "Role fit",
                  "weight": 1, "required": False}],
    "hard_rejection_rules": [], "minimum_global_score": 68, "minimum_confidence": 0.5,
}
MASTER = {
    "identity": {"name": "Test", "headline_default": "Engineer", "email": "",
                 "phone": "", "linkedin": "", "mobility": "", "languages_line": ""},
    "experiences": [], "education": [], "skill_groups": [], "projects": [],
    "headline_words": [],
}


class MultiUserApiTest(unittest.TestCase):
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
        os.environ["JEV_SESSION_SECRET"] = "m" * 40
        config.reset_cache()
        security._signing_key.cache_clear()
        security.LIMITER = security.RateLimiter()
        store.DB_PATH = str(self.root / "jev.db")
        self.alice = accounts.create_user(
            "alice", "correct-horse-battery", "alice@example.test", role="admin", user_id="alice-id",
        )
        self.bob = accounts.create_user(
            "bob", "another-correct-password", "bob@example.test", user_id="bob-id",
        )
        for user, name in ((self.alice, "Alice"), (self.bob, "Bob")):
            directory = config.user_dir(user["id"])
            directory.mkdir(parents=True)
            profile = dict(PROFILE)
            profile["candidate"] = {**PROFILE["candidate"], "name": name}
            (directory / "PROFILE.json").write_text(json.dumps(profile), encoding="utf-8")
            master = dict(MASTER)
            master["identity"] = {**MASTER["identity"], "name": name}
            (directory / "CV_MASTER.json").write_text(json.dumps(master), encoding="utf-8")

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

    def login(self, client: TestClient, identifier: str, password: str) -> None:
        client.headers["Origin"] = "http://testserver"
        response = client.post("/login", data={
            "identifier": identifier, "password": password, "next": "/",
        }, follow_redirects=False)
        self.assertEqual(response.status_code, 303)

    def test_runs_applications_and_profiles_are_isolated(self):
        alice_run = store.create_run(["https://jobs.test/alice"], self.alice["id"])
        store.save_result(alice_run, "https://jobs.test/alice", "ok", {
            "url": "https://jobs.test/alice", "title": "Alice role", "status": "ok",
            "decision": {"status": "qualified"}, "jev": {"global_score": 80},
        })
        store.finish_run(alice_run)
        with TestClient(app) as alice_client, TestClient(app) as bob_client, \
                mock.patch("app.main.network.validate_url"):
            self.login(alice_client, "alice", "correct-horse-battery")
            self.login(bob_client, "bob", "another-correct-password")
            self.assertEqual(alice_client.get(f"/api/runs/{alice_run}").status_code, 200)
            self.assertEqual(bob_client.get(f"/api/runs/{alice_run}").status_code, 404)
            created = alice_client.post("/api/applications", json={
                "url": "https://jobs.test/alice", "title": "Alice role",
            })
            self.assertEqual(created.status_code, 200)
            self.assertEqual(alice_client.get("/api/applications").json()["total"], 1)
            self.assertEqual(bob_client.get("/api/applications").json()["total"], 0)
            self.assertEqual(alice_client.get("/api/profile").json()["profile"]["candidate"]["name"], "Alice")
            self.assertEqual(bob_client.get("/api/profile").json()["profile"]["candidate"]["name"], "Bob")

    def test_admin_invitation_registration_and_single_use(self):
        with TestClient(app) as admin_client, TestClient(app) as guest_client:
            self.login(admin_client, "alice", "correct-horse-battery")
            created = admin_client.post("/api/admin/invitations", json={
                "email": "guest@example.test", "expires_hours": 72, "send_email": False,
            })
            self.assertEqual(created.status_code, 200)
            token = created.json()["token"]
            registered = guest_client.post("/register", data={
                "token": token, "username": "guest", "email": "guest@example.test",
                "display_name": "Guest", "password": "guest-correct-password",
            }, follow_redirects=False)
            self.assertEqual(registered.status_code, 303)
            reused = TestClient(app).post("/register", data={
                "token": token, "username": "other", "email": "guest@example.test",
                "password": "other-correct-password",
            }, follow_redirects=False)
            self.assertEqual(reused.status_code, 400)


if __name__ == "__main__":
    unittest.main(verbosity=2)
