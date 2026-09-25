"""FastAPI integration tests for the protected surface."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402
from app import config, security, store  # noqa: E402
from app.main import app  # noqa: E402


class ApiSecurity(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.previous_db = store.DB_PATH
        self.saved = {name: os.environ.get(name) for name in (
            "JEV_CONFIG", "JEV_DATA_DIR", "JEV_AUTH_PASSWORD", "JEV_SESSION_SECRET",
        )}
        os.environ["JEV_CONFIG"] = str(self.root / "missing.toml")
        os.environ["JEV_DATA_DIR"] = str(self.root)
        os.environ["JEV_AUTH_PASSWORD"] = "integration-password"
        os.environ["JEV_SESSION_SECRET"] = "x" * 40
        config.reset_cache()
        security._signing_key.cache_clear()
        security.LIMITER = security.RateLimiter()
        store.DB_PATH = str(self.root / "jev.db")

    def tearDown(self):
        store.DB_PATH = self.previous_db
        for name, value in self.saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        config.reset_cache()
        security._signing_key.cache_clear()
        self.tmp.cleanup()

    def test_health_public_et_api_protegee(self):
        with TestClient(app) as client:
            health = client.get("/healthz")
            self.assertEqual(health.status_code, 200)
            self.assertEqual(health.json(), {"ok": True, "version": "2.2.0", "auth_required": True})
            self.assertEqual(client.get("/api/history").status_code, 401)
            page = client.get("/offers", follow_redirects=False)
            self.assertEqual(page.status_code, 303)
            self.assertTrue(page.headers["location"].startswith("/login?next="))

    def test_login_pose_un_cookie_signe_et_donne_acces(self):
        with TestClient(app) as client:
            response = client.post(
                "/login", data={"password": "integration-password", "next": "/api/history"},
                follow_redirects=False,
            )
            self.assertEqual(response.status_code, 303)
            cookie = response.headers.get("set-cookie", "")
            self.assertIn("jev_session=", cookie)
            self.assertIn("HttpOnly", cookie)
            self.assertIn("SameSite=strict", cookie)
            self.assertEqual(client.get("/api/history").status_code, 200)

    def test_mauvais_mot_de_passe_ne_pose_pas_de_cookie(self):
        with TestClient(app) as client:
            response = client.post(
                "/login", data={"password": "wrong-password", "next": "/"},
                follow_redirects=False,
            )
            self.assertEqual(response.status_code, 401)
            self.assertNotIn("jev_session=", response.headers.get("set-cookie", ""))


if __name__ == "__main__":
    unittest.main(verbosity=2)
