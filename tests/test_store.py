"""Tests hors ligne de la persistance des jobs CV."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import store  # noqa: E402


class CvJobs(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.previous_db = store.DB_PATH
        store.DB_PATH = str(Path(self.tmp.name) / "test.db")

    def tearDown(self):
        store.DB_PATH = self.previous_db
        self.tmp.cleanup()

    def test_liste_inclut_les_jobs_en_cours_apres_relecture(self):
        running = store.create_cv_job("https://example.test/offre")
        done = store.create_cv_job("https://example.test/autre")
        store.finish_cv_job(done, "done", {"pdf": "/tmp/cv.pdf"})

        jobs = store.list_cv_jobs()
        self.assertEqual({job["id"] for job in jobs}, {running, done})
        self.assertEqual(store.list_cv_jobs(status="running")[0]["id"], running)
        payload = next(job["payload"] for job in jobs if job["id"] == done)
        self.assertEqual(payload["pdf"], "/tmp/cv.pdf")

    def test_limite_est_bornee_et_acceptee(self):
        for index in range(3):
            store.create_cv_job(f"https://example.test/{index}")
        self.assertEqual(len(store.list_cv_jobs(limit=2)), 2)
        self.assertEqual(len(store.list_cv_jobs(limit=0)), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
