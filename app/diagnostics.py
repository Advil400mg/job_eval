"""Administrator diagnostics limited to state observable by the JEV process."""

from __future__ import annotations

import os
import shutil
import threading
import time
from pathlib import Path

from . import backup, config, store
from .version import APP_VERSION

_CACHE_LOCK = threading.Lock()
_CACHE: tuple[float, dict] | None = None
_CACHE_SECONDS = 15


def _file_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _status_counts(connection, table: str) -> dict[str, int]:
    if table not in {"runs", "cv_jobs", "onboarding_jobs"}:
        raise ValueError("Table de diagnostic non autorisée")
    rows = connection.execute(
        f"SELECT status, COUNT(*) AS count FROM {table} GROUP BY status"
    ).fetchall()
    return {str(row["status"]): int(row["count"]) for row in rows}


def _storage_state(connection, data_dir: Path) -> dict:
    users_root = data_dir / "users"
    users_root.mkdir(parents=True, exist_ok=True)
    expected = {str(row[0]) for row in connection.execute("SELECT id FROM users").fetchall()}
    present = {
        path.name for path in users_root.iterdir()
        if path.is_dir() and not path.name.startswith(".deleting-")
    }
    deleting = sorted(path.name for path in users_root.glob(".deleting-*") if path.is_dir())
    return {
        "expected_user_directories": len(expected),
        "present_user_directories": len(present),
        "missing_user_directories": sorted(expected - present),
        "orphan_user_directories": sorted(present - expected),
        "pending_deletions": deleting,
    }


def _compute() -> dict:
    settings = config.settings()
    data_dir = Path(settings["data_dir"])
    data_dir.mkdir(parents=True, exist_ok=True)
    database = Path(store.DB_PATH)
    usage = shutil.disk_usage(data_dir)
    with store._LOCK, store._connect() as connection:
        quick_check_row = connection.execute("PRAGMA quick_check").fetchone()
        quick_check = str(quick_check_row[0]) if quick_check_row else "unknown"
        schema_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        active_users = int(connection.execute(
            "SELECT COUNT(*) FROM users WHERE active = 1"
        ).fetchone()[0])
        users = int(connection.execute("SELECT COUNT(*) FROM users").fetchone()[0])
        runs = _status_counts(connection, "runs")
        cv_jobs = _status_counts(connection, "cv_jobs")
        onboarding_jobs = _status_counts(connection, "onboarding_jobs")
        storage = _storage_state(connection, data_dir)
    backup_state = backup.backup_summary()
    free_ratio = usage.free / usage.total if usage.total else 0.0
    checks = [
        {"id": "database", "label": "Intégrité SQLite",
         "status": "ok" if quick_check == "ok" else "error", "detail": quick_check},
        {"id": "disk", "label": "Espace disque",
         "status": "warning" if usage.free < 512 * 1024 * 1024 or free_ratio < 0.10 else "ok",
         "detail": f"{usage.free} octets disponibles"},
        {"id": "scheduled_backup", "label": "Sauvegarde planifiée",
         "status": "warning" if backup_state["scheduled_stale"] else "ok",
         "detail": ("Aucune sauvegarde planifiée récente" if backup_state["scheduled_stale"]
                    else str(backup_state["latest_scheduled"]["created_at"]))},
        {"id": "storage", "label": "Répertoires utilisateurs",
         "status": "warning" if (storage["missing_user_directories"] or
                                  storage["orphan_user_directories"] or
                                  storage["pending_deletions"]) else "ok",
         "detail": (f"{len(storage['missing_user_directories'])} manquant(s), "
                    f"{len(storage['orphan_user_directories'])} orphelin(s), "
                    f"{len(storage['pending_deletions'])} suppression(s) en attente")},
    ]
    if runs.get("failed", 0) + cv_jobs.get("failed", 0) + onboarding_jobs.get("failed", 0):
        checks.append({"id": "failed_jobs", "label": "Tâches en échec", "status": "warning",
                       "detail": "Des tâches ont échoué ; consulter leurs pages de suivi."})
    overall = "error" if any(item["status"] == "error" for item in checks) else (
        "warning" if any(item["status"] == "warning" for item in checks) else "ok"
    )
    return {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "status": overall,
        "app": {"version": APP_VERSION, "schema_version": schema_version},
        "database": {
            "quick_check": quick_check,
            "path_name": database.name,
            "size": _file_size(database),
            "wal_size": _file_size(Path(str(database) + "-wal")),
            "shm_size": _file_size(Path(str(database) + "-shm")),
        },
        "disk": {"total": usage.total, "used": usage.used, "free": usage.free},
        "users": {"total": users, "active": active_users},
        "jobs": {"runs": runs, "cv": cv_jobs, "onboarding": onboarding_jobs},
        "storage": storage,
        "backups": backup_state,
        "checks": checks,
        "capabilities": {
            "systemd": False, "caddy": False,
            "note": "Le conteneur n’observe ni systemd ni l’état du reverse proxy.",
        },
    }


def collect(force: bool = False) -> dict:
    global _CACHE
    now = time.monotonic()
    with _CACHE_LOCK:
        if not force and _CACHE and now - _CACHE[0] < _CACHE_SECONDS:
            return _CACHE[1]
        payload = _compute()
        _CACHE = (now, payload)
        return payload


def reset_cache() -> None:
    global _CACHE
    with _CACHE_LOCK:
        _CACHE = None
