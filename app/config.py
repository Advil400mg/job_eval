"""Configuration de l'application.

Ordre de priorité : variables d'environnement > fichier de configuration
(config.toml) > valeurs par défaut. Aucun secret n'est jamais journalisé.

Emplacement du fichier : $JEV_CONFIG, sinon ./config.toml à côté de l'application.
Format TOML (stdlib `tomllib`, Python >= 3.11) — voir config.example.toml.
"""

from __future__ import annotations

import os
import tomllib
from functools import lru_cache
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = APP_DIR / "config.toml"
EXAMPLE_CONFIG = APP_DIR / "config.example.toml"

DEFAULTS: dict = {
    "app": {"host": "127.0.0.1", "port": 8000, "data_dir": "./data", "db_file": ""},
    "openrouter": {
        "api_key": "",
        "api_key_file": "",
        "endpoint": "https://openrouter.ai/api/alpha/decisions",
        "model": "typesafe/jev-1.13",
        "timeout_seconds": 120,
        "max_retries": 3,
    },
    "profile": {"path": "./PROFILE.json", "evaluator": "./scripts/evaluate_job.py",
                "minimum_global_score": None, "minimum_confidence": None},
    "fetch": {"timeout_seconds": 30, "max_workers": 4, "max_text_chars": 60000},
    "cv": {
        "enabled": True,
        "command": "{python} engine/tailor_cv.py {url} --json --out-dir {out_dir} --no-jev --no-telegram {extra}",
        "out_dir": "",
        "env_file": "",
        "model": "",
        "master": "",
        "email_target": "",
        "timeout_seconds": 900,
    },
}


class ConfigError(RuntimeError):
    pass


def config_path() -> Path:
    return Path(os.environ.get("JEV_CONFIG") or DEFAULT_CONFIG)


def _deep_merge(base: dict, override: dict) -> dict:
    out = {key: (dict(value) if isinstance(value, dict) else value)
           for key, value in base.items()}
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def _resolve_path(value: str, base: Path) -> Path:
    path = Path(os.path.expanduser(str(value)))
    return path if path.is_absolute() else (base / path).resolve()


def load_raw() -> dict:
    """Configuration fusionnée : défauts + fichier + surcharges d'environnement."""
    merged = dict(DEFAULTS)
    path = config_path()
    if path.is_file():
        try:
            with path.open("rb") as handle:
                merged = _deep_merge(merged, tomllib.load(handle))
        except (tomllib.TOMLDecodeError, OSError) as exc:
            raise ConfigError(f"config illisible ({path}) : {exc}") from exc

    env = os.environ
    overrides = {
        "app": {"host": env.get("HOST"), "port": env.get("PORT"),
                "data_dir": env.get("JEV_DATA_DIR"), "db_file": env.get("JEV_DB")},
        "profile": {"path": env.get("JEV_PROFILE"), "evaluator": env.get("JEV_EVALUATOR")},
        "cv": {"command": env.get("CV_COMMAND"), "out_dir": env.get("CV_OUT_DIR"),
               "env_file": env.get("HERMES_ENV_FILE")},
    }
    # CV_TAILOR_BIN (ancien nom) reste accepté : chemin d'un binaire appelé comme aujourd'hui
    if env.get("CV_TAILOR_BIN"):
        overrides["cv"]["command"] = (
            f"{env['CV_TAILOR_BIN']} {{url}} --json --out-dir {{out_dir}} "
            f"--no-jev --no-telegram {{extra}}")
    for section, values in overrides.items():
        cleaned = {k: v for k, v in values.items() if v not in (None, "")}
        if cleaned:
            merged[section] = {**merged.get(section, {}), **cleaned}
    return merged


def read_env_file(path: str | os.PathLike) -> dict:
    """Lit un fichier KEY=VALUE (style .env) sans jamais exposer sa valeur."""
    values: dict[str, str] = {}
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            for line in handle:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                values[key.strip()] = value.strip().strip('"').strip("'")
    except OSError:
        pass
    return values


def resolve_api_key(cfg: dict | None = None) -> str:
    """OPENROUTER_API_KEY (env) > config.toml > api_key_file > HERMES_ENV_FILE."""
    cfg = cfg or load_raw()
    if os.environ.get("OPENROUTER_API_KEY"):
        return os.environ["OPENROUTER_API_KEY"]
    if cfg["openrouter"].get("api_key"):
        return str(cfg["openrouter"]["api_key"]).strip()
    source = cfg["openrouter"].get("api_key_file")
    if source:
        path = _resolve_path(source, APP_DIR)
        values = read_env_file(path)
        if values.get("OPENROUTER_API_KEY"):
            return values["OPENROUTER_API_KEY"]
        try:
            raw = path.read_text(encoding="utf-8").strip().strip('"').strip("'")
        except OSError:
            raw = ""
        if raw and "\n" not in raw and "=" not in raw:
            return raw
    legacy = cfg["cv"].get("env_file")
    if legacy:
        values = read_env_file(_resolve_path(legacy, APP_DIR))
        if values.get("OPENROUTER_API_KEY"):
            return values["OPENROUTER_API_KEY"]
    return ""


def cv_environment(cfg: dict | None = None) -> tuple[dict, str]:
    """Environnement à passer au moteur CV + commande effective.

    Le moteur embarqué (engine/) lit ses chemins dans ces variables : elles sont
    dérivées de la configuration de l'application, pour qu'il n'y ait qu'une seule
    source de vérité (data_dir, profil, master, modèle).
    """
    settings_now = settings()
    env = dict(os.environ)
    env["OPENROUTER_API_KEY"] = resolve_api_key(cfg)
    env_file = settings_now["cv"]["env_file"]
    if env_file:
        # Comme pour le reste de la configuration, l'environnement est prioritaire.
        # C'est notamment nécessaire en conteneur, où les secrets SMTP sont injectés
        # par Compose/Ansible plutôt que lus depuis un chemin propre à l'hôte.
        for name, value in read_env_file(_resolve_path(env_file, APP_DIR)).items():
            env.setdefault(name, value)
    env["CV_DATA_DIR"] = str(settings_now["data_dir"])
    env["CV_OUT_DIR"] = str(settings_now["cv"]["out_dir"])
    env["CV_RUNS"] = str(settings_now["data_dir"] / "cv-runs")
    env["CV_PROFILE"] = str(settings_now["profile_path"])
    env["CV_JEV"] = str(settings_now["evaluator_path"])
    if settings_now["cv"]["model"]:
        env["CV_MODEL"] = str(settings_now["cv"]["model"])
    if settings_now["cv"]["master"]:
        env["CV_MASTER"] = str(_resolve_path(settings_now["cv"]["master"], APP_DIR))
    return env, str(settings_now["cv"].get("command") or "")


def email_target(cfg: dict | None = None) -> str:
    """Adresse affichée à l'utilisateur (jamais un mot de passe, jamais un secret)."""
    cfg = cfg or load_raw()
    if cfg["cv"].get("email_target"):
        return str(cfg["cv"]["email_target"])
    env_file = cfg["cv"].get("env_file")
    if env_file:
        return read_env_file(_resolve_path(env_file, APP_DIR)).get("EMAIL_ADDRESS", "")
    return os.environ.get("EMAIL_ADDRESS", "")


@lru_cache(maxsize=1)
def settings() -> dict:
    """Configuration résolue, chemins absolus, avec la clé API résolue à part."""
    cfg = load_raw()
    data_dir = _resolve_path(cfg["app"].get("data_dir") or "./data", APP_DIR)
    db_file = cfg["app"].get("db_file")
    resolved = {
        "host": cfg["app"].get("host") or "127.0.0.1",
        "port": int(cfg["app"].get("port") or 8000),
        "data_dir": data_dir,
        "db_file": _resolve_path(db_file, APP_DIR) if db_file else data_dir / "jev.db",
        "openrouter": {
            "endpoint": cfg["openrouter"].get("endpoint"),
            "model": cfg["openrouter"].get("model"),
            "timeout_seconds": int(cfg["openrouter"].get("timeout_seconds") or 120),
            "max_retries": int(cfg["openrouter"].get("max_retries") or 3),
        },
        "profile_path": _resolve_path(cfg["profile"].get("path") or "./PROFILE.json", APP_DIR),
        "evaluator_path": _resolve_path(
            cfg["profile"].get("evaluator") or "./scripts/evaluate_job.py", APP_DIR),
        "minimum_global_score": cfg["profile"].get("minimum_global_score"),
        "minimum_confidence": cfg["profile"].get("minimum_confidence"),
        "fetch": {
            "timeout_seconds": int(cfg["fetch"].get("timeout_seconds") or 30),
            "max_workers": max(1, min(int(cfg["fetch"].get("max_workers") or 4), 8)),
            "max_text_chars": int(cfg["fetch"].get("max_text_chars") or 60000),
        },
        "cv": {
            "enabled": bool(cfg["cv"].get("enabled", True)),
            "command": str(cfg["cv"].get("command") or ""),
            "out_dir": (_resolve_path(cfg["cv"]["out_dir"], APP_DIR)
                        if cfg["cv"].get("out_dir") else data_dir / "cv"),
            "env_file": cfg["cv"].get("env_file") or "",
            "model": cfg["cv"].get("model") or "",
            "master": cfg["cv"].get("master") or "",
            "timeout_seconds": int(cfg["cv"].get("timeout_seconds") or 900),
        },
        "config_file": str(config_path()),
        "config_file_exists": config_path().is_file(),
        "api_key_set": bool(resolve_api_key(cfg)),
        "email_target": email_target(cfg),
    }
    return resolved


def reset_cache() -> None:
    settings.cache_clear()
