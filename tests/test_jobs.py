"""Durable job recovery tests."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config, jobs, store  # noqa: E402


class JobRecovery(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.previous_db = store.DB_PATH
        self.saved = {name: os.environ.get(name) for name in ("JEV_CONFIG", "JEV_DATA_DIR")}
        os.environ["JEV_CONFIG"] = str(Path(self.tmp.name) / "missing.toml")
        os.environ["JEV_DATA_DIR"] = self.tmp.name
        config.reset_cache()
        store.DB_PATH = str(Path(self.tmp.name) / "jev.db")

    def tearDown(self):
        store.DB_PATH = self.previous_db
        for name, value in self.saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        config.reset_cache()
        self.tmp.cleanup()

    def test_reprise_ne_relance_que_les_urls_manquantes(self):
        urls = ["https://jobs.test/one", "https://jobs.test/two"]
        run_id = store.create_run(urls)
        store.save_result(run_id, urls[0], "ok", {"url": urls[0], "status": "ok"})
        with mock.patch.object(jobs, "submit_run") as submit:
            result = jobs.recover_after_restart()
        submit.assert_called_once_with(run_id, [urls[1]])
        self.assertEqual(result["resumed_runs"], 1)
        run = store.get_run(run_id)
        assert run is not None
        self.assertEqual(run["attempts"], 2)
        self.assertEqual(run["status"], "running")

    def test_cv_en_cours_devient_interrompu_sans_relance_email(self):
        job_id = store.create_cv_job("https://jobs.test/cv", send_email=True)
        with mock.patch.object(jobs, "submit_run"):
            result = jobs.recover_after_restart()
        job = store.get_cv_job(job_id)
        assert job is not None
        self.assertEqual(result["interrupted_cv"], 1)
        self.assertEqual(job["status"], "interrupted")
        self.assertTrue(job["send_email"])
        self.assertIn("redémarrage", job["payload"]["error"])

    def test_relance_manuelle_du_cv_conserve_le_choix_email(self):
        job_id = store.create_cv_job("https://jobs.test/cv", send_email=True)
        store.finish_cv_job(job_id, "interrupted", {"error": "restart"})
        with mock.patch.object(jobs, "submit_cv") as submit:
            self.assertTrue(jobs.retry_cv(job_id))
        submit.assert_called_once_with(job_id)
        job = store.get_cv_job(job_id)
        assert job is not None
        self.assertEqual(job["status"], "running")
        self.assertEqual(job["attempts"], 2)
        self.assertTrue(job["send_email"])

    def test_annulation_est_persistante(self):
        run_id = store.create_run(["https://jobs.test/one"])
        cv_id = store.create_cv_job("https://jobs.test/cv")
        self.assertTrue(store.request_run_cancel(run_id))
        self.assertTrue(store.run_cancel_requested(run_id))
        self.assertTrue(store.request_cv_cancel(cv_id))
        self.assertTrue(store.cv_cancel_requested(cv_id))


if __name__ == "__main__":
    unittest.main(verbosity=2)
