"""Offline checks for the versioned production deployment artifacts."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sqlite3
import sys
import tempfile
import tomllib
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, os.fspath(ROOT))

from app.version import APP_VERSION  # noqa: E402


class DeploymentArtifacts(unittest.TestCase):
    def test_version_is_centralized(self):
        self.assertEqual(APP_VERSION, "3.0.1")
        package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
        lock = json.loads((ROOT / "package-lock.json").read_text(encoding="utf-8"))
        self.assertEqual(package["version"], APP_VERSION)
        self.assertEqual(lock["version"], APP_VERSION)
        self.assertEqual(lock["packages"][""]["version"], APP_VERSION)
        main = (ROOT / "app/main.py").read_text(encoding="utf-8")
        backup = (ROOT / "app/backup.py").read_text(encoding="utf-8")
        self.assertIn("version=APP_VERSION", main)
        self.assertIn('"version": APP_VERSION', main)
        self.assertIn('"app_version": APP_VERSION', backup)

    def test_production_configuration_enforces_proxy_security(self):
        with (ROOT / "deploy/config.production.example.toml").open("rb") as handle:
            production = tomllib.load(handle)
        self.assertTrue(production["security"]["cookie_secure"])
        self.assertTrue(production["security"]["trust_proxy"])
        self.assertEqual(production["backup"]["dir"], "/backups")
        self.assertEqual(production["backup"]["retention_days"], 14)
        self.assertEqual(production["backup"]["stale_after_hours"], 36)
        self.assertEqual(production["audit"]["retention_days"], 180)

    def test_compose_only_publishes_the_reverse_proxy(self):
        compose = (ROOT / "deploy/compose.production.yml").read_text(encoding="utf-8")
        jev_section, caddy_section = compose.split("  caddy:\n", 1)
        self.assertNotIn("    ports:\n", jev_section)
        self.assertIn('"${JEV_HTTP_PORT:-80}:80"', caddy_section)
        self.assertIn('"${JEV_HTTPS_PORT:-443}:443"', caddy_section)
        self.assertIn("read_only: true", jev_section)
        self.assertIn("cap_drop:\n      - ALL", jev_section)
        self.assertIn("internal: true", compose)
        self.assertIn("- egress", jev_section)
        self.assertIn('ipv4_address: "${JEV_CADDY_BACKEND_IP:-172.30.240.254}"', caddy_section)
        self.assertIn('JEV_FORWARDED_ALLOW_IPS: "${JEV_FORWARDED_ALLOW_IPS:-172.30.240.254,127.0.0.1}"', jev_section)

    def test_compose_uses_read_only_secret_files(self):
        compose = (ROOT / "deploy/compose.production.yml").read_text(encoding="utf-8")
        self.assertIn("OPENROUTER_API_KEY_FILE: /run/secrets/openrouter_api_key", compose)
        self.assertIn("JEV_SESSION_SECRET_FILE: /run/secrets/session_secret", compose)
        self.assertIn("JEV_AUTH_PASSWORD_FILE: /run/secrets/admin_bootstrap_password", compose)
        self.assertIn("EMAIL_PASSWORD_FILE: /run/secrets/email_password", compose)
        self.assertNotIn("OPENROUTER_API_KEY:", compose)
        self.assertNotIn("JEV_SESSION_SECRET:", compose)

    def test_ansible_rollback_restores_release_environment_and_image(self):
        deploy = (ROOT / "deploy/ansible/roles/jev/tasks/deploy.yml").read_text(encoding="utf-8")
        rollback = (ROOT / "deploy/ansible/roles/jev/templates/jev-rollback.sh.j2").read_text(
            encoding="utf-8",
        )
        self.assertIn('dest: "{{ jev_env_file }}.previous"', deploy)
        self.assertIn("jev_previous_release.stdout", deploy)
        self.assertIn("jev-backup.timer", deploy)
        self.assertIn("previous_env", rollback)
        self.assertIn("previous_dir", rollback)
        self.assertIn("previous_backup_pointer", rollback)
        self.assertIn("jev-restore", rollback)
        self.assertIn('"${COMPOSE[@]}" up', rollback)
        validation = (ROOT / "deploy/ansible/roles/jev/tasks/main.yml").read_text(encoding="utf-8")
        self.assertNotIn("[:space:]", validation)
        self.assertIn("[^@\\s]+@[^@\\s]+", validation)
        self.assertIn('distribution_major_version in ["24", "26"]', validation)

    def test_decommission_requires_confirmation_and_preserves_data_by_default(self):
        playbook = ROOT / "deploy/ansible/decommission.yml"
        tasks = ROOT / "deploy/ansible/roles/jev/tasks/decommission.yml"
        self.assertTrue(playbook.is_file())
        self.assertTrue(tasks.is_file())
        content = tasks.read_text(encoding="utf-8")
        self.assertIn("jev_decommission_confirm | bool", content)
        self.assertIn("Refuse dangerous JEV decommission targets", content)
        self.assertIn("jev_install_root is match", content)
        self.assertIn("jev_config_dir is match", content)
        self.assertIn("jev_backup_dir is match", content)
        self.assertIn("reference={{ jev_image }}:*", content)
        self.assertIn("jev_decommission_purge_data | bool", content)
        self.assertIn("{{ jev_data_volume }}", content)
        self.assertIn("{{ jev_backup_dir }}", content)
        self.assertIn("{{ jev_system_user }}", content)
        self.assertLess(content.index("Remove JEV containers"), content.index("Purge JEV Docker volumes"))
        self.assertNotIn("docker-ce", content)
        self.assertNotIn("ufw delete", content)
        self.assertNotIn("ufw reset", content)

    def test_decommission_documentation_covers_preserve_and_purge_modes(self):
        documentation = (ROOT / "deploy/README.md").read_text(encoding="utf-8")
        self.assertIn("ansible-playbook decommission.yml", documentation)
        self.assertIn("jev_decommission_confirm=true", documentation)
        self.assertIn("jev_decommission_purge_data=true", documentation)
        self.assertIn("Mode standard : conserver les données", documentation)
        self.assertIn("Mode purge : suppression irréversible", documentation)

    def test_ansible_role_contains_release_and_operations_paths(self):
        required = [
            "deploy/ansible/site.yml",
            "deploy/ansible/roles/jev/tasks/install.yml",
            "deploy/ansible/roles/jev/tasks/deploy.yml",
            "deploy/ansible/roles/jev/tasks/operations.yml",
            "deploy/ansible/roles/jev/templates/production.env.j2",
            "deploy/ansible/roles/jev/templates/jev-backup.timer.j2",
            "deploy/ansible/roles/jev/templates/jev-restore.sh.j2",
            "deploy/ansible/roles/jev/templates/jev-rollback.sh.j2",
        ]
        self.assertTrue(all((ROOT / path).is_file() for path in required))


class BackupVerifier(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        script = ROOT / "deploy/scripts/verify-backup.py"
        spec = importlib.util.spec_from_file_location("jev_verify_backup", script)
        if spec is None or spec.loader is None:
            raise RuntimeError("Impossible de charger verify-backup.py")
        cls.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.module)

    def test_backup_verifier_detects_tampering(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            database = directory / "jev.db"
            connection = sqlite3.connect(database)
            connection.execute("CREATE TABLE sample (value TEXT)")
            connection.execute("INSERT INTO sample VALUES ('ok')")
            connection.commit()
            connection.close()
            payload = database.read_bytes()
            metadata = {
                "path": "jev.db",
                "size": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
            manifest = {
                "format": "jev-backup",
                "version": 1,
                "app_version": APP_VERSION,
                "created_at": "2026-09-26T00:00:00+0200",
                "files": [metadata],
            }
            archive = directory / "jev-backup-valid.zip"
            with zipfile.ZipFile(archive, "w") as handle:
                handle.writestr("jev.db", payload)
                handle.writestr("manifest.json", json.dumps(manifest))
            self.assertEqual(self.module.verify(archive)["app_version"], APP_VERSION)

            broken = directory / "jev-backup-broken.zip"
            with zipfile.ZipFile(broken, "w") as handle:
                handle.writestr("jev.db", payload + b"tampered")
                handle.writestr("manifest.json", json.dumps(manifest))
            with self.assertRaises(RuntimeError):
                self.module.verify(broken)


if __name__ == "__main__":
    unittest.main(verbosity=2)
