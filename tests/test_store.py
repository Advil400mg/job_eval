"""Offline tests for SQLite persistence, migrations and scalable offer queries."""

from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import store  # noqa: E402


def payload(url: str, title: str, score: float | None, status: str = "qualified",
            company: str = "Example", location: str = "Brussels") -> dict:
    return {
        "url": url, "title": title, "company": company, "location": location,
        "published_at": "2026-09-20", "status": "ok",
        "decision": {"status": status, "hard_gate_failures": []},
        "gate_results": [],
        "jev": {
            "global_score": score, "minimum_global_score": 68,
            "minimum_confidence": 0.5, "blocking_criteria": [],
            "low_confidence_criteria": [], "criteria": [],
        },
    }


class StoreBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.previous_db = store.DB_PATH
        store.DB_PATH = str(Path(self.tmp.name) / "test.db")

    def tearDown(self):
        store.DB_PATH = self.previous_db
        self.tmp.cleanup()


class CvJobs(StoreBase):
    def test_liste_inclut_les_jobs_en_cours_apres_relecture(self):
        running = store.create_cv_job("https://example.test/offre")
        done = store.create_cv_job("https://example.test/autre")
        store.finish_cv_job(done, "done", {"pdf": "/tmp/cv.pdf"})
        jobs = store.list_cv_jobs()
        self.assertEqual({job["id"] for job in jobs}, {running, done})
        self.assertEqual(store.list_cv_jobs(status="running")[0]["id"], running)
        self.assertEqual(store.count_cv_jobs(status="done"), 1)
        result = next(job["payload"] for job in jobs if job["id"] == done)
        self.assertEqual(result["pdf"], "/tmp/cv.pdf")

    def test_derniers_cv_groupes_par_url_excluent_les_jobs_incomplets(self):
        url = "https://example.test/offre"
        old = store.create_cv_job(url)
        store.finish_cv_job(old, "done", {"pdf": "/tmp/old.pdf"})
        recent = store.create_cv_job(url)
        store.finish_cv_job(recent, "done", {"pdf": "/tmp/recent.pdf"})
        store.create_cv_job(url)
        other = store.create_cv_job("https://example.test/autre")
        store.finish_cv_job(other, "done", {"pdf": "/tmp/other.pdf"})
        with store._LOCK, store._connect() as conn:
            conn.execute("UPDATE cv_jobs SET created_at='2026-09-20T10:00:00' WHERE id=?", (old,))
            conn.execute("UPDATE cv_jobs SET created_at='2026-09-21T10:00:00' WHERE id=?", (recent,))
        jobs = store.latest_cvs_for([url, url, "https://example.test/autre"])
        self.assertEqual(set(jobs), {url, "https://example.test/autre"})
        self.assertEqual(jobs[url]["id"], recent)
        self.assertEqual(jobs[url]["payload"]["pdf"], "/tmp/recent.pdf")
        latest = store.latest_cv_for(url)
        self.assertIsNotNone(latest)
        assert latest is not None
        self.assertEqual(latest["id"], recent)

    def test_limite_offset_et_bornes(self):
        for index in range(3):
            store.create_cv_job(f"https://example.test/{index}")
        self.assertEqual(len(store.list_cv_jobs(limit=2)), 2)
        self.assertEqual(len(store.list_cv_jobs(limit=0)), 1)
        self.assertEqual(len(store.list_cv_jobs(limit=2, offset=2)), 1)


class Offers(StoreBase):
    def make_two_evaluations(self):
        old = store.create_run(["https://jobs.test/role?utm_source=mail"])
        store.save_result(old, "https://jobs.test/role?utm_source=mail", "ok",
                          payload("https://jobs.test/role?utm_source=mail", "Old role", 61, "rejected"))
        store.finish_run(old)
        new = store.create_run(["https://JOBS.test/role/#apply"])
        store.save_result(new, "https://JOBS.test/role/#apply", "ok",
                          payload("https://JOBS.test/role/#apply", "New role", 82))
        store.finish_run(new)
        with store._LOCK, store._connect() as conn:
            conn.execute("UPDATE runs SET created_at='2026-09-20T10:00:00' WHERE id=?", (old,))
            conn.execute("UPDATE runs SET created_at='2026-09-21T10:00:00' WHERE id=?", (new,))
        return old, new

    def test_normalisation_retire_tracking_fragment_et_slash(self):
        left = store.normalize_url("HTTPS://Example.COM/jobs/42/?utm_source=x&keep=1#apply")
        right = store.normalize_url("https://example.com/jobs/42?keep=1")
        self.assertEqual(left, right)

    def test_vue_latest_deduplique_et_conserve_historique(self):
        _, new = self.make_two_evaluations()
        latest = store.query_offers(view="latest")
        self.assertEqual(latest["total"], 1)
        self.assertEqual(latest["items"][0]["title"], "New role")
        self.assertEqual(latest["items"][0]["evaluation_count"], 2)
        self.assertEqual(latest["items"][0]["run_id"], new)
        self.assertEqual(store.query_offers(view="all")["total"], 2)
        self.assertEqual(len(store.offer_history("https://jobs.test/role")), 2)

    def test_filtres_tri_et_pagination_sont_appliques_en_sql(self):
        for index in range(35):
            run = store.create_run([f"https://jobs.test/{index}"])
            status = "qualified" if index % 2 else "rejected"
            store.save_result(run, f"https://jobs.test/{index}", "ok",
                              payload(f"https://jobs.test/{index}", f"Security role {index}",
                                      float(index), status,
                                      company="Acme" if index < 20 else "Other"))
            store.finish_run(run)
        page = store.query_offers(page=2, page_size=10, status="qualified", sort="score_desc")
        self.assertEqual(page["total"], 17)
        self.assertEqual(page["pages"], 2)
        self.assertEqual(len(page["items"]), 7)
        searched = store.query_offers(q="role 3", view="all")
        self.assertGreaterEqual(searched["total"], 6)
        facets = store.offer_facets()
        self.assertEqual(facets["statuses"]["qualified"], 17)
        self.assertEqual(facets["statuses"]["rejected"], 18)

    def test_migration_reindexe_une_ancienne_base_sans_perte(self):
        connection = sqlite3.connect(store.DB_PATH)
        connection.executescript("""
            CREATE TABLE runs (id TEXT PRIMARY KEY, created_at TEXT NOT NULL, urls TEXT NOT NULL,
                status TEXT NOT NULL, progress INTEGER NOT NULL DEFAULT 0, total INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE results (run_id TEXT NOT NULL, url TEXT NOT NULL, created_at TEXT NOT NULL,
                status TEXT NOT NULL, payload TEXT NOT NULL, PRIMARY KEY (run_id, url));
            INSERT INTO runs VALUES ('legacy', '2026-09-01T10:00:00', '[]', 'done', 1, 1);
        """)
        legacy = payload("https://legacy.test/job?utm_source=x", "Legacy", 73)
        connection.execute("INSERT INTO results VALUES (?, ?, ?, ?, ?)",
                           ("legacy", legacy["url"], "2026-09-01T10:00:01", "ok",
                            json.dumps(legacy)))
        connection.commit()
        connection.close()
        result = store.query_offers()
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["items"][0]["title"], "Legacy")
        with sqlite3.connect(store.DB_PATH) as check:
            columns = {row[1] for row in check.execute("PRAGMA table_info(results)")}
            run_columns = {row[1] for row in check.execute("PRAGMA table_info(runs)")}
            cv_columns = {row[1] for row in check.execute("PRAGMA table_info(cv_jobs)")}
            version = check.execute("PRAGMA user_version").fetchone()[0]
            journal_mode = check.execute("PRAGMA journal_mode").fetchone()[0]
        self.assertIn("normalized_url", columns)
        self.assertIn("score", columns)
        self.assertIn("attempts", run_columns)
        self.assertIn("cancel_requested", cv_columns)
        self.assertEqual(version, 3)
        self.assertEqual(journal_mode.lower(), "wal")


if __name__ == "__main__":
    unittest.main(verbosity=2)
