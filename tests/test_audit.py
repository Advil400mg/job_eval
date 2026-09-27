"""Tests for the persistent privacy-conscious audit log."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from app import accounts, audit, config, store


class AuditLog(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.previous_db = store.DB_PATH
        self.previous_data = os.environ.get("JEV_DATA_DIR")
        store.DB_PATH = str(Path(self.tmp.name) / "audit.db")
        os.environ["JEV_DATA_DIR"] = self.tmp.name
        config.reset_cache()
        self.user = accounts.create_user("auditor", "correct-horse-battery", role="admin")

    def tearDown(self):
        store.DB_PATH = self.previous_db
        if self.previous_data is None:
            os.environ.pop("JEV_DATA_DIR", None)
        else:
            os.environ["JEV_DATA_DIR"] = self.previous_data
        config.reset_cache()
        self.tmp.cleanup()

    def test_record_list_filters_and_metadata_allowlist(self):
        event_id = audit.record(
            "auth.login_succeeded", actor_id=self.user["id"], subject_type="user",
            subject_id=self.user["id"], metadata={"role": "admin", "password": "secret"},
        )
        audit.record("auth.login_failed", success=False,
                     metadata={"fingerprint": "abc", "identifier": "hidden"})

        page = audit.list_events(limit=1)
        self.assertEqual(page["total"], 2)
        self.assertEqual(page["limit"], 1)
        failed = audit.list_events(event_type="auth.login_failed", success=False)
        self.assertEqual(failed["total"], 1)
        self.assertEqual(failed["events"][0]["metadata"], {"fingerprint": "abc"})
        succeeded = audit.list_events(actor_id=self.user["id"], success=True)
        self.assertEqual(succeeded["events"][0]["id"], event_id)
        self.assertEqual(succeeded["events"][0]["actor_username"], "auditor")
        self.assertEqual(succeeded["events"][0]["metadata"], {"role": "admin"})

    def test_delete_user_preserves_audit_actor_as_null(self):
        audit.record("user.changed", actor_id=self.user["id"], subject_type="user",
                     subject_id=self.user["id"], metadata={"changed": ["active"]})
        with store._LOCK, store._connect() as conn:
            conn.execute("DELETE FROM users WHERE id = ?", (self.user["id"],))
        event = audit.list_events()["events"][0]
        self.assertIsNone(event["actor_user_id"])
        self.assertEqual(event["subject_id"], self.user["id"])

    def test_prune_removes_only_expired_events(self):
        old_id = audit.record("backup.created", metadata={"kind": "manual"})
        recent_id = audit.record("backup.verified", metadata={"backup_name": "recent.zip"})
        with store._LOCK, store._connect() as conn:
            conn.execute("UPDATE audit_events SET created_at = '2020-01-01T00:00:00' WHERE id = ?",
                         (old_id,))
        self.assertEqual(audit.prune(30), 1)
        self.assertEqual([item["id"] for item in audit.list_events()["events"]], [recent_id])

    def test_rejects_invalid_event_and_subject_types(self):
        with self.assertRaises(audit.AuditError):
            audit.record("INVALID")
        with self.assertRaises(audit.AuditError):
            audit.record("valid.event", subject_type="Not valid")


if __name__ == "__main__":
    unittest.main(verbosity=2)
