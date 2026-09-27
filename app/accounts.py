"""User accounts, password hashing and first-admin bootstrap."""

from __future__ import annotations

import os
import re
import secrets
import hashlib
import logging
import shutil
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from . import config, store

LEGACY_ADMIN_ID = "legacy-admin"
_USERNAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{2,63}$")
_EMAIL = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_HASHER = PasswordHasher(time_cost=2, memory_cost=19_456, parallelism=1, hash_len=32, salt_len=16)
_LOGGER = logging.getLogger(__name__)
_DELETING_DIR = re.compile(
    r"^\.deleting-(?P<user_id>[A-Za-z0-9][A-Za-z0-9_.-]{0,127})-(?P<nonce>[0-9a-f]{32})$"
)


class AccountError(RuntimeError):
    pass


class AccountConflict(AccountError):
    pass


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def normalize_username(value: str) -> str:
    username = (value or "").strip()
    if not _USERNAME.fullmatch(username):
        raise AccountError(
            "Le nom d’utilisateur doit faire 3 à 64 caractères et contenir uniquement "
            "lettres, chiffres, point, tiret ou underscore."
        )
    return username.lower()


def normalize_email(value: str | None) -> str | None:
    email = (value or "").strip().lower()
    if not email:
        return None
    if len(email) > 320 or not _EMAIL.fullmatch(email):
        raise AccountError("Adresse email invalide")
    return email


def validate_password(password: str) -> None:
    if len(password or "") < 12:
        raise AccountError("Le mot de passe doit contenir au moins 12 caractères")
    if len(password) > 512:
        raise AccountError("Le mot de passe est trop long")


def hash_password(password: str) -> str:
    validate_password(password)
    return _HASHER.hash(password)


def verify_password(password: str, encoded_hash: str) -> bool:
    if not password or not encoded_hash:
        return False
    try:
        return bool(_HASHER.verify(encoded_hash, password))
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def _public(row) -> dict:
    user = dict(row)
    user.pop("password_hash", None)
    user["active"] = bool(user.get("active"))
    return user


def count_users(active_only: bool = False) -> int:
    query = "SELECT COUNT(*) FROM users" + (" WHERE active = 1" if active_only else "")
    with store._LOCK, store._connect() as conn:
        return int(conn.execute(query).fetchone()[0])


def get_user(user_id: str, include_disabled: bool = False) -> dict | None:
    query = "SELECT * FROM users WHERE id = ?"
    if not include_disabled:
        query += " AND active = 1"
    with store._LOCK, store._connect() as conn:
        row = conn.execute(query, (user_id,)).fetchone()
    return _public(row) if row else None


def list_users() -> list[dict]:
    with store._LOCK, store._connect() as conn:
        rows = conn.execute(
            "SELECT * FROM users ORDER BY "
            "CASE role WHEN 'admin' THEN 0 ELSE 1 END, active DESC, username_normalized"
        ).fetchall()
    return [_public(row) for row in rows]


def active_user_count() -> int:
    return count_users(active_only=True)


def create_user(username: str, password: str, email: str | None = None,
                display_name: str = "", role: str = "user", user_id: str | None = None) -> dict:
    normalized_username = normalize_username(username)
    normalized_email = normalize_email(email)
    if role not in ("admin", "user"):
        raise AccountError("Rôle utilisateur invalide")
    now = _now()
    user_id = user_id or uuid.uuid4().hex[:16]
    try:
        with store._LOCK, store._connect() as conn:
            conn.execute(
                "INSERT INTO users (id, username, username_normalized, email, email_normalized, "
                "display_name, password_hash, role, active, session_version, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, 1, ?, ?)",
                (user_id, username.strip(), normalized_username, normalized_email, normalized_email,
                 display_name.strip(), hash_password(password), role, now, now),
            )
            row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    except Exception as exc:
        if "UNIQUE constraint failed" in str(exc):
            raise AccountConflict("Ce nom d’utilisateur ou cette adresse email est déjà utilisé") from exc
        raise
    return _public(row)


def authenticate(identifier: str, password: str) -> dict | None:
    normalized = (identifier or "").strip().lower()
    if not normalized:
        return None
    with store._LOCK, store._connect() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE active = 1 AND "
            "(username_normalized = ? OR email_normalized = ?)",
            (normalized, normalized),
        ).fetchone()
        if not row or not verify_password(password, row["password_hash"]):
            return None
        conn.execute("UPDATE users SET last_login_at = ?, updated_at = ? WHERE id = ?",
                     (_now(), _now(), row["id"]))
    return _public(row)


def create_first_admin(username: str, password: str, email: str | None = None,
                       display_name: str = "") -> dict:
    with store._LOCK, store._connect() as conn:
        existing = conn.execute("SELECT * FROM users ORDER BY created_at LIMIT 1").fetchone()
        if existing and existing["id"] != LEGACY_ADMIN_ID:
            raise AccountConflict("Le premier administrateur existe déjà")
        if existing and existing["active"]:
            raise AccountConflict("Le premier administrateur existe déjà")
        normalized_username = normalize_username(username)
        normalized_email = normalize_email(email)
        now = _now()
        if existing:
            conn.execute(
                "UPDATE users SET username=?, username_normalized=?, email=?, email_normalized=?, "
                "display_name=?, password_hash=?, role='admin', active=1, session_version=1, "
                "updated_at=? WHERE id=?",
                (username.strip(), normalized_username, normalized_email, normalized_email,
                 display_name.strip(), hash_password(password), now, LEGACY_ADMIN_ID),
            )
            user_id = LEGACY_ADMIN_ID
        else:
            user_id = uuid.uuid4().hex[:16]
            conn.execute(
                "INSERT INTO users (id, username, username_normalized, email, email_normalized, "
                "display_name, password_hash, role, active, session_version, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, 'admin', 1, 1, ?, ?)",
                (user_id, username.strip(), normalized_username, normalized_email, normalized_email,
                 display_name.strip(), hash_password(password), now, now),
            )
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    _migrate_legacy_files(user_id)
    return _public(row)


def _migrate_legacy_files(user_id: str) -> None:
    """Move pre-v2.3 single-user files into the owner's isolated directory."""
    settings = config.settings()
    target = config.user_dir(user_id)
    target.mkdir(parents=True, exist_ok=True)
    sources = {
        Path(settings["profile_path"]): target / "PROFILE.json",
        Path(settings["cv"]["master_path"]): target / "CV_MASTER.json",
        Path(settings["data_dir"]) / "source_cv.pdf": target / "source_cv.pdf",
        Path(settings["cv"]["out_dir"]): target / "cv",
        Path(settings["data_dir"]) / "cv-runs": target / "cv-runs",
    }
    for source, destination in sources.items():
        if source == destination or not source.exists() or destination.exists():
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(destination))


def bootstrap_from_environment() -> dict | None:
    password = config.secret_value("JEV_AUTH_PASSWORD")
    if not password:
        return None
    with store._LOCK, store._connect() as conn:
        legacy = conn.execute(
            "SELECT active FROM users WHERE id = ?", (LEGACY_ADMIN_ID,),
        ).fetchone()
        total = int(conn.execute("SELECT COUNT(*) FROM users").fetchone()[0])
    if total == 0 or (legacy and not legacy["active"]):
        return create_first_admin(
            os.environ.get("JEV_ADMIN_USERNAME", "admin"), password,
            os.environ.get("JEV_ADMIN_EMAIL") or None,
            os.environ.get("JEV_ADMIN_DISPLAY_NAME", "Administrateur"),
        )
    return None


def bump_session_version(user_id: str) -> int:
    with store._LOCK, store._connect() as conn:
        conn.execute(
            "UPDATE users SET session_version = session_version + 1, updated_at = ? WHERE id = ?",
            (_now(), user_id),
        )
        row = conn.execute("SELECT session_version FROM users WHERE id = ?", (user_id,)).fetchone()
    if not row:
        raise AccountError("Utilisateur inconnu")
    return int(row["session_version"])


def change_password(user_id: str, current_password: str, new_password: str) -> None:
    with store._LOCK, store._connect() as conn:
        row = conn.execute(
            "SELECT password_hash FROM users WHERE id = ? AND active = 1", (user_id,),
        ).fetchone()
        if not row or not verify_password(current_password, row["password_hash"]):
            raise AccountError("Mot de passe actuel incorrect")
        conn.execute(
            "UPDATE users SET password_hash = ?, session_version = session_version + 1, "
            "updated_at = ? WHERE id = ?",
            (hash_password(new_password), _now(), user_id),
        )


def set_user_active(user_id: str, active: bool, actor_id: str) -> dict:
    if user_id == actor_id and not active:
        raise AccountError("Un administrateur ne peut pas désactiver son propre compte")
    with store._LOCK, store._connect() as conn:
        cursor = conn.execute(
            "UPDATE users SET active = ?, session_version = session_version + 1, updated_at = ? "
            "WHERE id = ?", (int(active), _now(), user_id),
        )
        if cursor.rowcount != 1:
            raise AccountError("Utilisateur inconnu")
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return _public(row)


def _user_storage_paths(user_id: str) -> tuple[Path, Path]:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", user_id):
        raise AccountError("Identifiant utilisateur invalide")
    users_root = (Path(config.settings()["data_dir"]) / "users").resolve()
    target = users_root / user_id
    if target.parent != users_root:
        raise AccountError("Répertoire utilisateur invalide")
    return users_root, target


def _remove_storage_path(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    else:
        shutil.rmtree(path)


def reconcile_deleted_user_files() -> dict[str, int]:
    """Recover or purge deletion staging directories left by a stopped process."""
    users_root = (Path(config.settings()["data_dir"]) / "users").resolve()
    result = {"restored": 0, "purged": 0, "failed": 0}
    if not users_root.is_dir():
        return result
    with store._LOCK, store._connect() as conn:
        for staged_path in users_root.iterdir():
            match = _DELETING_DIR.fullmatch(staged_path.name)
            if not match:
                continue
            user_id = match.group("user_id")
            exists = conn.execute("SELECT 1 FROM users WHERE id = ?", (user_id,)).fetchone()
            target_path = users_root / user_id
            try:
                if exists:
                    if target_path.exists() or target_path.is_symlink():
                        _LOGGER.warning(
                            "Deletion staging directory kept because user storage already exists: %s",
                            staged_path,
                        )
                        result["failed"] += 1
                    else:
                        os.replace(staged_path, target_path)
                        result["restored"] += 1
                else:
                    _remove_storage_path(staged_path)
                    result["purged"] += 1
            except OSError:
                _LOGGER.exception("Unable to reconcile user deletion staging directory: %s", staged_path)
                result["failed"] += 1
    return result


def delete_user(user_id: str, actor_id: str, confirmation: str) -> dict:
    """Delete another account, all owned database rows and its isolated files."""
    if user_id == actor_id:
        raise AccountError("Un administrateur ne peut pas supprimer son propre compte")

    staged_path: Path | None = None
    target_path: Path | None = None
    deleted_user: dict | None = None
    with store._LOCK:
        conn = store._connect()
        try:
            conn.commit()
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
            if not row:
                raise AccountError("Utilisateur inconnu")
            if confirmation != row["username"]:
                raise AccountError("Le nom d’utilisateur de confirmation est incorrect")
            active_work = conn.execute(
                "SELECT EXISTS(SELECT 1 FROM runs WHERE user_id = ? AND status = 'running') "
                "OR EXISTS(SELECT 1 FROM cv_jobs WHERE user_id = ? AND status = 'running') "
                "OR EXISTS(SELECT 1 FROM onboarding_jobs WHERE user_id = ? AND status = 'running')",
                (user_id, user_id, user_id),
            ).fetchone()[0]
            if active_work:
                raise AccountError("Suppression refusée pendant une tâche active de cet utilisateur")

            users_root, target_path = _user_storage_paths(user_id)
            if target_path.exists() or target_path.is_symlink():
                users_root.mkdir(parents=True, exist_ok=True)
                staged_path = users_root / f".deleting-{user_id}-{uuid.uuid4().hex}"
                os.replace(target_path, staged_path)

            # Delete children explicitly as a defensive guarantee, even though two relations cascade.
            conn.execute(
                "DELETE FROM results WHERE run_id IN (SELECT id FROM runs WHERE user_id = ?)",
                (user_id,),
            )
            conn.execute("DELETE FROM runs WHERE user_id = ?", (user_id,))
            conn.execute("DELETE FROM cv_jobs WHERE user_id = ?", (user_id,))
            conn.execute("DELETE FROM onboarding_jobs WHERE user_id = ?", (user_id,))
            conn.execute("DELETE FROM profile_versions WHERE user_id = ?", (user_id,))
            conn.execute(
                "DELETE FROM application_events WHERE application_id IN "
                "(SELECT id FROM applications WHERE user_id = ?)",
                (user_id,),
            )
            conn.execute("DELETE FROM applications WHERE user_id = ?", (user_id,))
            conn.execute("DELETE FROM invitations WHERE created_by = ?", (user_id,))
            conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
            deleted_user = _public(row)
            conn.commit()
        except Exception:
            conn.rollback()
            if staged_path and staged_path.exists() and target_path and not target_path.exists():
                os.replace(staged_path, target_path)
            raise
        finally:
            conn.close()

    cleanup_pending = False
    if staged_path:
        try:
            _remove_storage_path(staged_path)
        except OSError:
            cleanup_pending = True
            _LOGGER.exception(
                "User account deleted but staged files could not be purged: %s", staged_path,
            )
    assert deleted_user is not None
    deleted_user["cleanup_pending"] = cleanup_pending
    return deleted_user


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_invitation(created_by: str, email: str | None = None,
                      expires_hours: int = 72) -> dict:
    if not 1 <= int(expires_hours) <= 24 * 30:
        raise AccountError("La durée d’invitation doit être comprise entre 1 heure et 30 jours")
    normalized_email = normalize_email(email)
    token = secrets.token_urlsafe(32)
    invitation_id = uuid.uuid4().hex[:16]
    created_at = datetime.now().replace(microsecond=0)
    expires_at = created_at + timedelta(hours=int(expires_hours))
    with store._LOCK, store._connect() as conn:
        conn.execute(
            "INSERT INTO invitations (id, token_hash, email, created_by, created_at, expires_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (invitation_id, _token_hash(token), normalized_email, created_by,
             created_at.isoformat(), expires_at.isoformat()),
        )
    return {"id": invitation_id, "token": token, "email": normalized_email,
            "created_at": created_at.isoformat(), "expires_at": expires_at.isoformat()}


def list_invitations(created_by: str | None = None) -> list[dict]:
    query = (
        "SELECT id, email, created_by, created_at, expires_at, accepted_at, revoked_at "
        "FROM invitations"
    )
    params: tuple[object, ...] = ()
    if created_by:
        query += " WHERE created_by = ?"
        params = (created_by,)
    query += " ORDER BY created_at DESC"
    with store._LOCK, store._connect() as conn:
        rows = conn.execute(query, params).fetchall()
    return [dict(row) for row in rows]


def revoke_invitation(invitation_id: str) -> bool:
    with store._LOCK, store._connect() as conn:
        cursor = conn.execute(
            "UPDATE invitations SET revoked_at = ? WHERE id = ? AND accepted_at IS NULL "
            "AND revoked_at IS NULL", (_now(), invitation_id),
        )
        return cursor.rowcount == 1


def invitation_status(token: str) -> dict | None:
    with store._LOCK, store._connect() as conn:
        row = conn.execute(
            "SELECT id, email, expires_at, accepted_at, revoked_at FROM invitations "
            "WHERE token_hash = ?", (_token_hash(token),),
        ).fetchone()
    if not row:
        return None
    result = dict(row)
    result["valid"] = (
        not result["accepted_at"] and not result["revoked_at"]
        and result["expires_at"] > _now()
    )
    return result


def register_with_invitation(token: str, username: str, password: str,
                             email: str | None = None, display_name: str = "") -> dict:
    normalized_username = normalize_username(username)
    normalized_email = normalize_email(email)
    validate_password(password)
    now = _now()
    user_id = uuid.uuid4().hex[:16]
    password_hash = hash_password(password)
    with store._LOCK, store._connect() as conn:
        invitation = conn.execute(
            "SELECT * FROM invitations WHERE token_hash = ?", (_token_hash(token),),
        ).fetchone()
        if (not invitation or invitation["accepted_at"] or invitation["revoked_at"]
                or invitation["expires_at"] <= now):
            raise AccountError("Invitation invalide, expirée ou déjà utilisée")
        invited_email = normalize_email(invitation["email"])
        if invited_email and normalized_email != invited_email:
            raise AccountError("Cette invitation est réservée à une autre adresse email")
        cursor = conn.execute(
            "UPDATE invitations SET accepted_at = ? WHERE id = ? AND accepted_at IS NULL "
            "AND revoked_at IS NULL AND expires_at > ?", (now, invitation["id"], now),
        )
        if cursor.rowcount != 1:
            raise AccountError("Invitation déjà utilisée")
        try:
            conn.execute(
                "INSERT INTO users (id, username, username_normalized, email, email_normalized, "
                "display_name, password_hash, role, active, session_version, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, 'user', 1, 1, ?, ?)",
                (user_id, username.strip(), normalized_username, normalized_email, normalized_email,
                 display_name.strip(), password_hash, now, now),
            )
        except Exception as exc:
            if "UNIQUE constraint failed" in str(exc):
                raise AccountConflict("Ce nom d’utilisateur ou cette adresse email est déjà utilisé") from exc
            raise
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return _public(row)