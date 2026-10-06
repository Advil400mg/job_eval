"""Offline rendering checks for the v3 shell; no model calls or real data."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app import accounts, config, security, store
from app.main import app


class UiV3ApiTests(unittest.TestCase):
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
        os.environ["JEV_SESSION_SECRET"] = "v" * 40
        config.reset_cache()
        security._signing_key.cache_clear()
        security.LIMITER = security.RateLimiter()
        store.DB_PATH = str(self.root / "jev.db")
        self.user = accounts.create_user("ui-v3-user", "synthetic-password-v3", user_id="ui-v3-user-id")
        self.directory = config.user_dir(self.user["id"])
        self.directory.mkdir(parents=True, exist_ok=True)
        profile = {
            "version": 1, "candidate": {"name": "V3 Example", "headline": "Analyst", "skills": []},
            "search": {"target_roles": ["Analyst <script>"], "locations": ["France"],
                       "max_age_days": 30, "experience_filter": {
                           "reject_if_minimum_required_years_gte": 2,
                           "internships_count_as_professional_experience": False}},
            "criteria": [{"id": "fit", "name": "Fit", "description": "Occupation fit", "weight": 1, "required": False}],
            "hard_rejection_rules": [], "minimum_global_score": 68, "minimum_confidence": 0.5,
        }
        master = {
            "identity": {"name": "V3 Example", "headline_default": "Analyst", "email": "", "phone": "",
                         "linkedin": "", "mobility": "", "languages_line": ""},
            "experiences": [], "education": [], "skill_groups": [], "projects": [], "headline_words": [],
        }
        (self.directory / "PROFILE.json").write_text(json.dumps(profile), encoding="utf-8")
        (self.directory / "CV_MASTER.json").write_text(json.dumps(master), encoding="utf-8")

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

    def login(self, client):
        result = client.post("/login", data={
            "identifier": "ui-v3-user", "password": "synthetic-password-v3", "next": "/",
        }, follow_redirects=False)
        self.assertEqual(result.status_code, 303)

    def test_public_auth_shell_does_not_load_authenticated_polling(self):
        with TestClient(app) as client:
            response = client.get("/login")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("/static/common.js", response.text)
        self.assertIn("/static/shell.js", response.text)
        self.assertIn("data-theme-toggle", response.text)

    def test_dashboard_is_protected_by_existing_session_guard(self):
        with TestClient(app) as client:
            response = client.get("/dashboard", follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertTrue(response.headers["location"].startswith("/login?next="))

    def test_dashboard_uses_owner_profile_without_rewriting_it(self):
        profile_path = self.directory / "PROFILE.json"
        before = profile_path.read_bytes()
        with TestClient(app) as client:
            self.login(client)
            response = client.get("/dashboard")
            self.assertEqual(response.status_code, 200)
            self.assertIn('id="dashboard_total"', response.text)
            self.assertIn("Analyst &lt;script&gt;", response.text)
            self.assertNotIn("Camille Exemple", response.text)
            self.assertEqual(client.get("/api/offers").json()["total"], 0)
        self.assertEqual(profile_path.read_bytes(), before)

    def test_root_keeps_existing_evaluation_route_and_api_hooks(self):
        with TestClient(app) as client:
            self.login(client)
            response = client.get("/")
        self.assertEqual(response.status_code, 200)
        for hook in ('id="urls"', 'id="manual_form"', 'id="recent_runs"', 'id="run"'):
            self.assertIn(hook, response.text)
        self.assertIn("Évaluer des offres", response.text)
        self.assertIn('data-evaluation-mode="text"', response.text)
        self.assertRegex(response.text, r'/static/common\.js\?v=[^"]+-ui3"')
        self.assertRegex(response.text, r'/static/evaluate\.js\?v=[^"]+-ui3"')

    def test_non_admin_shell_has_theme_and_all_personal_routes(self):
        with TestClient(app) as client:
            self.login(client)
            response = client.get("/dashboard")
        for path in ("/offers", "/applications", "/cv", "/runs", "/analytics", "/profile"):
            self.assertIn(f'href="{path}"', response.text)
        self.assertIn("data-theme-toggle", response.text)
        self.assertIn('id="app_menu_toggle"', response.text)
        self.assertIn('id="action_dialog"', response.text)
        self.assertNotIn('href="/admin"', response.text)

    def test_dashboard_keeps_onboarding_guard_for_missing_profile(self):
        (self.directory / "PROFILE.json").unlink()
        with TestClient(app) as client:
            self.login(client)
            response = client.get("/dashboard")
        self.assertEqual(response.status_code, 200)
        self.assertIn('id="setup_form"', response.text)
        self.assertNotIn('id="dashboard_total"', response.text)
