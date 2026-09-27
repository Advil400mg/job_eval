"""Portable, integrity-checked backups for the persistent JEV data."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import stat
import tempfile
import time
import uuid
import zipfile
from contextlib import contextmanager
from pathlib import Path, PurePosixPath

import fcntl

from . import config, store
from .version import APP_VERSION

FORMAT_VERSION = 1
_ALLOWED_ROOT_FILES = {"jev.db", "PROFILE.json", "CV_MASTER.json", "source_cv.pdf"}
_ALLOWED_PREFIXES = ("cv/", "cv-runs/", "users/")


class BackupError(RuntimeError):
    pass


@contextmanager
def _maintenance_lock():
    data_dir = Path(config.settings()["data_dir"])
    data_dir.mkdir(parents=True, exist_ok=True)
    with (data_dir / ".maintenance.lock").open("a+") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sources() -> list[tuple[str, Path]]:
    settings = config.settings()
    return [
        ("users", Path(settings["data_dir"]) / "users"),
    ]


def _archive_name(kind: str) -> str:
    stamp = time.strftime("%Y%m%dT%H%M%S")
    return f"jev-backup-{stamp}-{kind}-{uuid.uuid4().hex[:6]}.zip"


def _create_backup(kind: str = "manual", database_connection: sqlite3.Connection | None = None) -> dict:
    settings = config.settings()
    backup_dir = Path(settings["backup"]["dir"])
    backup_dir.mkdir(parents=True, exist_ok=True)
    final_path = backup_dir / _archive_name(kind)
    temp_path = final_path.with_suffix(".zip.tmp")
    with tempfile.TemporaryDirectory(dir=settings["data_dir"], prefix=".backup-") as temporary:
        database = Path(temporary) / "jev.db"
        if database_connection is None:
            store.backup_database(str(database))
        else:
            store.backup_database_from_connection(database_connection, str(database))
        entries: list[dict] = []
        with zipfile.ZipFile(temp_path, "w", compression=zipfile.ZIP_DEFLATED,
                             compresslevel=6) as archive:
            archive.write(database, "jev.db")
            entries.append({"path": "jev.db", "size": database.stat().st_size,
                            "sha256": _sha256(database)})
            for logical, source in _sources():
                if source.is_file():
                    archive.write(source, logical)
                    entries.append({"path": logical, "size": source.stat().st_size,
                                    "sha256": _sha256(source)})
                elif source.is_dir():
                    for item in sorted(path for path in source.rglob("*") if path.is_file()):
                        relative = item.relative_to(source).as_posix()
                        archive_path = f"{logical}/{relative}"
                        archive.write(item, archive_path)
                        entries.append({"path": archive_path, "size": item.stat().st_size,
                                        "sha256": _sha256(item)})
            manifest = {
                "format": "jev-backup",
                "version": FORMAT_VERSION,
                "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "app_version": APP_VERSION,
                "kind": kind,
                "files": entries,
            }
            archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    os.replace(temp_path, final_path)
    return backup_info(final_path)


def create_backup(kind: str = "manual") -> dict:
    with _maintenance_lock():
        created = _create_backup(kind)
        verification = verify_backup(created["name"])
        created.update({"verified": True, "manifest": verification["manifest"]})
        created["pruned"] = prune_backups(config.settings()["backup"]["retention_days"])
        return created


def _manifest(path: Path) -> dict | None:
    try:
        with zipfile.ZipFile(path) as archive:
            payload = json.loads(archive.read("manifest.json"))
        return payload if isinstance(payload, dict) else None
    except (OSError, KeyError, zipfile.BadZipFile, json.JSONDecodeError):
        return None


def backup_info(path: Path) -> dict:
    stat_result = path.stat()
    manifest = _manifest(path)
    return {
        "name": path.name,
        "size": stat_result.st_size,
        "created_at": (manifest or {}).get("created_at") or time.strftime(
            "%Y-%m-%dT%H:%M:%S", time.localtime(stat_result.st_mtime)),
        "kind": (manifest or {}).get("kind", "unknown"),
        "app_version": (manifest or {}).get("app_version"),
        "manifest_valid": bool(manifest),
        "age_hours": round(max(0.0, time.time() - stat_result.st_mtime) / 3600, 1),
    }


def list_backups() -> list[dict]:
    directory = Path(config.settings()["backup"]["dir"])
    if not directory.is_dir():
        return []
    return [backup_info(path) for path in sorted(directory.glob("jev-backup-*.zip"), reverse=True)]


def prune_backups(retention_days: int | None = None) -> list[str]:
    directory = Path(config.settings()["backup"]["dir"])
    if not directory.is_dir():
        return []
    days = retention_days or int(config.settings()["backup"]["retention_days"])
    cutoff = time.time() - max(1, int(days)) * 86400
    deleted: list[str] = []
    for path in directory.glob("jev-backup-*.zip"):
        if path.is_file() and path.stat().st_mtime < cutoff:
            path.unlink()
            deleted.append(path.name)
    return sorted(deleted)


def verify_backup(name: str) -> dict:
    path = backup_path(name)
    data_dir = Path(config.settings()["data_dir"])
    data_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=data_dir, prefix=".verify-") as temporary:
        manifest = _validate_archive(path, Path(temporary))
    return {"name": name, "verified": True, "manifest": manifest}


def backup_summary() -> dict:
    backups = list_backups()
    scheduled = next((item for item in backups if item["kind"] == "scheduled"), None)
    stale_hours = int(config.settings()["backup"]["stale_after_hours"])
    return {
        "count": len(backups),
        "total_size": sum(int(item["size"]) for item in backups),
        "latest": backups[0] if backups else None,
        "latest_scheduled": scheduled,
        "scheduled_stale": not scheduled or float(scheduled["age_hours"]) > stale_hours,
        "stale_after_hours": stale_hours,
        "retention_days": int(config.settings()["backup"]["retention_days"]),
    }


def backup_path(name: str) -> Path:
    if not name or Path(name).name != name or not name.startswith("jev-backup-") or not name.endswith(".zip"):
        raise BackupError("Nom de sauvegarde invalide")
    path = Path(config.settings()["backup"]["dir"]) / name
    if not path.is_file():
        raise BackupError("Sauvegarde inconnue")
    return path


def delete_backup(name: str) -> None:
    backup_path(name).unlink()


def _safe_member(info: zipfile.ZipInfo) -> bool:
    path = PurePosixPath(info.filename)
    if info.filename == "manifest.json":
        return True
    if path.is_absolute() or ".." in path.parts or not path.parts:
        return False
    mode = info.external_attr >> 16
    if mode and stat.S_ISLNK(mode):
        return False
    name = path.as_posix()
    return name in _ALLOWED_ROOT_FILES or name.startswith(_ALLOWED_PREFIXES)


def _validate_archive(archive_path: Path, stage: Path) -> dict:
    max_bytes = config.settings()["backup"]["max_upload_bytes"]
    try:
        archive = zipfile.ZipFile(archive_path)
    except (OSError, zipfile.BadZipFile) as exc:
        raise BackupError("Archive ZIP illisible") from exc
    with archive:
        infos = archive.infolist()
        if len(infos) > 10_000 or sum(item.file_size for item in infos) > max_bytes:
            raise BackupError("Archive trop volumineuse")
        if any(not _safe_member(item) for item in infos):
            raise BackupError("Archive contenant un chemin ou un type de fichier interdit")
        try:
            manifest = json.loads(archive.read("manifest.json"))
        except (KeyError, json.JSONDecodeError) as exc:
            raise BackupError("Manifeste absent ou invalide") from exc
        if manifest.get("format") != "jev-backup" or manifest.get("version") != FORMAT_VERSION:
            raise BackupError("Format de sauvegarde incompatible")
        files = manifest.get("files")
        if not isinstance(files, list) or not files:
            raise BackupError("Manifeste sans fichiers")
        declared = {
            item["path"]: item for item in files
            if isinstance(item, dict) and isinstance(item.get("path"), str)
        }
        actual = {item.filename for item in infos if not item.is_dir() and item.filename != "manifest.json"}
        if set(declared) != actual or "jev.db" not in declared:
            raise BackupError("Contenu de l’archive différent du manifeste")
        archive.extractall(stage)
    for relative, metadata in declared.items():
        target = stage / relative
        if not target.is_file() or target.stat().st_size != int(metadata.get("size", -1)):
            raise BackupError(f"Taille invalide pour {relative}")
        if _sha256(target) != metadata.get("sha256"):
            raise BackupError(f"Checksum invalide pour {relative}")
    database = sqlite3.connect(stage / "jev.db")
    try:
        result = database.execute("PRAGMA integrity_check").fetchone()
        if not result or result[0] != "ok":
            raise BackupError("Base SQLite corrompue")
    finally:
        database.close()
    return manifest


def _atomic_file(source: Path | None, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if source is None:
        target.unlink(missing_ok=True)
        return
    with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as handle:
        temporary = Path(handle.name)
    try:
        shutil.copy2(source, temporary)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def _atomic_directory(source: Path | None, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    replacement = target.parent / f".{target.name}.restore-{uuid.uuid4().hex}"
    previous = target.parent / f".{target.name}.previous-{uuid.uuid4().hex}"
    if source is not None:
        shutil.copytree(source, replacement)
    try:
        if target.exists():
            os.replace(target, previous)
        if source is not None:
            os.replace(replacement, target)
        if previous.exists():
            shutil.rmtree(previous)
    except Exception:
        if target.exists() and source is not None:
            shutil.rmtree(target, ignore_errors=True)
        if previous.exists():
            os.replace(previous, target)
        raise
    finally:
        shutil.rmtree(replacement, ignore_errors=True)
        shutil.rmtree(previous, ignore_errors=True)


def restore_backup(archive_path: Path) -> dict:
    settings = config.settings()
    data_dir = Path(settings["data_dir"])
    data_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=data_dir, prefix=".restore-") as temporary:
        stage = Path(temporary)
        manifest = _validate_archive(archive_path, stage)
        with _maintenance_lock():
            with store._LOCK:
                with store._connect() as connection:
                    runs = int(connection.execute(
                        "SELECT COUNT(*) FROM runs WHERE status = 'running'",
                    ).fetchone()[0])
                    cvs = int(connection.execute(
                        "SELECT COUNT(*) FROM cv_jobs WHERE status = 'running'",
                    ).fetchone()[0])
                    if runs + cvs:
                        raise BackupError("Restauration refusée pendant une tâche active")
                    safety = _create_backup("pre-restore", database_connection=connection)
                _atomic_file(stage / "jev.db", Path(store.DB_PATH))
                Path(str(store.DB_PATH) + "-wal").unlink(missing_ok=True)
                Path(str(store.DB_PATH) + "-shm").unlink(missing_ok=True)
                _atomic_file(stage / "PROFILE.json" if (stage / "PROFILE.json").is_file() else None,
                             Path(settings["profile_path"]))
                _atomic_file(stage / "CV_MASTER.json" if (stage / "CV_MASTER.json").is_file() else None,
                             Path(settings["cv"]["master_path"]))
                _atomic_file(stage / "source_cv.pdf" if (stage / "source_cv.pdf").is_file() else None,
                             data_dir / "source_cv.pdf")
                _atomic_directory(stage / "cv" if (stage / "cv").is_dir() else None,
                                  Path(settings["cv"]["out_dir"]))
                _atomic_directory(stage / "cv-runs" if (stage / "cv-runs").is_dir() else None,
                                  data_dir / "cv-runs")
                _atomic_directory(stage / "users" if (stage / "users").is_dir() else None,
                                  data_dir / "users")
    return {"restored": True, "manifest": manifest, "safety_backup": safety}
