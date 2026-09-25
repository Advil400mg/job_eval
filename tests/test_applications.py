"""Application tracking persistence tests."""

from __future__ import annotations

import sys
import sqlite3
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import store  # noqa: E402


class Applications(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.previous_db = store.DB_PATH
        store.DB_PATH = str(Path(self.tmp.name) / "jev.db")

    def tearDown(self):
        store.DB_PATH = self.previous_db
        self.tmp.cleanup()

    def add_offer(self, url: str = "https://jobs.test/role?utm_source=mail") -> None:
        run = store.create_run([url])
        store.save_result(run, url, "ok", {
            "url": url, "title": "Security Engineer", "company": "Example",
            "location": "Brussels", "published_at": "2026-09-24", "status": "ok",
            "decision": {"status": "qualified", "hard_gate_failures": []},
            "gate_results": [], "jev": {"global_score": 80, "criteria": []},
        })
        store.finish_run(run)

    def test_migration_v3_vers_v5_ajoute_les_tables_sans_perte(self):
        connection = sqlite3.connect(store.DB_PATH)
        connection.executescript("""
            CREATE TABLE runs (
                id TEXT PRIMARY KEY, created_at TEXT NOT NULL, urls TEXT NOT NULL,
                status TEXT NOT NULL, progress INTEGER NOT NULL DEFAULT 0,
                total INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE results (
                run_id TEXT NOT NULL, url TEXT NOT NULL, created_at TEXT NOT NULL,
                status TEXT NOT NULL, payload TEXT NOT NULL,
                PRIMARY KEY (run_id, url)
            );
            CREATE TABLE cv_jobs (
                id TEXT PRIMARY KEY, url TEXT NOT NULL, created_at TEXT NOT NULL,
                status TEXT NOT NULL, payload TEXT
            );
        """)
        connection.execute("PRAGMA user_version = 3")
        connection.execute(
            "INSERT INTO runs (id, created_at, urls, status, progress, total) "
            "VALUES ('v3-run', '2026-09-24T12:00:00', '[]', 'done', 0, 0)"
        )
        connection.commit()
        connection.close()
        self.assertEqual(store.list_applications()["total"], 0)
        with sqlite3.connect(store.DB_PATH) as migrated:
            self.assertEqual(migrated.execute("PRAGMA user_version").fetchone()[0], 5)
            self.assertEqual(migrated.execute(
                "SELECT status FROM runs WHERE id = 'v3-run'"
            ).fetchone()[0], "done")
            tables = {row[0] for row in migrated.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )}
        self.assertTrue({"profile_versions", "applications", "application_events"} <= tables)

    def test_creation_reutilise_metadonnees_et_deduplique_url(self):
        self.add_offer()
        first = store.create_application("https://jobs.test/role?utm_source=mail")
        duplicate = store.create_application("https://JOBS.test/role/#apply")
        self.assertEqual(first["id"], duplicate["id"])
        self.assertEqual(first["title"], "Security Engineer")
        self.assertEqual(first["company"], "Example")
        self.assertEqual(store.list_applications()["total"], 1)

    def test_mise_a_jour_cree_evenement_et_revision_concurrente(self):
        application = store.create_application("https://jobs.test/role")
        updated = store.update_application(application["id"], {
            "status": "applied", "notes": "Candidature envoyée",
            "applied_at": "2026-09-25", "follow_up_at": "2026-10-02",
        }, expected_revision=1)
        assert updated is not None
        self.assertEqual(updated["revision"], 2)
        self.assertEqual(updated["status"], "applied")
        events = store.application_events(application["id"])
        self.assertEqual(events[0]["event_type"], "status_changed")
        self.assertEqual(events[0]["from_status"], "to_review")
        with self.assertRaises(RuntimeError):
            store.update_application(application["id"], {"notes": "stale"}, expected_revision=1)

    def test_filtres_de_relance_et_statut(self):
        overdue = store.create_application("https://jobs.test/overdue")
        upcoming = store.create_application("https://jobs.test/upcoming")
        store.update_application(overdue["id"], {"follow_up_at": "2026-09-24"}, 1)
        store.update_application(upcoming["id"], {"status": "interview", "follow_up_at": "2026-10-01"}, 1)
        self.assertEqual(store.list_applications(due="overdue")["applications"][0]["id"], overdue["id"])
        self.assertEqual(store.list_applications(due="upcoming")["applications"][0]["id"], upcoming["id"])
        self.assertEqual(store.list_applications(status="interview")["total"], 1)

    def test_cv_pret_ne_regresse_pas_un_statut_avance(self):
        review = store.create_application("https://jobs.test/review")
        applied = store.create_application("https://jobs.test/applied")
        store.update_application(applied["id"], {"status": "applied"}, 1)
        self.assertTrue(store.mark_application_cv_ready(review["url"]))
        self.assertFalse(store.mark_application_cv_ready(applied["url"]))
        review_after = store.get_application(review["id"])
        applied_after = store.get_application(applied["id"])
        assert review_after is not None and applied_after is not None
        self.assertEqual(review_after["status"], "cv_ready")
        self.assertEqual(applied_after["status"], "applied")

    def test_suppression_efface_aussi_evenements(self):
        application = store.create_application("https://jobs.test/delete")
        self.assertTrue(store.application_events(application["id"]))
        self.assertTrue(store.delete_application(application["id"]))
        self.assertIsNone(store.get_application(application["id"]))
        self.assertEqual(store.application_events(application["id"]), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
