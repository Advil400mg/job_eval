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
from pathlib import Path, PurePosixPath

from . import config, store

FORMAT_VERSION = 1
_ALLOWED_ROOT_FILES = {"jev.db", "PROFILE.json", "CV_MASTER.json", "source_cv.pdf"}
_ALLOWED_PREFIXES = ("cv/", "cv-runs/", "users/")


class BackupError(RuntimeError):
    pass


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


def create_backup(kind: str = "manual") -> dict:
    settings = config.settings()
    backup_dir = Path(settings["backup"]["dir"])
    backup_dir.mkdir(parents=True, exist_ok=True)
    final_path = backup_dir / _archive_name(kind)
    temp_path = final_path.with_suffix(".zip.tmp")
    with tempfile.TemporaryDirectory(dir=settings["data_dir"], prefix=".backup-") as temporary:
        database = Path(temporary) / "jev.db"
        store.backup_database(str(database))
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
                "app_version": "2.3.0",
                "kind": kind,
                "files": entries,
            }
            archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    os.replace(temp_path, final_path)
    return backup_info(final_path)


def backup_info(path: Path) -> dict:
    return {"name": path.name, "size": path.stat().st_size,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(path.stat().st_mtime))}


def list_backups() -> list[dict]:
    directory = Path(config.settings()["backup"]["dir"])
    if not directory.is_dir():
        return []
    return [backup_info(path) for path in sorted(directory.glob("jev-backup-*.zip"), reverse=True)]


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
    if store.active_work_count():
        raise BackupError("Restauration refusée pendant une tâche active")
    settings = config.settings()
    data_dir = Path(settings["data_dir"])
    data_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=data_dir, prefix=".restore-") as temporary:
        stage = Path(temporary)
        manifest = _validate_archive(archive_path, stage)
        safety = create_backup("pre-restore")
        with store._LOCK:
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
