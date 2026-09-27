"""Account, Argon2id and invitation tests for v2.3."""

from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

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

    def test_list_users_regroupe_les_administrateurs(self):
        accounts.create_user("z-user", "correct-horse-battery")
        accounts.create_user("b-admin", "another-correct-password", role="admin")
        accounts.create_user("a-user", "third-correct-password")
        accounts.create_user("a-admin", "fourth-correct-password", role="admin")
        users = accounts.list_users()
        self.assertEqual(
            [(user["role"], user["username"]) for user in users],
            [
                ("admin", "a-admin"), ("admin", "b-admin"),
                ("user", "a-user"), ("user", "z-user"),
            ],
        )

    def test_delete_user_purges_owned_database_rows_and_files(self):
        admin = accounts.create_user("admin", "correct-horse-battery", role="admin")
        user = accounts.create_user("member", "another-correct-password")
        user_dir = config.user_dir(user["id"])
        (user_dir / "cv" / "nested").mkdir(parents=True)
        (user_dir / "PROFILE.json").write_text("{}", encoding="utf-8")
        (user_dir / "cv" / "nested" / "resume.pdf").write_bytes(b"%PDF-test")
        with store._LOCK, store._connect() as conn:
            conn.execute(
                "INSERT INTO runs (id, user_id, created_at, urls, status, updated_at) "
                "VALUES ('run-member', ?, '2026-09-27', '[]', 'done', '2026-09-27')",
                (user["id"],),
            )
            conn.execute(
                "INSERT INTO results (run_id, url, created_at, status, payload) "
                "VALUES ('run-member', 'https://jobs.test/member', '2026-09-27', 'ok', '{}')"
            )
            conn.execute(
                "INSERT INTO cv_jobs (id, user_id, url, created_at, status, updated_at) "
                "VALUES ('cv-member', ?, 'https://jobs.test/member', '2026-09-27', 'done', "
                "'2026-09-27')", (user["id"],),
            )
            conn.execute(
                "INSERT INTO onboarding_jobs (user_id, status, created_at, started_at, updated_at) "
                "VALUES (?, 'done', '2026-09-27', '2026-09-27', '2026-09-27')",
                (user["id"],),
            )
            conn.execute(
                "INSERT INTO profile_versions (id, user_id, created_at, revision, source, payload) "
                "VALUES ('profile-member', ?, '2026-09-27', 'rev-member', 'test', '{}')",
                (user["id"],),
            )
            conn.execute(
                "INSERT INTO applications (id, user_id, normalized_url, url, status, created_at, "
                "updated_at) VALUES ('app-member', ?, 'https://jobs.test/member', "
                "'https://jobs.test/member', 'to_review', '2026-09-27', '2026-09-27')",
                (user["id"],),
            )
            conn.execute(
                "INSERT INTO application_events (application_id, created_at, event_type) "
                "VALUES ('app-member', '2026-09-27', 'created')"
            )
        member_invitation = accounts.create_invitation(user["id"])
        admin_invitation = accounts.create_invitation(admin["id"])

        deleted = accounts.delete_user(user["id"], admin["id"], "member")

        self.assertEqual(deleted["id"], user["id"])
        self.assertFalse(user_dir.exists())
        self.assertIsNone(accounts.get_user(user["id"], include_disabled=True))
        self.assertIsNotNone(accounts.get_user(admin["id"], include_disabled=True))
        with store._LOCK, store._connect() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM results WHERE run_id = 'run-member'").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM runs WHERE user_id = ?", (user["id"],)).fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM cv_jobs WHERE user_id = ?", (user["id"],)).fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM onboarding_jobs WHERE user_id = ?", (user["id"],)).fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM profile_versions WHERE user_id = ?", (user["id"],)).fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM applications WHERE user_id = ?", (user["id"],)).fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM application_events WHERE application_id = 'app-member'").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM invitations WHERE id = ?", (member_invitation["id"],)).fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM invitations WHERE id = ?", (admin_invitation["id"],)).fetchone()[0], 1)

    def test_delete_user_refuses_self_wrong_confirmation_and_active_work(self):
        admin = accounts.create_user("admin", "correct-horse-battery", role="admin")
        user = accounts.create_user("member", "another-correct-password")
        user_dir = config.user_dir(user["id"])
        user_dir.mkdir(parents=True)
        with self.assertRaisesRegex(accounts.AccountError, "propre compte"):
            accounts.delete_user(admin["id"], admin["id"], "admin")
        with self.assertRaisesRegex(accounts.AccountError, "confirmation"):
            accounts.delete_user(user["id"], admin["id"], "Member")
        store.create_run(["https://jobs.test/member"], user["id"])
        with self.assertRaisesRegex(accounts.AccountError, "tâche active"):
            accounts.delete_user(user["id"], admin["id"], "member")
        self.assertIsNotNone(accounts.get_user(user["id"], include_disabled=True))
        self.assertTrue(user_dir.exists())

    def test_delete_user_restores_files_and_database_when_transaction_fails(self):
        admin = accounts.create_user("admin", "correct-horse-battery", role="admin")
        user = accounts.create_user("member", "another-correct-password")
        user_dir = config.user_dir(user["id"])
        user_dir.mkdir(parents=True)
        marker = user_dir / "PROFILE.json"
        marker.write_text("{}", encoding="utf-8")
        with store._LOCK, store._connect() as conn:
            conn.execute(
                "CREATE TRIGGER refuse_member_delete BEFORE DELETE ON users "
                "WHEN OLD.id = '" + user["id"] + "' BEGIN SELECT RAISE(ABORT, 'refused'); END"
            )
        with self.assertRaises(sqlite3.IntegrityError):
            accounts.delete_user(user["id"], admin["id"], "member")
        self.assertIsNotNone(accounts.get_user(user["id"], include_disabled=True))
        self.assertTrue(marker.exists())
        self.assertFalse(any(user_dir.parent.glob(f".deleting-{user['id']}-*")))

    def test_delete_user_reports_pending_cleanup_and_retries_it(self):
        admin = accounts.create_user("admin", "correct-horse-battery", role="admin")
        user = accounts.create_user("member", "another-correct-password")
        user_dir = config.user_dir(user["id"])
        user_dir.mkdir(parents=True)
        (user_dir / "PROFILE.json").write_text("{}", encoding="utf-8")
        with self.assertLogs("app.accounts", level="ERROR"), mock.patch(
            "app.accounts._remove_storage_path", side_effect=OSError("denied"),
        ):
            deleted = accounts.delete_user(user["id"], admin["id"], "member")
        self.assertTrue(deleted["cleanup_pending"])
        staged = list(user_dir.parent.glob(f".deleting-{user['id']}-*"))
        self.assertEqual(len(staged), 1)
        recovered = accounts.reconcile_deleted_user_files()
        self.assertEqual(recovered, {"restored": 0, "purged": 1, "failed": 0})
        self.assertFalse(staged[0].exists())

    def test_reconciliation_restores_files_after_precommit_crash(self):
        user = accounts.create_user("member", "another-correct-password")
        user_dir = config.user_dir(user["id"])
        user_dir.mkdir(parents=True)
        marker = user_dir / "PROFILE.json"
        marker.write_text("{}", encoding="utf-8")
        staged = user_dir.parent / f".deleting-{user['id']}-{'a' * 32}"
        os.replace(user_dir, staged)
        recovered = accounts.reconcile_deleted_user_files()
        self.assertEqual(recovered, {"restored": 1, "purged": 0, "failed": 0})
        self.assertTrue(marker.exists())
        self.assertFalse(staged.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
