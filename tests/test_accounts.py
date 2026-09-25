"""Account, Argon2id and invitation tests for v2.3."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from app import accounts, config, store


class AccountsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.previous_db = store.DB_PATH
        self.saved = {key: os.environ.get(key) for key in ("JEV_CONFIG", "JEV_DATA_DIR")}
        os.environ["JEV_CONFIG"] = str(self.root / "missing.toml")
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

    def test_password_is_argon2id_and_authentication_accepts_email_or_username(self):
        user = accounts.create_user("Alice", "correct-horse-battery", "Alice@Example.test")
        with store._LOCK, store._connect() as conn:
            encoded = conn.execute("SELECT password_hash FROM users WHERE id = ?", (user["id"],)).fetchone()[0]
        self.assertTrue(encoded.startswith("$argon2id$"))
        self.assertEqual(accounts.authenticate("alice", "correct-horse-battery")["id"], user["id"])
        self.assertEqual(accounts.authenticate("ALICE@example.test", "correct-horse-battery")["id"], user["id"])
        self.assertIsNone(accounts.authenticate("alice", "wrong-password"))

    def test_invitation_is_one_time_hashed_and_can_be_revoked(self):
        admin = accounts.create_user("admin", "correct-horse-battery", role="admin")
        invitation = accounts.create_invitation(admin["id"], "bob@example.test", 72)
        with store._LOCK, store._connect() as conn:
            row = conn.execute("SELECT token_hash FROM invitations WHERE id = ?", (invitation["id"],)).fetchone()
        self.assertNotEqual(row["token_hash"], invitation["token"])
        bob = accounts.register_with_invitation(
            invitation["token"], "bob", "another-correct-password", "bob@example.test",
        )
        self.assertEqual(bob["email"], "bob@example.test")
        with self.assertRaises(accounts.AccountError):
            accounts.register_with_invitation(
                invitation["token"], "other", "another-correct-password", "bob@example.test",
            )
        second = accounts.create_invitation(admin["id"])
        self.assertTrue(accounts.revoke_invitation(second["id"]))
        with self.assertRaises(accounts.AccountError):
            accounts.register_with_invitation(second["token"], "third", "another-correct-password")

    def test_account_conflict_does_not_consume_invitation(self):
        admin = accounts.create_user("admin", "correct-horse-battery", role="admin")
        accounts.create_user("taken", "first-password-123", email="taken@example.test")
        invitation = accounts.create_invitation(admin["id"], "new@example.test")
        with self.assertRaises(accounts.AccountConflict):
            accounts.register_with_invitation(
                invitation["token"], "taken", "second-password-123", "new@example.test",
            )
        status = accounts.invitation_status(invitation["token"])
        assert status is not None
        self.assertTrue(status["valid"])

    def test_disabling_user_invalidates_sessions_version(self):
        admin = accounts.create_user("admin", "correct-horse-battery", role="admin")
        user = accounts.create_user("user", "another-correct-password")
        before = int(user["session_version"])
        disabled = accounts.set_user_active(user["id"], False, admin["id"])
        self.assertFalse(disabled["active"])
        self.assertGreater(int(disabled["session_version"]), before)
        self.assertIsNone(accounts.authenticate("user", "another-correct-password"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
