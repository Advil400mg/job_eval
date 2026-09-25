"""Tests hors ligne de la configuration (stdlib uniquement).

Run:  python3 tests/test_config.py
"""

from __future__ import annotations

import os
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import config, cv  # noqa: E402


class ConfigBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.saved = {k: os.environ.get(k) for k in
                      ("JEV_CONFIG", "OPENROUTER_API_KEY", "PORT", "HOST",
                       "JEV_DATA_DIR", "JEV_DB", "JEV_PROFILE", "CV_MASTER", "CV_TAILOR_BIN",
                       "CV_COMMAND", "EMAIL_ADDRESS", "EMAIL_PASSWORD",
                       "EMAIL_SMTP_HOST", "EMAIL_SMTP_PORT", "EMAIL_IMAP_HOST",
                       "EMAIL_IMAP_PORT", "HERMES_ENV_FILE", "JEV_AUTH_PASSWORD",
                       "JEV_SESSION_SECRET", "JEV_COOKIE_SECURE", "JEV_TRUST_PROXY",
                       "JEV_ALLOW_INSECURE_REMOTE")}
        for key in self.saved:
            os.environ.pop(key, None)
        # isole les tests du config.toml réellement présent dans le dossier
        os.environ["JEV_CONFIG"] = str(self.dir / "absent.toml")
        config.reset_cache()

    def tearDown(self):
        for key, value in self.saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        config.reset_cache()
        self.tmp.cleanup()

    def write_config(self, body: str) -> Path:
        path = self.dir / "config.toml"
        path.write_text(textwrap.dedent(body).strip() + "\n", encoding="utf-8")
        os.environ["JEV_CONFIG"] = str(path)
        config.reset_cache()
        return path


class Defaults(ConfigBase):
    def test_sans_fichier_les_defauts_sont_relatifs_au_dossier(self):
        settings = config.settings()
        self.assertFalse(settings["config_file_exists"])
        self.assertEqual(settings["db_file"], config.APP_DIR / "data" / "jev.db")
        self.assertEqual(settings["profile_path"], config.APP_DIR / "data" / "PROFILE.json")
        self.assertEqual(settings["cv"]["master_path"], config.APP_DIR / "data" / "CV_MASTER.json")
        self.assertEqual(settings["openrouter"]["model"], "typesafe/jev-1.13")
        self.assertTrue(str(settings["openrouter"]["endpoint"]).startswith("https://"))
        self.assertEqual(settings["port"], 8000)

    def test_cles_de_configuration_attendues(self):
        settings = config.settings()
        for key in ("host", "port", "data_dir", "db_file", "openrouter", "profile_path",
                    "evaluator_path", "fetch", "cv", "security", "jobs", "backup",
                    "api_key_set", "email_target"):
            self.assertIn(key, settings)


class FileAndEnv(ConfigBase):
    def test_le_fichier_ecrase_les_defauts(self):
        self.write_config("""
            [app]
            port = 9001
            data_dir = "./donnees"
            [openrouter]
            model = "mon/modele"
            [fetch]
            max_workers = 7
        """)
        settings = config.settings()
        self.assertTrue(settings["config_file_exists"])
        self.assertEqual(settings["port"], 9001)
        self.assertEqual(settings["openrouter"]["model"], "mon/modele")
        self.assertEqual(settings["fetch"]["max_workers"], 7)
        self.assertEqual(settings["db_file"], config.APP_DIR / "donnees" / "jev.db")

    def test_les_variables_d_environnement_priment(self):
        self.write_config("""
            [app]
            port = 9001
            [openrouter]
            model = "mon/modele"
        """)
        os.environ["PORT"] = "9002"
        os.environ["JEV_DATA_DIR"] = str(self.dir / "autre")
        os.environ["CV_MASTER"] = str(self.dir / "master-custom.json")
        config.reset_cache()
        settings = config.settings()
        self.assertEqual(settings["port"], 9002)
        self.assertEqual(settings["data_dir"], self.dir / "autre")
        self.assertEqual(settings["profile_path"], self.dir / "autre" / "PROFILE.json")
        self.assertEqual(settings["cv"]["master_path"], self.dir / "master-custom.json")

    def test_chemin_de_config_inexistant_echoue_clairement(self):
        os.environ["JEV_CONFIG"] = str(self.dir / "absent.toml")
        config.reset_cache()
        self.assertFalse(config.settings()["config_file_exists"])  # pas d'exception

    def test_toml_invalide_leve_une_erreur_explicite(self):
        path = self.dir / "casse.toml"
        path.write_text("[app\nport = 1\n", encoding="utf-8")
        os.environ["JEV_CONFIG"] = str(path)
        config.reset_cache()
        with self.assertRaises(config.ConfigError):
            config.load_raw()


class ApiKey(ConfigBase):
    def test_variable_d_environnement_prioritaire(self):
        env_file = self.dir / "keys.env"
        env_file.write_text("OPENROUTER_API_KEY=depuis-fichier\n", encoding="utf-8")
        self.write_config(f'[openrouter]\napi_key_file = "{env_file}"\napi_key = "depuis-config"\n')
        os.environ["OPENROUTER_API_KEY"] = "depuis-env"
        config.reset_cache()
        self.assertEqual(config.resolve_api_key(), "depuis-env")

    def test_fichier_key_value(self):
        env_file = self.dir / "keys.env"
        env_file.write_text('# commentaire\nOPENROUTER_API_KEY="depuis-fichier"\n',
                            encoding="utf-8")
        self.write_config(f'[openrouter]\napi_key_file = "{env_file}"\n')
        self.assertEqual(config.resolve_api_key(), "depuis-fichier")

    def test_fichier_cle_brute(self):
        raw = self.dir / "key.txt"
        raw.write_text("sk-or-brute\n", encoding="utf-8")
        self.write_config(f'[openrouter]\napi_key_file = "{raw}"\n')
        self.assertEqual(config.resolve_api_key(), "sk-or-brute")

    def test_absente(self):
        self.assertEqual(config.resolve_api_key(), "")
        self.assertFalse(config.settings()["api_key_set"])

    def test_la_cle_n_apparait_dans_aucun_champ_de_healthz(self):
        os.environ["OPENROUTER_API_KEY"] = "secret-de-test-1234"
        config.reset_cache()
        settings = config.settings()
        self.assertTrue(settings["api_key_set"])
        self.assertNotIn("secret-de-test-1234", repr(settings))


class EmailAndCv(ConfigBase):
    def test_email_target_prioritaire_dans_le_fichier(self):
        self.write_config('[cv]\nemail_target = "moi@exemple.test"\n')
        self.assertEqual(config.email_target(), "moi@exemple.test")

    def test_email_target_lu_dans_env_file(self):
        env_file = self.dir / "mail.env"
        env_file.write_text("EMAIL_ADDRESS=boite@exemple.test\n", encoding="utf-8")
        self.write_config(f'[cv]\nenv_file = "{env_file}"\n')
        self.assertEqual(config.email_target(), "boite@exemple.test")
        self.assertEqual(config.settings()["email_target"], "boite@exemple.test")

    def test_variables_smtp_de_l_environnement_priment_sur_env_file(self):
        env_file = self.dir / "mail.env"
        env_file.write_text(
            "EMAIL_ADDRESS=fichier@exemple.test\nEMAIL_PASSWORD=depuis-fichier\n",
            encoding="utf-8",
        )
        self.write_config(f'[cv]\nenv_file = "{env_file}"\n')
        os.environ["EMAIL_ADDRESS"] = "conteneur@exemple.test"
        os.environ["EMAIL_PASSWORD"] = "depuis-environnement"
        config.reset_cache()
        environment, _ = config.cv_environment()
        self.assertEqual(environment["EMAIL_ADDRESS"], "conteneur@exemple.test")
        self.assertEqual(environment["EMAIL_PASSWORD"], "depuis-environnement")

    def test_cv_desactive(self):
        self.write_config("[cv]\nenabled = false\n")
        ok, why = cv.available()
        self.assertFalse(ok)
        self.assertIn("désactivé", why)

    def test_cv_commande_dans_le_path(self):
        self.write_config('[cv]\ncommand = "python3 {url} --out-dir {out_dir} {extra}"\n')
        ok, why = cv.available()
        self.assertTrue(ok, why)

    def test_cv_chemin_absolu_inexistant(self):
        self.write_config('[cv]\ncommand = "/nulle/part/moteur {url} {out_dir} {extra}"\n')
        ok, why = cv.available()
        self.assertFalse(ok)
        self.assertIn("/nulle/part/moteur", why)

    def test_gabarit_de_commande_rendu(self):
        self.write_config('[cv]\ncommand = "tool {url} --out {out_dir} {extra}"\n')
        rendered = cv._expand(cv.command_template(), "https://a.test", "/tmp/out", "--dry-run")
        self.assertEqual(rendered, ["tool", "https://a.test", "--out", "/tmp/out", "--dry-run"])

    def test_moteur_cv_est_execute_depuis_la_racine_de_l_application(self):
        pdf = self.dir / "cv.pdf"
        pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")
        settings = {
            "enabled": True,
            "command": "python3 engine/tailor_cv.py {url} --out-dir {out_dir} {extra}",
            "out_dir": self.dir,
            "timeout_seconds": 30,
        }
        completed = mock.Mock(returncode=0, stdout=f'{{"pdf": "{pdf}"}}', stderr="")
        with (mock.patch.object(cv, "_settings", return_value=settings),
              mock.patch.object(cv, "available", return_value=(True, "ok")),
              mock.patch.object(config, "cv_environment", return_value=({}, settings["command"])),
              mock.patch.object(cv.subprocess, "run", return_value=completed) as run):
            cv.generate("https://example.test/offre")
        self.assertEqual(run.call_args.kwargs["cwd"], str(config.APP_DIR))

    def test_ancien_nom_cv_tailor_bin_accepte(self):
        os.environ["CV_TAILOR_BIN"] = "/opt/cv-tailor"
        config.reset_cache()
        self.assertIn("/opt/cv-tailor {url}", cv.command_template())


if __name__ == "__main__":
    unittest.main(verbosity=2)