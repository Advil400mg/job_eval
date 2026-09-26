#!/usr/bin/env python3
"""Verify a JEV backup archive without modifying the running instance."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import stat
import tempfile
import zipfile
from pathlib import Path, PurePosixPath


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_member(info: zipfile.ZipInfo) -> bool:
    path = PurePosixPath(info.filename)
    mode = info.external_attr >> 16
    return (
        bool(path.parts)
        and not path.is_absolute()
        and ".." not in path.parts
        and not (mode and stat.S_ISLNK(mode))
    )


def verify(path: Path) -> dict:
    if not path.is_file():
        raise RuntimeError(f"archive absente: {path}")
    try:
        archive = zipfile.ZipFile(path)
    except zipfile.BadZipFile as exc:
        raise RuntimeError("archive ZIP illisible") from exc

    with archive, tempfile.TemporaryDirectory(prefix="jev-backup-check-") as temporary:
        infos = archive.infolist()
        if not infos or any(not safe_member(info) for info in infos):
            raise RuntimeError("archive contenant un chemin ou un type interdit")
        try:
            manifest = json.loads(archive.read("manifest.json"))
        except (KeyError, json.JSONDecodeError) as exc:
            raise RuntimeError("manifeste absent ou invalide") from exc
        if manifest.get("format") != "jev-backup" or manifest.get("version") != 1:
            raise RuntimeError("format de sauvegarde incompatible")
        declared: dict[str, dict] = {}
        for item in manifest.get("files", []):
            if isinstance(item, dict) and isinstance(item.get("path"), str):
                declared[item["path"]] = item
        actual = {
            info.filename for info in infos
            if not info.is_dir() and info.filename != "manifest.json"
        }
        if set(declared) != actual or "jev.db" not in declared:
            raise RuntimeError("contenu différent du manifeste")
        stage = Path(temporary)
        archive.extractall(stage)
        for relative, metadata in declared.items():
            target = stage / relative
            if not target.is_file() or target.stat().st_size != int(metadata.get("size", -1)):
                raise RuntimeError(f"taille invalide: {relative}")
            if sha256(target) != metadata.get("sha256"):
                raise RuntimeError(f"empreinte invalide: {relative}")
        database = sqlite3.connect(stage / "jev.db")
        try:
            result = database.execute("PRAGMA integrity_check").fetchone()
        finally:
            database.close()
        if not result or result[0] != "ok":
            raise RuntimeError("base SQLite corrompue")
        return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("archive", type=Path)
    args = parser.parse_args()
    manifest = verify(args.archive.resolve())
    print(json.dumps({
        "ok": True,
        "archive": str(args.archive),
        "app_version": manifest.get("app_version"),
        "created_at": manifest.get("created_at"),
        "files": len(manifest.get("files", [])),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
