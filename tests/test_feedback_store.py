"""Scoped, transactional and privacy-aware feedback persistence."""
from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from app import store


class FeedbackStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_db = store.DB_PATH
        store.DB_PATH = str(Path(self.tmp.name) / "feedback.db")
        self.url = "https://jobs.example.test/security"
        self.other = "https://jobs.example.test/other"
        self.run_id = store.create_run([self.url, self.other])
        for url in (self.url, self.other):
            store.save_result(self.run_id, url, "ok", {"url": url, "decision": {"status": "qualified"}})
        with store._LOCK, store._connect() as conn:
            conn.execute(
                "INSERT INTO users (id, username, username_normalized, display_name, "
                "password_hash, role, created_at, updated_at) "
                "VALUES ('other-user', 'other', 'other', 'Other', '', 'user', '2026-01-01', '2026-01-01')"
            )
        self.other_run = store.create_run([self.url], "other-user")
        store.save_result(self.other_run, self.url, "ok", {"url": self.url})

    def tearDown(self):
        store.DB_PATH = self.old_db
        self.tmp.cleanup()

    def test_schema_is_migrated_and_scoped(self):
        with store._LOCK, store._connect() as conn:
            self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 8)
            self.assertIsNotNone(conn.execute(
                "SELECT sql FROM sqlite_master WHERE name = 'evaluation_feedback'"
            ).fetchone())
        self.assertTrue(store.feedback_target_exists(self.run_id, self.url))
        self.assertFalse(store.feedback_target_exists(self.run_id, self.url, "other-user"))
        self.assertIsNone(store.get_evaluation_feedback(self.run_id, self.url))

    def test_put_get_revision_conflict_and_audit_excludes_note(self):
        secret_note = "Texte sensible d'une annonce — ne pas mettre dans l'audit"
        saved = store.put_evaluation_feedback(self.run_id, self.url, "bad_reason", secret_note, 0)
        self.assertEqual(saved["revision"], 1)
        fetched = store.get_evaluation_feedback(self.run_id, self.url)
        assert fetched is not None
        self.assertEqual(fetched["note"], secret_note)
        updated = store.put_evaluation_feedback(self.run_id, self.url, "correct", "Vérifié", 1)
        self.assertEqual(updated["revision"], 2)
        with self.assertRaises(store.FeedbackConflict):
            store.put_evaluation_feedback(self.run_id, self.url, "false_positive", "perdu", 1)
        fetched = store.get_evaluation_feedback(self.run_id, self.url)
        assert fetched is not None
        self.assertEqual(fetched["verdict"], "correct")
        with store._LOCK, store._connect() as conn:
            events = [dict(row) for row in conn.execute(
                "SELECT event_type, metadata FROM audit_events "
                "WHERE event_type = 'evaluation.feedback_saved' ORDER BY created_at"
            )]
        self.assertEqual(len(events), 2)
        self.assertTrue(all(secret_note not in row["metadata"] for row in events))
        self.assertEqual({json.loads(row["metadata"])["status"] for row in events},
                         {"bad_reason", "correct"})

    def test_exact_result_ownership_even_with_same_url_in_another_run(self):
        self.assertIsNone(store.put_evaluation_feedback(
            self.run_id, self.url, "correct", "", 0, "other-user"))
        self.assertIsNone(store.put_evaluation_feedback(
            self.run_id, "https://jobs.example.test/missing", "correct", "", 0))
        store.put_evaluation_feedback(self.run_id, self.url, "false_positive", "my note", 0)
        self.assertIsNone(store.get_evaluation_feedback(self.run_id, self.url, "other-user"))
        self.assertIsNone(store.get_evaluation_feedback(self.other_run, self.url))
        other = store.put_evaluation_feedback(self.other_run, self.url, "correct", "other note", 0,
                                              "other-user")
        self.assertEqual(other["note"], "other note")
        fetched = store.get_evaluation_feedback(self.run_id, self.url)
        assert fetched is not None
        self.assertEqual(fetched["note"], "my note")

    def test_reject_invalid_verdict_and_oversized_note_without_writing(self):
        for verdict, note in (("invented", ""), ("correct", "x" * 2001)):
            with self.subTest(verdict=verdict, note_length=len(note)):
                with self.assertRaises(ValueError):
                    store.put_evaluation_feedback(self.run_id, self.url, verdict, note, 0)
        self.assertIsNone(store.get_evaluation_feedback(self.run_id, self.url))


if __name__ == "__main__":
    unittest.main()
