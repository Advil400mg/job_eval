"""Offline tests for authentication, signed sessions and rate limiting."""

from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config, security  # noqa: E402


class SecurityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.saved = {name: os.environ.get(name) for name in (
            "JEV_CONFIG", "JEV_DATA_DIR", "JEV_AUTH_PASSWORD", "JEV_SESSION_SECRET",
        )}
        os.environ["JEV_CONFIG"] = str(Path(self.tmp.name) / "missing.toml")
        os.environ["JEV_DATA_DIR"] = self.tmp.name
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

    def test_session_signee_detecte_la_falsification(self):
        token = security.create_session()
        self.assertTrue(security.valid_session(token))
        self.assertFalse(security.valid_session(token[:-1] + ("A" if token[-1] != "A" else "B")))
        self.assertFalse(security.valid_session(None))

    def test_expiration_est_verifiee(self):
        with mock.patch.object(time, "time", return_value=1_000):
            token = security.create_session()
        with mock.patch.object(time, "time", return_value=1_000 + 13 * 3600):
            self.assertFalse(security.valid_session(token))

    def test_mot_de_passe_compare_en_temps_constant(self):
        self.assertTrue(security.verify_password("correct-horse-battery"))
        self.assertFalse(security.verify_password("incorrect"))

    def test_configuration_refuse_les_secrets_trop_courts(self):
        os.environ["JEV_AUTH_PASSWORD"] = "court"
        with self.assertRaises(RuntimeError):
            security.validate_configuration()
        os.environ["JEV_AUTH_PASSWORD"] = "correct-horse-battery"
        os.environ["JEV_SESSION_SECRET"] = "court"
        with self.assertRaises(RuntimeError):
            security.validate_configuration()

    def test_safe_next_refuse_les_redirections_externes(self):
        self.assertEqual(security.safe_next("/offers?page=2"), "/offers?page=2")
        self.assertEqual(security.safe_next("https://evil.test"), "/")
        self.assertEqual(security.safe_next("//evil.test"), "/")

    def test_rate_limit_retourne_429(self):
        limiter = security.RateLimiter()
        limiter.enforce("client", "login", 2, 60)
        limiter.enforce("client", "login", 2, 60)
        with self.assertRaises(Exception) as caught:
            limiter.enforce("client", "login", 2, 60)
        self.assertEqual(getattr(caught.exception, "status_code", None), 429)


if __name__ == "__main__":
    unittest.main(verbosity=2)
