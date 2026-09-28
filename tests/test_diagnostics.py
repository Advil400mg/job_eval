"""Tests for administrator diagnostics."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from app import accounts, backup, config, diagnostics, store


class DiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.previous_db = store.DB_PATH
        self.saved = {name: os.environ.get(name) for name in ("JEV_CONFIG", "JEV_DATA_DIR")}
        os.environ["JEV_CONFIG"] = str(self.root / "missing.toml")
        os.environ["JEV_DATA_DIR"] = str(self.root)
        config.reset_cache()
        diagnostics.reset_cache()
        store.DB_PATH = str(self.root / "jev.db")
        self.admin = accounts.create_user("diag-admin", "correct-horse-battery", role="admin")
        config.user_dir(self.admin["id"]).mkdir(parents=True)

    def tearDown(self):
        store.DB_PATH = self.previous_db
        for name, value in self.saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        config.reset_cache()
        diagnostics.reset_cache()
        self.tmp.cleanup()

    def test_collect_reports_schema_storage_jobs_and_backups(self):
        run_id = store.create_run(["https://jobs.test/diag"], self.admin["id"])
        store.finish_run(run_id, "failed", "test")
        created = backup.create_backup("scheduled")

        payload = diagnostics.collect(force=True)

        self.assertEqual(payload["app"]["schema_version"], 8)
        self.assertEqual(payload["database"]["quick_check"], "ok")
        self.assertEqual(payload["users"], {"total": 1, "active": 1})
        self.assertEqual(payload["jobs"]["runs"]["failed"], 1)
        self.assertEqual(payload["backups"]["latest_scheduled"]["name"], created["name"])
        self.assertFalse(payload["backups"]["scheduled_stale"])
        self.assertEqual(payload["storage"]["missing_user_directories"], [])
        self.assertEqual(payload["status"], "warning")

    def test_collect_detects_missing_orphan_and_pending_directories(self):
        config.user_dir(self.admin["id"]).rmdir()
        users = self.root / "users"
        (users / "orphan").mkdir(parents=True)
        (users / ".deleting-old").mkdir()

        payload = diagnostics.collect(force=True)

        self.assertEqual(payload["storage"]["missing_user_directories"], [self.admin["id"]])
        self.assertEqual(payload["storage"]["orphan_user_directories"], ["orphan"])
        self.assertEqual(payload["storage"]["pending_deletions"], [".deleting-old"])
        storage_check = next(item for item in payload["checks"] if item["id"] == "storage")
        self.assertEqual(storage_check["status"], "warning")

    def test_status_counts_rejects_unknown_table(self):
        with store._LOCK, store._connect() as connection:
            with self.assertRaises(ValueError):
                diagnostics._status_counts(connection, "users; DROP TABLE users")

    def test_collect_uses_cache_until_forced(self):
        first = diagnostics.collect(force=True)
        accounts.create_user("second", "correct-horse-battery")
        cached = diagnostics.collect()
        refreshed = diagnostics.collect(force=True)
        self.assertEqual(cached["users"]["total"], first["users"]["total"])
        self.assertEqual(refreshed["users"]["total"], first["users"]["total"] + 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
