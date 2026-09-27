"""FastAPI integration tests for the protected surface."""

from __future__ import annotations

import os
import sys
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402
from app import accounts, config, onboarding, security, store  # noqa: E402
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
            self.assertEqual(health.json(), {"ok": True, "version": "2.5.0", "auth_required": True})
            self.assertIn("default-src 'self'", health.headers["content-security-policy"])
            self.assertEqual(client.get("/api/history").status_code, 401)
            page = client.get("/offers", follow_redirects=False)
            self.assertEqual(page.status_code, 303)
            self.assertTrue(page.headers["location"].startswith("/login?next="))

    def test_onboarding_long_ne_bloque_pas_healthz(self):
        entered = threading.Event()
        release = threading.Event()

        def slow_initialize(*args, **kwargs):
            entered.set()
            release.wait(timeout=3)
            return {"ok": True, "candidate": "Test"}

        with TestClient(app) as client:
            login = client.post(
                "/login",
                data={"identifier": "admin", "password": "integration-password", "next": "/"},
                follow_redirects=False,
            )
            self.assertEqual(login.status_code, 303)
            client.headers["Origin"] = "http://testserver"
            with mock.patch.object(onboarding, "initialize", side_effect=slow_initialize):
                with ThreadPoolExecutor(max_workers=1) as executor:
                    pending = executor.submit(
                        client.post,
                        "/api/onboarding",
                        files={"cv_pdf": ("cv.pdf", b"%PDF-test", "application/pdf")},
                    )
                    self.assertTrue(entered.wait(timeout=1), "l'analyse CV n'a pas démarré")
                    started = time.monotonic()
                    health = client.get("/healthz")
                    elapsed = time.monotonic() - started
                    release.set()
                    response = pending.result(timeout=2)

        self.assertEqual(health.status_code, 200)
        self.assertLess(elapsed, 0.75, f"/healthz a attendu {elapsed:.2f} s")
        self.assertEqual(response.status_code, 200)

    def test_refresh_exposes_running_onboarding_and_rejects_duplicate(self):
        entered = threading.Event()
        release = threading.Event()
        master = {
            "identity": {
                "name": "Ada Example", "headline_default": "Security Engineer",
                "email": "ada@example.test", "phone": "", "linkedin": "",
                "mobility": "Brussels", "languages_line": "Français, anglais",
            },
            "experiences": [], "education": [], "skill_groups": [], "projects": [],
            "headline_words": ["Security", "Engineer"], "profile_facts": [],
            "eligibility_defense_only": [], "gap_notes_for_email": [],
        }

        def slow_master(*args, **kwargs):
            entered.set()
            release.wait(timeout=3)
            return master

        with TestClient(app) as client:
            login = client.post(
                "/login",
                data={"identifier": "admin", "password": "integration-password", "next": "/"},
                follow_redirects=False,
            )
            self.assertEqual(login.status_code, 303)
            client.headers["Origin"] = "http://testserver"
            with (mock.patch.object(onboarding, "extract_pdf_text", return_value="CV text " * 200),
                  mock.patch.object(onboarding, "_generate_master", side_effect=slow_master)):
                with ThreadPoolExecutor(max_workers=1) as executor:
                    pending = executor.submit(
                        client.post,
                        "/api/onboarding",
                        files={"cv_pdf": ("cv.pdf", b"%PDF-test", "application/pdf")},
                    )
                    self.assertTrue(entered.wait(timeout=1), "l'analyse CV n'a pas démarré")

                    status_response = client.get("/api/onboarding")
                    self.assertEqual(status_response.status_code, 200)
                    setup = status_response.json()
                    self.assertTrue(setup["needed"])
                    self.assertTrue(setup["processing"])
                    self.assertEqual(setup["job"]["status"], "running")

                    page = client.get("/")
                    self.assertEqual(page.status_code, 200)
                    self.assertIn("Analyse du CV en cours", page.text)
                    self.assertIn('data-processing="true"', page.text)

                    duplicate = client.post(
                        "/api/onboarding",
                        files={"cv_pdf": ("cv.pdf", b"%PDF-test", "application/pdf")},
                    )
                    self.assertEqual(duplicate.status_code, 409)
                    detail = duplicate.json()["detail"]
                    self.assertEqual(detail["message"], "L’analyse du CV est déjà en cours.")
                    self.assertTrue(detail["onboarding"]["processing"])

                    release.set()
                    completed = pending.result(timeout=2)

            self.assertEqual(completed.status_code, 200)
            final_status = client.get("/api/onboarding").json()
            self.assertFalse(final_status["needed"])
            self.assertFalse(final_status["processing"])
            self.assertEqual(final_status["job"]["status"], "done")

    def test_login_pose_un_cookie_signe_et_donne_acces(self):
        with TestClient(app) as client:
            response = client.post(
                "/login", data={"identifier": "admin", "password": "integration-password",
                                "next": "/api/history"},
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
                "/login", data={"identifier": "admin", "password": "wrong-password", "next": "/"},
                follow_redirects=False,
            )
            self.assertEqual(response.status_code, 401)
            self.assertNotIn("jev_session=", response.headers.get("set-cookie", ""))

    def test_connexions_reussies_ne_declenchent_pas_la_limite(self):
        with TestClient(app) as client:
            for _ in range(8):
                response = client.post(
                    "/login", data={"identifier": "admin", "password": "integration-password",
                                    "next": "/"},
                    follow_redirects=False,
                )
                self.assertEqual(response.status_code, 303)

    def test_seuls_les_echecs_de_connexion_sont_limites(self):
        with TestClient(app) as client:
            for _ in range(5):
                response = client.post(
                    "/login", data={"identifier": "admin", "password": "wrong-password",
                                    "next": "/"},
                    follow_redirects=False,
                )
                self.assertEqual(response.status_code, 401)
            response = client.post(
                "/login", data={"identifier": "admin", "password": "wrong-password",
                                "next": "/"},
                follow_redirects=False,
            )
            self.assertEqual(response.status_code, 429)

    def test_non_admin_ne_revient_pas_sur_la_page_admin_apres_login(self):
        accounts.create_user("member", "member-password-123", user_id="member-user")
        with TestClient(app) as client:
            response = client.post(
                "/login", data={"identifier": "member", "password": "member-password-123",
                                "next": "/admin"},
                follow_redirects=False,
            )
            self.assertEqual(response.status_code, 303)
            self.assertEqual(response.headers["location"], "/")

    def test_logout_sans_origin_supprime_la_session(self):
        with TestClient(app) as client:
            login = client.post(
                "/login", data={"identifier": "admin", "password": "integration-password",
                                "next": "/"},
                follow_redirects=False,
            )
            self.assertEqual(login.status_code, 303)
            self.assertEqual(client.get("/api/history").status_code, 200)
            logout = client.post("/logout", follow_redirects=False)
            self.assertEqual(logout.status_code, 303)
            self.assertEqual(logout.headers["location"], "/login")
            self.assertIn("jev_session=", logout.headers.get("set-cookie", ""))
            self.assertEqual(client.get("/api/history").status_code, 401)


if __name__ == "__main__":
    unittest.main(verbosity=2)
