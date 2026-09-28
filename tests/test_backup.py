"""Backup and restore integrity tests."""

from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import backup, config, store  # noqa: E402


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.previous_db = store.DB_PATH
        self.saved = {name: os.environ.get(name) for name in ("JEV_CONFIG", "JEV_DATA_DIR")}
        os.environ["JEV_CONFIG"] = str(self.root / "missing.toml")
        os.environ["JEV_DATA_DIR"] = str(self.root)
        config.reset_cache()
        store.DB_PATH = str(self.root / "jev.db")
        self.user_dir = config.user_dir()
        (self.user_dir / "cv").mkdir(parents=True)
        (self.user_dir / "PROFILE.json").write_text('{"name":"before"}', encoding="utf-8")
        (self.user_dir / "CV_MASTER.json").write_text('{"identity":{"name":"Ada"}}', encoding="utf-8")
        (self.user_dir / "source_cv.pdf").write_bytes(b"%PDF-source")
        (self.user_dir / "cv" / "resume.pdf").write_bytes(b"%PDF-result")
        run_id = store.create_run(["https://jobs.test/one"])
        store.save_result(run_id, "https://jobs.test/one", "ok", {"url": "https://jobs.test/one"})
        store.finish_run(run_id)
        self.run_id = run_id

    def tearDown(self):
        store.DB_PATH = self.previous_db
        for name, value in self.saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        config.reset_cache()
        self.tmp.cleanup()

    def test_archive_contient_manifeste_checksums_et_aucun_secret(self):
        info = backup.create_backup()
        archive = backup.backup_path(info["name"])
        with zipfile.ZipFile(archive) as handle:
            names = set(handle.namelist())
            manifest = handle.read("manifest.json").decode("utf-8")
        self.assertIn("jev.db", names)
        self.assertIn("users/legacy-admin/PROFILE.json", names)
        self.assertIn("users/legacy-admin/CV_MASTER.json", names)
        self.assertIn("users/legacy-admin/cv/resume.pdf", names)
        self.assertNotIn("config.toml", names)
        self.assertNotIn(".env", names)
        self.assertIn("sha256", manifest)

    def test_restauration_remet_base_et_fichiers_en_place(self):
        info = backup.create_backup()
        archive = backup.backup_path(info["name"])
        (self.user_dir / "PROFILE.json").write_text('{"name":"after"}', encoding="utf-8")
        (self.user_dir / "source_cv.pdf").write_bytes(b"%PDF-after")
        (self.user_dir / "cv" / "resume.pdf").unlink()
        with store._LOCK, store._connect() as conn:
            conn.execute("DELETE FROM runs")
            conn.execute("DELETE FROM results")
        result = backup.restore_backup(archive)
        self.assertTrue(result["restored"])
        self.assertEqual((self.user_dir / "PROFILE.json").read_text(encoding="utf-8"), '{"name":"before"}')
        self.assertEqual((self.user_dir / "source_cv.pdf").read_bytes(), b"%PDF-source")
        self.assertEqual((self.user_dir / "cv" / "resume.pdf").read_bytes(), b"%PDF-result")
        self.assertIsNotNone(store.get_run(self.run_id))
        self.assertTrue(result["safety_backup"]["name"].startswith("jev-backup-"))

    def test_restauration_preserve_le_retour_sur_une_evaluation(self):
        url = "https://jobs.test/one"
        saved = store.put_evaluation_feedback(self.run_id, url, "bad_reason", "Justification à revoir", 0)
        assert saved is not None
        self.assertEqual(saved["revision"], 1)
        archive = backup.backup_path(backup.create_backup()["name"])
        store.put_evaluation_feedback(self.run_id, url, "correct", "Modifié après sauvegarde", 1)
        backup.restore_backup(archive)
        restored = store.get_evaluation_feedback(self.run_id, url)
        assert restored is not None
        self.assertEqual(restored["verdict"], "bad_reason")
        self.assertEqual(restored["note"], "Justification à revoir")
        self.assertEqual(restored["revision"], 1)

    def test_restauration_refuse_une_tache_active(self):
        archive = backup.backup_path(backup.create_backup()["name"])
        store.create_cv_job("https://jobs.test/cv")
        with self.assertRaises(backup.BackupError):
            backup.restore_backup(archive)

    def test_creation_verifie_archive_et_expose_manifest(self):
        info = backup.create_backup("scheduled")
        self.assertTrue(info["verified"])
        self.assertEqual(info["kind"], "scheduled")
        self.assertEqual(info["manifest"]["kind"], "scheduled")
        verified = backup.verify_backup(info["name"])
        self.assertTrue(verified["verified"])
        summary = backup.backup_summary()
        self.assertEqual(summary["count"], 1)
        self.assertEqual(summary["latest_scheduled"]["name"], info["name"])
        self.assertFalse(summary["scheduled_stale"])

    def test_retention_supprime_seulement_les_archives_expirees(self):
        old = backup.create_backup("manual")
        recent = backup.create_backup("manual")
        old_path = backup.backup_path(old["name"])
        expired = time.time() - 20 * 86400
        os.utime(old_path, (expired, expired))
        deleted = backup.prune_backups(14)
        self.assertEqual(deleted, [old["name"]])
        self.assertFalse(old_path.exists())
        self.assertTrue(backup.backup_path(recent["name"]).is_file())

    def test_archive_traversal_est_refusee(self):
        malicious = self.root / "malicious.zip"
        with zipfile.ZipFile(malicious, "w") as handle:
            handle.writestr("../secret", "x")
            handle.writestr("manifest.json", "{}")
        stage = self.root / "stage"
        stage.mkdir()
        with self.assertRaises(backup.BackupError):
            backup._validate_archive(malicious, stage)


if __name__ == "__main__":
    unittest.main(verbosity=2)
