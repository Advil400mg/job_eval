"""Tests for multi-user authentication v2.3 — sessions, middleware, CSRF, rate limiter."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import starlette.requests as _requests
from app import accounts, config, security, store  # noqa: E402


class SecurityTests(unittest.TestCase):
    """Unit tests for session token, rate limiter, cookie helpers & CSRF."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.saved = {
            name: os.environ.get(name)
            for name in (
                "JEV_CONFIG",
                "JEV_DATA_DIR",
                "JEV_AUTH_PASSWORD",
                "JEV_SESSION_SECRET",
            )
        }
        os.environ["JEV_CONFIG"] = str(self.root / "missing.toml")
        os.environ["JEV_DATA_DIR"] = str(self.root)
        os.environ["JEV_AUTH_PASSWORD"] = "correct-horse-battery"
        os.environ["JEV_SESSION_SECRET"] = "s" * 40
        config.reset_cache()
        security._signing_key.cache_clear()
        security.LIMITER = security.RateLimiter()

    def tearDown(self):
        for name, value in self.saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        config.reset_cache()
        security._signing_key.cache_clear()
        self.tmp.cleanup()

    # ── Legacy session ───────────────────────────────────────────

    def test_session_signee_detecte_la_falsification(self):
        token = security.create_session()
        self.assertTrue(security.valid_session(token))
        # Mutate the base64 payload body (append a char before the dot)
        dot = token.index(".")
        tampered = token[: dot - 1] + ("A" if token[dot - 1] != "A" else "B") + token[dot:]
        self.assertFalse(security.valid_session(tampered))
        self.assertFalse(security.valid_session(None))

    def test_expiration_est_verifiee(self):
        with mock.patch.object(time, "time", return_value=1_000):
            token = security.create_session()
        with mock.patch.object(time, "time", return_value=1_000 + 13 * 3600):
            self.assertFalse(security.valid_session(token))

    def test_mot_de_passe_compare_en_temps_constant(self):
        self.assertTrue(security.verify_password("correct-horse-battery"))
        self.assertFalse(security.verify_password("incorrect"))

    def test_cookie_session_est_http_only_et_same_site_strict(self):
        response = mock.Mock()
        security.set_session_cookie(response)
        kwargs = response.set_cookie.call_args.kwargs
        self.assertTrue(kwargs["httponly"])
        self.assertEqual(kwargs["samesite"], "strict")

    # ── Multi-user session ───────────────────────────────────────

    def test_create_user_session(self):
        """A multi-user session token can be created."""
        token = security.create_user_session("user-abc", 2)
        self.assertIsNotNone(token)
        self.assertIn(".", token)

    def test_user_session_rejects_unknown_user(self):
        """valid_session returns False when the referenced user doesn't exist."""
        token = security.create_user_session("no-such-user", 1)
        self.assertFalse(security.valid_session(token))

    def test_user_session_rejects_wrong_version(self):
        """valid_session returns False when session_version doesn't match DB."""
        token = security.create_user_session("no-such-user", 99)
        self.assertFalse(security.valid_session(token))

    def test_user_session_tamper_detection(self):
        """Modifying the payload invalidates the HMAC signature."""
        token = security.create_user_session("user-id", 1)
        self.assertIn(".", token)
        dot = token.index(".")
        tampered = token[: dot - 1] + ("A" if token[dot - 1] != "A" else "B") + token[dot:]
        self.assertFalse(security.valid_session(tampered))

    # ── load_session ─────────────────────────────────────────────

    def test_load_session_legacy_returns_virtual_admin(self):
        token = security.create_session()
        user = security.load_session(token)
        self.assertIsNotNone(user)
        self.assertEqual(user["id"], "legacy-admin")
        self.assertEqual(user["role"], "admin")

    def test_load_session_legacy_none_when_auth_disabled(self):
        os.environ.pop("JEV_AUTH_PASSWORD", None)
        os.environ.pop("JEV_SESSION_SECRET", None)
        config.reset_cache()
        security._signing_key.cache_clear()
        token = security.create_session()
        self.assertIn(".", token)
        user = security.load_session(token)
        self.assertIsNone(user)

    def test_load_session_returns_none_for_invalid(self):
        self.assertIsNone(security.load_session(None))
        self.assertIsNone(security.load_session("garbage"))
        self.assertIsNone(security.load_session("abc.def"))

    # ── set_user_session_cookie ──────────────────────────────────

    def test_user_session_cookie_has_correct_attributes(self):
        response = mock.Mock()
        security.set_user_session_cookie(response, "user-id", 1)
        name = response.set_cookie.call_args[0][0]
        kwargs = response.set_cookie.call_args.kwargs
        self.assertEqual(name, security.COOKIE_NAME)
        self.assertTrue(kwargs["httponly"])
        self.assertEqual(kwargs["samesite"], "strict")
        self.assertEqual(kwargs["path"], "/")
        token = response.set_cookie.call_args[0][1]
        self.assertIn(".", token)

    # ── Configuration ────────────────────────────────────────────

    def test_configuration_refuse_les_secrets_trop_courts(self):
        os.environ["JEV_AUTH_PASSWORD"] = "court"
        with self.assertRaises(RuntimeError):
            security.validate_configuration()
        os.environ["JEV_AUTH_PASSWORD"] = "correct-horse-battery"
        os.environ["JEV_SESSION_SECRET"] = "court"
        with self.assertRaises(RuntimeError):
            security.validate_configuration()

    def test_validate_configuration_accepts_no_secret_multi_user(self):
        os.environ.pop("JEV_AUTH_PASSWORD", None)
        os.environ.pop("JEV_SESSION_SECRET", None)
        config.reset_cache()
        security._signing_key.cache_clear()
        security.validate_configuration()

    # ── safe_next ────────────────────────────────────────────────

    def test_safe_next_refuse_les_redirections_externes(self):
        self.assertEqual(security.safe_next("/offers?page=2"), "/offers?page=2")
        self.assertEqual(security.safe_next("https://evil.test"), "/")
        self.assertEqual(security.safe_next("//evil.test"), "/")

    # ── Rate limiter ─────────────────────────────────────────────

    def test_rate_limit_retourne_429(self):
        limiter = security.RateLimiter()
        limiter.enforce("client", "login", 2, 60)
        limiter.enforce("client", "login", 2, 60)
        with self.assertRaises(Exception) as caught:
            limiter.enforce("client", "login", 2, 60)
        self.assertEqual(getattr(caught.exception, "status_code", None), 429)

    def test_rate_limit_allows_different_actions(self):
        limiter = security.RateLimiter()
        limiter.enforce("client", "login", 1, 60)
        limiter.enforce("client", "evaluate", 1, 60)
        with self.assertRaises(Exception) as caught:
            limiter.enforce("client", "evaluate", 1, 60)
        self.assertEqual(getattr(caught.exception, "status_code", None), 429)

    def test_rate_limit_window_expires(self):
        limiter = security.RateLimiter()
        now = time.monotonic()
        with mock.patch.object(time, "monotonic", return_value=now):
            limiter.enforce("c", "a", 1, 10)
        with mock.patch.object(time, "monotonic", return_value=now + 11):
            limiter.enforce("c", "a", 1, 10)

    # ── CSRF helper ──────────────────────────────────────────────

    def _fake_request(self, method="GET", origin=None, referer=None,
                      host="example.com", port=None, scheme="http"):
        headers = {}
        if origin:
            headers["origin"] = origin
        if referer:
            headers["referer"] = referer
        req = mock.Mock(spec=_requests.Request)
        req.url.hostname = host
        req.url.port = port
        req.url.scheme = scheme
        req.headers = headers
        return req

    def test_csrf_same_origin_passes(self):
        req = self._fake_request(method="POST", origin="http://example.com")
        self.assertTrue(security._is_same_origin(req))

    def test_csrf_different_origin_fails(self):
        req = self._fake_request(method="POST", origin="https://evil.com")
        self.assertFalse(security._is_same_origin(req))

    def test_csrf_no_origin_checks_referer(self):
        req = self._fake_request(method="POST", referer="http://example.com/login")
        self.assertTrue(security._is_same_origin(req))

    def test_csrf_cross_origin_referer_fails(self):
        req = self._fake_request(method="POST", referer="https://evil.com/page")
        self.assertFalse(security._is_same_origin(req))

    def test_csrf_no_origin_no_referer_fails_on_mutation(self):
        req = self._fake_request(method="POST")
        self.assertFalse(security._is_same_origin(req))

    def test_csrf_get_skipped(self):
        req = self._fake_request(method="GET", origin="https://evil.com")
        self.assertFalse(security._is_same_origin(req))

    def test_csrf_origin_port_must_match(self):
        req = self._fake_request(
            method="POST", origin="http://example.com:8080",
            host="example.com", port=8080,
        )
        self.assertTrue(security._is_same_origin(req))

    # ── client_ip ────────────────────────────────────────────────

    def test_client_ip_trusts_x_forwarded_for(self):
        req = mock.Mock(spec=_requests.Request)
        req.headers = {"x-forwarded-for": "10.0.0.1, 10.0.0.2"}
        req.client.host = "127.0.0.1"
        with mock.patch.object(config, "settings", return_value={
            "security": {"trust_proxy": True},
        }):
            self.assertEqual(security.client_ip(req), "10.0.0.1")

    def test_client_ip_falls_back_to_remote(self):
        req = mock.Mock(spec=_requests.Request)
        req.headers = {}
        req.client.host = "203.0.113.1"
        with mock.patch.object(config, "settings", return_value={
            "security": {"trust_proxy": False},
        }):
            self.assertEqual(security.client_ip(req), "203.0.113.1")

    # ── auth_enabled ─────────────────────────────────────────────

    def test_auth_enabled_with_password(self):
        os.environ["JEV_AUTH_PASSWORD"] = "valid-password-long"
        config.reset_cache()
        self.assertTrue(security.auth_enabled())

    def test_auth_disabled_no_password_no_users(self):
        os.environ.pop("JEV_AUTH_PASSWORD", None)
        os.environ.pop("JEV_SESSION_SECRET", None)
        config.reset_cache()
        security._signing_key.cache_clear()
        with mock.patch.object(accounts, "active_user_count", return_value=0):
            self.assertTrue(security.auth_enabled())

    def test_auth_enabled_with_users(self):
        os.environ.pop("JEV_AUTH_PASSWORD", None)
        config.reset_cache()
        with mock.patch.object(accounts, "active_user_count", return_value=2):
            self.assertTrue(security.auth_enabled())

    # ── Public paths ─────────────────────────────────────────────

    def test_public_routes_listed(self):
        for route in ("/healthz", "/login", "/setup-admin", "/register"):
            self.assertIn(route, security._PUBLIC_PATHS)
        self.assertTrue(any("/static/" in p for p in security._PUBLIC_PREFIXES))

    # ── enforce_rate convenience ─────────────────────────────────

    def test_enforce_rate_wraps_limiter(self):
        req = mock.Mock(spec=_requests.Request)
        req.headers = {}
        req.client.host = "1.2.3.4"
        with mock.patch.object(config, "settings", return_value={
            "security": {"trust_proxy": False},
        }):
            security.enforce_rate(req, "test", 5, 60)
        for _ in range(4):
            security.LIMITER.enforce("1.2.3.4", "test", 5, 60)
        with self.assertRaises(Exception) as caught:
            security.LIMITER.enforce("1.2.3.4", "test", 5, 60)
        self.assertEqual(getattr(caught.exception, "status_code", None), 429)


class AuthMiddlewareTests(unittest.TestCase):
    """Integration tests for AuthMiddleware using FastAPI TestClient."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.saved = {
            name: os.environ.get(name)
            for name in (
                "JEV_CONFIG", "JEV_DATA_DIR",
                "JEV_AUTH_PASSWORD", "JEV_SESSION_SECRET",
            )
        }
        os.environ["JEV_CONFIG"] = str(self.root / "missing.toml")
        os.environ["JEV_AUTH_PASSWORD"] = "correct-horse-battery"
        os.environ["JEV_SESSION_SECRET"] = "s" * 40
        # Override DATA_DIR so store.DB_PATH resolves inside tmp
        os.environ["JEV_DATA_DIR"] = str(self.root)
        config.reset_cache()
        security._signing_key.cache_clear()
        security.LIMITER = security.RateLimiter()
        self.previous_db = store.DB_PATH
        store.DB_PATH = str(self.root / "jev.db")
        accounts.create_user(
            "admin", "correct-horse-battery", "admin@example.test",
            role="admin", user_id="legacy-admin",
        )

        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from starlette.requests import Request
        self.app = FastAPI()
        self.app.add_middleware(security.AuthMiddleware)

        @self.app.get("/api/test")
        async def api_test(request: _requests.Request):
            user = getattr(request.state, "user", None)
            return {"ok": True, "user_id": (user or {}).get("id")}

        @self.app.post("/api/test")
        async def api_test_post(request: _requests.Request):
            user = getattr(request.state, "user", None)
            return {"ok": True, "user_id": (user or {}).get("id")}

        @self.app.get("/healthz")
        async def healthz():
            return {"ok": True}

        @self.app.get("/login")
        async def login_get():
            return {"page": "login"}

        @self.app.post("/login")
        async def login_post():
            return {"page": "login"}

        @self.app.get("/setup-admin")
        async def setup_admin():
            return {"page": "setup-admin"}

        @self.app.get("/register")
        async def register():
            return {"page": "register"}

        @self.app.get("/protected-page")
        async def protected_page(request: _requests.Request):
            user = getattr(request.state, "user", None)
            return {"ok": True, "user_id": (user or {}).get("id")}

        self.client = TestClient(self.app)

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

    # ── Public routes accessible without auth ────────────────────

    def test_healthz_public(self):
        resp = self.client.get("/healthz")
        self.assertEqual(resp.status_code, 200)

    def test_login_public(self):
        resp = self.client.get("/login")
        self.assertEqual(resp.status_code, 200)

    def test_setup_admin_public(self):
        resp = self.client.get("/setup-admin")
        self.assertEqual(resp.status_code, 200)

    def test_register_public(self):
        resp = self.client.get("/register")
        self.assertEqual(resp.status_code, 200)

    # ── Protected routes require auth ────────────────────────────

    def test_api_returns_401_when_unauthenticated(self):
        with mock.patch.object(security, "auth_enabled", return_value=True):
            resp = self.client.get("/api/test")
        self.assertEqual(resp.status_code, 401)

    def test_page_redirects_to_login_when_unauthenticated(self):
        with mock.patch.object(security, "auth_enabled", return_value=True):
            resp = self.client.get("/protected-page", follow_redirects=False)
        self.assertEqual(resp.status_code, 303)
        self.assertIn("/login", resp.headers.get("location", ""))

    # ── Authenticated access ─────────────────────────────────────

    def test_api_authenticated_with_legacy_session(self):
        with mock.patch.object(security, "auth_enabled", return_value=True):
            token = security.create_session()
            resp = self.client.get(
                "/api/test",
                cookies={security.COOKIE_NAME: token},
                headers={"Origin": "http://testserver"},
            )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["user_id"], "legacy-admin")

    def test_page_authenticated_with_legacy_session(self):
        with mock.patch.object(security, "auth_enabled", return_value=True):
            token = security.create_session()
            resp = self.client.get(
                "/protected-page",
                cookies={security.COOKIE_NAME: token},
            )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["user_id"], "legacy-admin")

    # ── request.state.user ───────────────────────────────────────

    def test_state_user_is_set_on_authenticated_request(self):
        with mock.patch.object(security, "auth_enabled", return_value=True):
            token = security.create_session()
            resp = self.client.get(
                "/api/test",
                cookies={security.COOKIE_NAME: token},
                headers={"Origin": "http://testserver"},
            )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["user_id"], "legacy-admin")

    def test_state_user_is_none_when_unauthenticated(self):
        resp = self.client.get("/healthz")
        self.assertEqual(resp.status_code, 200)

    # ── CSRF for mutations ───────────────────────────────────────

    def test_api_post_without_origin_referer_fails_when_authd(self):
        with mock.patch.object(security, "auth_enabled", return_value=True):
            token = security.create_session()
            resp = self.client.post(
                "/api/test",
                cookies={security.COOKIE_NAME: token},
            )
        self.assertEqual(resp.status_code, 403)
        self.assertIn("origine non vérifiée", resp.text)

    def test_api_post_with_valid_origin_succeeds_when_authd(self):
        with mock.patch.object(security, "auth_enabled", return_value=True):
            token = security.create_session()
            resp = self.client.post(
                "/api/test",
                cookies={security.COOKIE_NAME: token},
                headers={"Origin": "http://testserver"},
            )
        self.assertEqual(resp.status_code, 200)

    def test_api_post_with_wrong_origin_fails_when_authd(self):
        with mock.patch.object(security, "auth_enabled", return_value=True):
            token = security.create_session()
            resp = self.client.post(
                "/api/test",
                cookies={security.COOKIE_NAME: token},
                headers={"Origin": "https://evil.com"},
            )
        self.assertEqual(resp.status_code, 403)

    def test_api_post_with_valid_referer_succeeds_when_authd(self):
        with mock.patch.object(security, "auth_enabled", return_value=True):
            token = security.create_session()
            resp = self.client.post(
                "/api/test",
                cookies={security.COOKIE_NAME: token},
                headers={"Referer": "http://testserver/some-page"},
            )
        self.assertEqual(resp.status_code, 200)

    # ── Auth disabled (no password, no users) ────────────────────

    def test_all_routes_require_auth_when_accounts_exist(self):
        resp = self.client.get("/api/test")
        self.assertEqual(resp.status_code, 401)

    def test_mutation_requires_auth(self):
        resp = self.client.post("/api/test")
        self.assertEqual(resp.status_code, 401)

    # ── Public routes bypass CSRF ────────────────────────────────

    def test_public_get_no_auth(self):
        resp = self.client.get("/login")
        self.assertEqual(resp.status_code, 200)

    def test_public_routes_not_csrf_checked(self):
        with mock.patch.object(security, "auth_enabled", return_value=True):
            token = security.create_session()
            resp = self.client.post(
                "/login",
                cookies={security.COOKIE_NAME: token},
                headers={"Origin": "http://testserver"},
            )
        self.assertEqual(resp.status_code, 200)

    # ── Multi-user session tests (with mocked DB user) ───────────

    def test_create_and_validate_multi_user_session(self):
        """Full round-trip: user session created, load_session returns user."""
        fake_user = {"id": "user-abc", "session_version": 2, "role": "user"}
        with mock.patch.object(security, "auth_enabled", return_value=True):
            with mock.patch.object(accounts, "get_user", return_value=fake_user):
                token = security.create_user_session("user-abc", 2)
                self.assertTrue(security.valid_session(token))
                loaded = security.load_session(token)
                self.assertEqual(loaded["id"], "user-abc")

    def test_session_invalidated_by_version_bump(self):
        """Bumped session_version invalidates existing tokens."""
        fake_user = {"id": "user-abc", "session_version": 2, "role": "user"}
        with mock.patch.object(security, "auth_enabled", return_value=True):
            with mock.patch.object(accounts, "get_user", return_value=fake_user):
                token = security.create_user_session("user-abc", 1)  # old version
                self.assertFalse(security.valid_session(token))
                self.assertIsNone(security.load_session(token))

    def test_authenticated_mutation_blocked_when_no_csrf_headers(self):
        """Even with a valid session, POST without Origin/Referer is blocked."""
        with mock.patch.object(security, "auth_enabled", return_value=True):
            token = security.create_session()
            resp = self.client.post(
                "/api/test",
                cookies={security.COOKIE_NAME: token},
            )
        self.assertEqual(resp.status_code, 403)

    def test_session_version_zero_is_valid(self):
        """session_version=0 should be accepted (first session)."""
        fake_user = {"id": "user-zero", "session_version": 0, "role": "user"}
        with mock.patch.object(security, "auth_enabled", return_value=True):
            with mock.patch.object(accounts, "get_user", return_value=fake_user):
                token = security.create_user_session("user-zero", 0)
                self.assertTrue(security.valid_session(token))


if __name__ == "__main__":
    unittest.main(verbosity=2)