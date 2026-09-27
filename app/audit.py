"""Persistent, privacy-conscious audit log for security-sensitive actions."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
from datetime import datetime, timedelta, timezone

from . import config, store

_EVENT = re.compile(r"^[a-z][a-z0-9_.-]{2,63}$")
_SUBJECT = re.compile(r"^[a-z][a-z0-9_.-]{1,31}$")
_ALLOWED_METADATA = {
    "active", "application_id", "backup_name", "changed", "cleanup_pending",
    "count", "email_reserved", "fingerprint", "job_id", "kind", "role",
    "run_id", "send_email", "status", "username", "version_id",
}
_FALLBACK_KEY = secrets.token_bytes(32)


class AuditError(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _clean_identifier(value: str | None, maximum: int = 128) -> str | None:
    text = (value or "").strip()
    if not text:
        return None
    return text[:maximum]


def _metadata(value: dict | None) -> str:
    cleaned: dict[str, object] = {}
    for key, item in (value or {}).items():
        if key not in _ALLOWED_METADATA or len(cleaned) >= 16:
            continue
        if isinstance(item, bool) or item is None:
            cleaned[key] = item
        elif isinstance(item, (int, float)):
            cleaned[key] = item
        elif isinstance(item, str):
            cleaned[key] = item[:256]
        elif isinstance(item, (list, tuple)):
            cleaned[key] = [str(entry)[:128] for entry in item[:10]]
    return json.dumps(cleaned, ensure_ascii=False, separators=(",", ":"))


def fingerprint(*parts: str) -> str:
    """Stable HMAC fingerprint without retaining identifiers or client addresses."""
    material = config.secret_value("JEV_SESSION_SECRET") or config.secret_value("JEV_AUTH_PASSWORD")
    key = material.encode("utf-8") if material else _FALLBACK_KEY
    normalized = "\x1f".join((part or "").strip().lower() for part in parts)
    return hmac.new(key, normalized.encode("utf-8"), hashlib.sha256).hexdigest()[:24]


def record(event_type: str, *, actor_id: str | None = None,
           subject_type: str | None = None, subject_id: str | None = None,
           success: bool = True, metadata: dict | None = None) -> str:
    if not _EVENT.fullmatch(event_type or ""):
        raise AuditError("Type d’événement d’audit invalide")
    if subject_type and not _SUBJECT.fullmatch(subject_type):
        raise AuditError("Type de sujet d’audit invalide")
    event_id = secrets.token_hex(12)
    with store._LOCK, store._connect() as conn:
        conn.execute(
            "INSERT INTO audit_events (id, created_at, actor_user_id, event_type, subject_type, "
            "subject_id, success, metadata) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (event_id, _now(), _clean_identifier(actor_id), event_type, subject_type,
             _clean_identifier(subject_id), int(success), _metadata(metadata)),
        )
    return event_id


def list_events(*, event_type: str | None = None, actor_id: str | None = None,
                success: bool | None = None, days: int | None = None,
                limit: int = 50, offset: int = 0) -> dict:
    clauses: list[str] = []
    params: list[object] = []
    if event_type:
        clauses.append("audit_events.event_type = ?")
        params.append(event_type)
    if actor_id:
        clauses.append("audit_events.actor_user_id = ?")
        params.append(actor_id)
    if success is not None:
        clauses.append("audit_events.success = ?")
        params.append(int(success))
    if days is not None:
        clauses.append("audit_events.created_at >= ?")
        params.append((datetime.now(timezone.utc) - timedelta(days=max(1, min(days, 3650)))).isoformat(
            timespec="seconds"))
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    size = max(1, min(int(limit), 200))
    start = max(0, int(offset))
    with store._LOCK, store._connect() as conn:
        total = int(conn.execute(
            "SELECT COUNT(*) FROM audit_events" + where, params,
        ).fetchone()[0])
        rows = conn.execute(
            "SELECT audit_events.id, audit_events.created_at, audit_events.actor_user_id, "
            "users.username AS actor_username, audit_events.event_type, "
            "audit_events.subject_type, audit_events.subject_id, audit_events.success, "
            "audit_events.metadata FROM audit_events "
            "LEFT JOIN users ON users.id = audit_events.actor_user_id" + where +
            " ORDER BY audit_events.created_at DESC, audit_events.id DESC LIMIT ? OFFSET ?",
            (*params, size, start),
        ).fetchall()
    events = []
    for row in rows:
        item = dict(row)
        item["success"] = bool(item["success"])
        try:
            item["metadata"] = json.loads(item["metadata"])
        except (TypeError, json.JSONDecodeError):
            item["metadata"] = {}
        events.append(item)
    return {"events": events, "total": total, "limit": size, "offset": start}


def event_types() -> list[str]:
    with store._LOCK, store._connect() as conn:
        rows = conn.execute(
            "SELECT DISTINCT event_type FROM audit_events ORDER BY event_type"
        ).fetchall()
    return [str(row[0]) for row in rows]


def prune(retention_days: int | None = None) -> int:
    days = retention_days or int(config.settings()["audit"]["retention_days"])
    cutoff = (datetime.now(timezone.utc) - timedelta(days=max(1, days))).isoformat(timespec="seconds")
    with store._LOCK, store._connect() as conn:
        cursor = conn.execute("DELETE FROM audit_events WHERE created_at < ?", (cutoff,))
        return cursor.rowcount
