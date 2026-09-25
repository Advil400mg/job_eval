"""SQLite persistence for evaluation runs and CV jobs."""

from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
import time
import uuid
from datetime import date
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from . import config

DB_PATH = str(config.settings()["db_file"])
_LOCK = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    urls TEXT NOT NULL,
    status TEXT NOT NULL,
    progress INTEGER NOT NULL DEFAULT 0,
    total INTEGER NOT NULL DEFAULT 0,
    started_at TEXT,
    updated_at TEXT,
    attempts INTEGER NOT NULL DEFAULT 1,
    last_error TEXT,
    cancel_requested INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS results (
    run_id TEXT NOT NULL,
    url TEXT NOT NULL,
    created_at TEXT NOT NULL,
    status TEXT NOT NULL,
    payload TEXT NOT NULL,
    normalized_url TEXT,
    title TEXT,
    company TEXT,
    location TEXT,
    decision_status TEXT,
    score REAL,
    published_at TEXT,
    PRIMARY KEY (run_id, url)
);
CREATE TABLE IF NOT EXISTS cv_jobs (
    id TEXT PRIMARY KEY,
    url TEXT NOT NULL,
    created_at TEXT NOT NULL,
    status TEXT NOT NULL,
    payload TEXT,
    started_at TEXT,
    updated_at TEXT,
    attempts INTEGER NOT NULL DEFAULT 1,
    last_error TEXT,
    cancel_requested INTEGER NOT NULL DEFAULT 0,
    send_email INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS profile_versions (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    revision TEXT NOT NULL UNIQUE,
    source TEXT NOT NULL,
    payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS applications (
    id TEXT PRIMARY KEY,
    normalized_url TEXT NOT NULL UNIQUE,
    url TEXT NOT NULL,
    title TEXT,
    company TEXT,
    location TEXT,
    status TEXT NOT NULL,
    notes TEXT NOT NULL DEFAULT '',
    contact_name TEXT NOT NULL DEFAULT '',
    contact_email TEXT NOT NULL DEFAULT '',
    applied_at TEXT,
    follow_up_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    revision INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS application_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    application_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    event_type TEXT NOT NULL,
    from_status TEXT,
    to_status TEXT,
    payload TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY (application_id) REFERENCES applications(id) ON DELETE CASCADE
);
"""

APPLICATION_STATUSES = ("to_review", "cv_ready", "applied", "interview", "rejected", "offer")

_RESULT_COLUMNS = {
    "normalized_url": "TEXT",
    "title": "TEXT",
    "company": "TEXT",
    "location": "TEXT",
    "decision_status": "TEXT",
    "score": "REAL",
    "published_at": "TEXT",
}
_RUN_COLUMNS = {
    "started_at": "TEXT",
    "updated_at": "TEXT",
    "attempts": "INTEGER NOT NULL DEFAULT 1",
    "last_error": "TEXT",
    "cancel_requested": "INTEGER NOT NULL DEFAULT 0",
}
_CV_COLUMNS = {
    "started_at": "TEXT",
    "updated_at": "TEXT",
    "attempts": "INTEGER NOT NULL DEFAULT 1",
    "last_error": "TEXT",
    "cancel_requested": "INTEGER NOT NULL DEFAULT 0",
    "send_email": "INTEGER NOT NULL DEFAULT 0",
}
_TRACKING_PARAMS = {
    "fbclid", "gclid", "mc_cid", "mc_eid", "ref", "referrer", "source",
}


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def normalize_url(url: str) -> str:
    """Canonical key used to group repeated evaluations without changing the source URL."""
    try:
        parsed = urlsplit((url or "").strip())
    except ValueError:
        return (url or "").strip()
    query = []
    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        lowered = key.lower()
        if lowered.startswith("utm_") or lowered in _TRACKING_PARAMS:
            continue
        query.append((key, value))
    path = re.sub(r"/{2,}", "/", parsed.path or "/")
    if path != "/":
        path = path.rstrip("/")
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), path,
                       urlencode(sorted(query)), ""))


def _payload_columns(url: str, status: str, payload: dict) -> tuple[object, ...]:
    jev = payload.get("jev") or {}
    decision = payload.get("decision") or {}
    decision_status = decision.get("status") or ("rejected" if status == "ok" else status)
    score = jev.get("global_score")
    return (
        normalize_url(url), payload.get("title"), payload.get("company"),
        payload.get("location"), decision_status,
        score if isinstance(score, (int, float)) else None, payload.get("published_at"),
    )


def _add_columns(conn: sqlite3.Connection, table: str, definitions: dict[str, str]) -> None:
    columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    for name, sql_type in definitions.items():
        if name not in columns:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {sql_type}")


def _migrate(conn: sqlite3.Connection) -> None:
    _add_columns(conn, "runs", _RUN_COLUMNS)
    _add_columns(conn, "results", _RESULT_COLUMNS)
    _add_columns(conn, "cv_jobs", _CV_COLUMNS)
    conn.execute("UPDATE runs SET updated_at = COALESCE(updated_at, created_at)")
    conn.execute("UPDATE cv_jobs SET updated_at = COALESCE(updated_at, created_at)")
    rows = conn.execute(
        "SELECT run_id, url, status, payload FROM results WHERE normalized_url IS NULL"
    ).fetchall()
    for row in rows:
        try:
            payload = json.loads(row["payload"])
        except (TypeError, json.JSONDecodeError):
            payload = {}
        values = _payload_columns(row["url"], row["status"], payload)
        conn.execute(
            "UPDATE results SET normalized_url=?, title=?, company=?, location=?, "
            "decision_status=?, score=?, published_at=? WHERE run_id=? AND url=?",
            (*values, row["run_id"], row["url"]),
        )
    conn.executescript("""
        CREATE INDEX IF NOT EXISTS idx_runs_created ON runs(created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_runs_status ON runs(status, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_results_normalized ON results(normalized_url, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_results_decision ON results(decision_status, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_results_score ON results(score DESC);
        CREATE INDEX IF NOT EXISTS idx_results_company ON results(company);
        CREATE INDEX IF NOT EXISTS idx_results_location ON results(location);
        CREATE INDEX IF NOT EXISTS idx_cv_jobs_status ON cv_jobs(status, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_cv_jobs_url ON cv_jobs(url, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_profile_versions_created ON profile_versions(created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_applications_status ON applications(status, updated_at DESC);
        CREATE INDEX IF NOT EXISTS idx_applications_follow_up ON applications(follow_up_at, status);
        CREATE INDEX IF NOT EXISTS idx_applications_updated ON applications(updated_at DESC);
        CREATE INDEX IF NOT EXISTS idx_application_events_app ON application_events(application_id, id DESC);
    """)
    conn.execute("PRAGMA user_version = 4")


def _connect() -> sqlite3.Connection:
    directory = os.path.dirname(DB_PATH)
    if directory:
        os.makedirs(directory, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 30000")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.executescript(SCHEMA)
    _migrate(conn)
    return conn


def create_run(urls: list[str]) -> str:
    run_id = uuid.uuid4().hex[:12]
    now = _now()
    with _LOCK, _connect() as conn:
        conn.execute(
            "INSERT INTO runs (id, created_at, urls, status, progress, total, started_at, "
            "updated_at, attempts, cancel_requested) "
            "VALUES (?, ?, ?, 'running', 0, ?, ?, ?, 1, 0)",
            (run_id, now, json.dumps(urls, ensure_ascii=False), len(urls), now, now),
        )
    return run_id


def set_total(run_id: str, total: int) -> None:
    with _LOCK, _connect() as conn:
        conn.execute("UPDATE runs SET total = ?, updated_at = ? WHERE id = ?", (total, _now(), run_id))


def save_result(run_id: str, url: str, status: str, payload: dict) -> None:
    indexed = _payload_columns(url, status, payload)
    with _LOCK, _connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO results "
            "(run_id, url, created_at, status, payload, normalized_url, title, company, "
            "location, decision_status, score, published_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (run_id, url, _now(), status,
             json.dumps(payload, ensure_ascii=False), *indexed),
        )
        conn.execute(
            "UPDATE runs SET progress = (SELECT COUNT(*) FROM results WHERE run_id = ?), "
            "updated_at = ? WHERE id = ?", (run_id, _now(), run_id),
        )


def finish_run(run_id: str, status: str = "done", last_error: str | None = None) -> None:
    with _LOCK, _connect() as conn:
        conn.execute(
            "UPDATE runs SET status = ?, updated_at = ?, last_error = ? WHERE id = ?",
            (status, _now(), last_error, run_id),
        )


def resume_run(run_id: str) -> bool:
    with _LOCK, _connect() as conn:
        cursor = conn.execute(
            "UPDATE runs SET status = 'running', started_at = ?, updated_at = ?, "
            "attempts = attempts + 1, last_error = NULL, cancel_requested = 0 "
            "WHERE id = ? AND status IN ('running', 'failed', 'interrupted', 'cancelled')",
            (_now(), _now(), run_id),
        )
        return cursor.rowcount == 1


def request_run_cancel(run_id: str) -> bool:
    with _LOCK, _connect() as conn:
        cursor = conn.execute(
            "UPDATE runs SET cancel_requested = 1, updated_at = ? "
            "WHERE id = ? AND status = 'running'", (_now(), run_id),
        )
        return cursor.rowcount == 1


def run_cancel_requested(run_id: str) -> bool:
    with _LOCK, _connect() as conn:
        row = conn.execute("SELECT cancel_requested FROM runs WHERE id = ?", (run_id,)).fetchone()
    return bool(row and row["cancel_requested"])


def running_runs() -> list[dict]:
    return list_runs(limit=200, status="running")


def missing_run_urls(run_id: str) -> list[str]:
    with _LOCK, _connect() as conn:
        row = conn.execute("SELECT urls FROM runs WHERE id = ?", (run_id,)).fetchone()
        completed = {item["url"] for item in conn.execute(
            "SELECT url FROM results WHERE run_id = ?", (run_id,),
        ).fetchall()}
    if not row:
        return []
    return [url for url in json.loads(row["urls"]) if url not in completed]


def get_run(run_id: str) -> dict | None:
    with _LOCK, _connect() as conn:
        row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        if not row:
            return None
        results = conn.execute(
            "SELECT payload FROM results WHERE run_id = ? ORDER BY created_at", (run_id,)
        ).fetchall()
    run = dict(row)
    run["urls"] = json.loads(run["urls"])
    run["results"] = [json.loads(r["payload"]) for r in results]
    return run


def list_runs(limit: int = 20, offset: int = 0, status: str | None = None) -> list[dict]:
    limit = max(1, min(int(limit), 200))
    offset = max(0, int(offset))
    query = (
        "SELECT id, created_at, status, progress, total, urls, started_at, updated_at, "
        "attempts, last_error, cancel_requested FROM runs"
    )
    params: list[object] = []
    if status:
        query += " WHERE status = ?"
        params.append(status)
    query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
    params.extend((limit, offset))
    with _LOCK, _connect() as conn:
        rows = conn.execute(query, params).fetchall()
    output = []
    for row in rows:
        item = dict(row)
        item["urls"] = json.loads(item["urls"])
        output.append(item)
    return output


def count_runs(status: str | None = None) -> int:
    query = "SELECT COUNT(*) FROM runs"
    params: tuple[object, ...] = ()
    if status:
        query += " WHERE status = ?"
        params = (status,)
    with _LOCK, _connect() as conn:
        return int(conn.execute(query, params).fetchone()[0])


def all_results() -> list[dict]:
    """Every stored result, newest run first, tagged with its run."""
    with _LOCK, _connect() as conn:
        rows = conn.execute(
            "SELECT results.run_id, results.created_at, results.payload, "
            "runs.created_at AS run_created_at "
            "FROM results JOIN runs ON runs.id = results.run_id "
            "ORDER BY runs.created_at DESC, results.created_at DESC",
        ).fetchall()
    output = []
    for row in rows:
        item = json.loads(row["payload"])
        item["run_id"] = row["run_id"]
        item["created_at"] = row["created_at"]
        item["run_created_at"] = row["run_created_at"]
        output.append(item)
    return output


def results_for_analytics(view: str = "latest", days: int | None = None) -> list[dict]:
    conditions = ["rn = 1"] if view != "all" else ["1 = 1"]
    params: list[object] = []
    if days:
        cutoff = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time() - days * 86400))
        conditions.append("run_created_at >= ?")
        params.append(cutoff)
    sql = f"""
        WITH ranked AS (
            SELECT results.*, runs.created_at AS run_created_at,
                   ROW_NUMBER() OVER (
                       PARTITION BY COALESCE(results.normalized_url, results.url)
                       ORDER BY runs.created_at DESC, results.created_at DESC
                   ) AS rn
            FROM results JOIN runs ON runs.id = results.run_id
        )
        SELECT run_id, created_at, run_created_at, payload FROM ranked
        WHERE {' AND '.join(conditions)}
        ORDER BY run_created_at DESC, created_at DESC
    """
    with _LOCK, _connect() as conn:
        rows = conn.execute(sql, params).fetchall()
    output = []
    for row in rows:
        item = json.loads(row["payload"])
        item["run_id"] = row["run_id"]
        item["created_at"] = row["created_at"]
        item["run_created_at"] = row["run_created_at"]
        output.append(item)
    return output


def runs_with_results(limit: int = 50, offset: int = 0,
                      status: str | None = None) -> list[dict]:
    """Runs (newest first) with their decoded results, for history summaries."""
    runs = list_runs(limit=limit, offset=offset, status=status)
    with _LOCK, _connect() as conn:
        for run in runs:
            rows = conn.execute(
                "SELECT payload FROM results WHERE run_id = ? ORDER BY created_at",
                (run["id"],),
            ).fetchall()
            run["results"] = [json.loads(r["payload"]) for r in rows]
    return runs


def _offer_query_parts(filters: dict) -> tuple[list[str], list[object]]:
    conditions: list[str] = []
    params: list[object] = []
    if filters.get("view", "latest") != "all":
        conditions.append("rn = 1")
    query = str(filters.get("q") or "").strip().lower()
    if query:
        token = f"%{query}%"
        conditions.append(
            "(LOWER(COALESCE(title, '')) LIKE ? OR LOWER(COALESCE(company, '')) LIKE ? "
            "OR LOWER(COALESCE(location, '')) LIKE ? OR LOWER(url) LIKE ? "
            "OR LOWER(payload) LIKE ?)"
        )
        params.extend([token] * 5)
    for key in ("status", "company", "location", "run_id"):
        if filters.get(key):
            column = "decision_status" if key == "status" else key
            conditions.append(f"{column} = ?")
            params.append(filters[key])
    if filters.get("score_min") is not None:
        conditions.append("score >= ?")
        params.append(float(filters["score_min"]))
    if filters.get("score_max") is not None:
        conditions.append("score <= ?")
        params.append(float(filters["score_max"]))
    if filters.get("scored") == "yes":
        conditions.append("score IS NOT NULL")
    elif filters.get("scored") == "no":
        conditions.append("score IS NULL")
    if filters.get("has_cv") == "yes":
        conditions.append(
            "EXISTS (SELECT 1 FROM cv_jobs c WHERE c.url = ranked.url AND c.status = 'done')"
        )
    elif filters.get("has_cv") == "no":
        conditions.append(
            "NOT EXISTS (SELECT 1 FROM cv_jobs c WHERE c.url = ranked.url AND c.status = 'done')"
        )
    return conditions or ["1 = 1"], params


def query_offers(page: int = 1, page_size: int = 50, **filters) -> dict:
    page = max(1, int(page))
    page_size = max(10, min(int(page_size), 100))
    conditions, params = _offer_query_parts(filters)
    cte = """
        WITH ranked AS (
            SELECT results.*, runs.created_at AS run_created_at,
                   ROW_NUMBER() OVER (
                       PARTITION BY COALESCE(results.normalized_url, results.url)
                       ORDER BY runs.created_at DESC, results.created_at DESC
                   ) AS rn,
                   COUNT(*) OVER (
                       PARTITION BY COALESCE(results.normalized_url, results.url)
                   ) AS evaluation_count
            FROM results JOIN runs ON runs.id = results.run_id
        )
    """
    sort_map = {
        "newest": "run_created_at DESC, created_at DESC",
        "score_desc": "score IS NULL, score DESC, run_created_at DESC",
        "score_asc": "score IS NULL, score ASC, run_created_at DESC",
        "company": "LOWER(COALESCE(company, '')) ASC, run_created_at DESC",
        "published_desc": "published_at IS NULL, published_at DESC, run_created_at DESC",
    }
    order_by = sort_map.get(str(filters.get("sort") or "newest"), sort_map["newest"])
    where = " AND ".join(conditions)
    with _LOCK, _connect() as conn:
        total = int(conn.execute(f"{cte} SELECT COUNT(*) FROM ranked WHERE {where}", params).fetchone()[0])
        rows = conn.execute(
            f"{cte} SELECT * FROM ranked WHERE {where} ORDER BY {order_by} LIMIT ? OFFSET ?",
            [*params, page_size, (page - 1) * page_size],
        ).fetchall()
    items = []
    for row in rows:
        item = json.loads(row["payload"])
        item["run_id"] = row["run_id"]
        item["created_at"] = row["created_at"]
        item["run_created_at"] = row["run_created_at"]
        item["evaluation_count"] = row["evaluation_count"]
        items.append(item)
    pages = max(1, (total + page_size - 1) // page_size)
    return {"items": items, "page": page, "page_size": page_size,
            "total": total, "pages": pages}


def offer_facets(view: str = "latest") -> dict:
    rank_condition = "rn = 1" if view != "all" else "1 = 1"
    cte = """
        WITH ranked AS (
            SELECT results.*,
                   ROW_NUMBER() OVER (
                       PARTITION BY COALESCE(normalized_url, url)
                       ORDER BY created_at DESC
                   ) AS rn
            FROM results
        )
    """
    with _LOCK, _connect() as conn:
        statuses = conn.execute(
            f"{cte} SELECT decision_status, COUNT(*) AS count FROM ranked WHERE {rank_condition} "
            "GROUP BY decision_status ORDER BY count DESC"
        ).fetchall()
        companies = conn.execute(
            f"{cte} SELECT company, COUNT(*) AS count FROM ranked WHERE {rank_condition} "
            "AND company IS NOT NULL AND company != '' "
            "GROUP BY company ORDER BY count DESC, company LIMIT 100"
        ).fetchall()
        locations = conn.execute(
            f"{cte} SELECT location, COUNT(*) AS count FROM ranked WHERE {rank_condition} "
            "AND location IS NOT NULL AND location != '' "
            "GROUP BY location ORDER BY count DESC, location LIMIT 100"
        ).fetchall()
    return {
        "statuses": {row["decision_status"] or "unknown": row["count"] for row in statuses},
        "companies": [dict(row) for row in companies],
        "locations": [dict(row) for row in locations],
    }


def offer_history(url: str) -> list[dict]:
    key = normalize_url(url)
    with _LOCK, _connect() as conn:
        rows = conn.execute(
            "SELECT results.run_id, results.created_at, results.payload, "
            "runs.created_at AS run_created_at FROM results "
            "JOIN runs ON runs.id = results.run_id "
            "WHERE results.normalized_url = ? ORDER BY runs.created_at DESC, results.created_at DESC",
            (key,),
        ).fetchall()
    output = []
    for row in rows:
        item = json.loads(row["payload"])
        item["run_id"] = row["run_id"]
        item["created_at"] = row["created_at"]
        item["run_created_at"] = row["run_created_at"]
        output.append(item)
    return output


def save_profile_version(profile: dict, revision: str, source: str) -> dict:
    version_id = uuid.uuid4().hex[:12]
    created_at = _now()
    payload = json.dumps(profile, ensure_ascii=False, sort_keys=True)
    with _LOCK, _connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO profile_versions (id, created_at, revision, source, payload) "
            "VALUES (?, ?, ?, ?, ?)",
            (version_id, created_at, revision, source, payload),
        )
        row = conn.execute(
            "SELECT id, created_at, revision, source FROM profile_versions WHERE revision = ?",
            (revision,),
        ).fetchone()
    return dict(row)


def list_profile_versions(limit: int = 50) -> list[dict]:
    limit = max(1, min(int(limit), 200))
    with _LOCK, _connect() as conn:
        rows = conn.execute(
            "SELECT id, created_at, revision, source FROM profile_versions "
            "ORDER BY created_at DESC, rowid DESC LIMIT ?", (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def get_profile_version(version_id: str) -> dict | None:
    with _LOCK, _connect() as conn:
        row = conn.execute("SELECT * FROM profile_versions WHERE id = ?", (version_id,)).fetchone()
    if not row:
        return None
    version = dict(row)
    version["profile"] = json.loads(version.pop("payload"))
    return version


def latest_offer_metadata(url: str) -> dict:
    key = normalize_url(url)
    with _LOCK, _connect() as conn:
        row = conn.execute(
            "SELECT url, title, company, location FROM results WHERE normalized_url = ? "
            "ORDER BY created_at DESC LIMIT 1", (key,),
        ).fetchone()
    return dict(row) if row else {"url": url, "title": "", "company": "", "location": ""}


def _application_event(conn: sqlite3.Connection, application_id: str, event_type: str,
                       from_status: str | None, to_status: str | None,
                       payload: dict | None = None) -> None:
    conn.execute(
        "INSERT INTO application_events "
        "(application_id, created_at, event_type, from_status, to_status, payload) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (application_id, _now(), event_type, from_status, to_status,
         json.dumps(payload or {}, ensure_ascii=False)),
    )


def _application_row(row: sqlite3.Row) -> dict:
    item = dict(row)
    item["overdue"] = bool(
        item.get("follow_up_at") and item["follow_up_at"] < date.today().isoformat()
        and item.get("status") not in ("rejected", "offer")
    )
    return item


def create_application(url: str, status: str = "to_review", **metadata: str) -> dict:
    if status not in APPLICATION_STATUSES:
        raise ValueError("statut de candidature invalide")
    key = normalize_url(url)
    if not key:
        raise ValueError("URL de candidature invalide")
    known = latest_offer_metadata(url)
    now = _now()
    application_id = uuid.uuid4().hex[:12]
    values = {
        "url": str(metadata.get("url") or known.get("url") or url).strip(),
        "title": str(metadata.get("title") or known.get("title") or "").strip(),
        "company": str(metadata.get("company") or known.get("company") or "").strip(),
        "location": str(metadata.get("location") or known.get("location") or "").strip(),
    }
    with _LOCK, _connect() as conn:
        existing = conn.execute(
            "SELECT * FROM applications WHERE normalized_url = ?", (key,),
        ).fetchone()
        if existing:
            return _application_row(existing)
        conn.execute(
            "INSERT INTO applications "
            "(id, normalized_url, url, title, company, location, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (application_id, key, values["url"], values["title"], values["company"],
             values["location"], status, now, now),
        )
        _application_event(conn, application_id, "created", None, status)
        row = conn.execute("SELECT * FROM applications WHERE id = ?", (application_id,)).fetchone()
    return _application_row(row)


def get_application(application_id: str) -> dict | None:
    with _LOCK, _connect() as conn:
        row = conn.execute("SELECT * FROM applications WHERE id = ?", (application_id,)).fetchone()
    return _application_row(row) if row else None


def application_for_url(url: str) -> dict | None:
    with _LOCK, _connect() as conn:
        row = conn.execute(
            "SELECT * FROM applications WHERE normalized_url = ?", (normalize_url(url),),
        ).fetchone()
    return _application_row(row) if row else None


def applications_for_urls(urls: list[str]) -> dict[str, dict]:
    keys = list(dict.fromkeys(normalize_url(url) for url in urls if url))
    if not keys:
        return {}
    output: dict[str, dict] = {}
    with _LOCK, _connect() as conn:
        for start in range(0, len(keys), 500):
            chunk = keys[start:start + 500]
            placeholders = ",".join("?" for _ in chunk)
            rows = conn.execute(
                f"SELECT * FROM applications WHERE normalized_url IN ({placeholders})", chunk,
            ).fetchall()
            for row in rows:
                output[row["normalized_url"]] = _application_row(row)
    return output


def update_application(application_id: str, changes: dict,
                       expected_revision: int | None = None) -> dict | None:
    allowed = {
        "status", "notes", "contact_name", "contact_email", "applied_at", "follow_up_at",
        "title", "company", "location",
    }
    updates = {key: changes[key] for key in allowed if key in changes}
    if "status" in updates and updates["status"] not in APPLICATION_STATUSES:
        raise ValueError("statut de candidature invalide")
    if not updates:
        return get_application(application_id)
    with _LOCK, _connect() as conn:
        current = conn.execute("SELECT * FROM applications WHERE id = ?", (application_id,)).fetchone()
        if not current:
            return None
        if expected_revision is not None and int(current["revision"]) != int(expected_revision):
            raise RuntimeError("candidature modifiée depuis son chargement")
        old_status = current["status"]
        fields = [f"{key} = ?" for key in updates]
        values = [updates[key] for key in updates]
        fields.extend(["updated_at = ?", "revision = revision + 1"])
        values.extend([_now(), application_id])
        conn.execute(f"UPDATE applications SET {', '.join(fields)} WHERE id = ?", values)
        new_status = updates.get("status", old_status)
        _application_event(
            conn, application_id, "status_changed" if new_status != old_status else "updated",
            old_status, new_status, updates,
        )
        row = conn.execute("SELECT * FROM applications WHERE id = ?", (application_id,)).fetchone()
    return _application_row(row)


def delete_application(application_id: str) -> bool:
    with _LOCK, _connect() as conn:
        conn.execute("DELETE FROM application_events WHERE application_id = ?", (application_id,))
        cursor = conn.execute("DELETE FROM applications WHERE id = ?", (application_id,))
        return cursor.rowcount == 1


def application_events(application_id: str, limit: int = 100) -> list[dict]:
    limit = max(1, min(int(limit), 500))
    with _LOCK, _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM application_events WHERE application_id = ? "
            "ORDER BY id DESC LIMIT ?", (application_id, limit),
        ).fetchall()
    events = []
    for row in rows:
        event = dict(row)
        event["payload"] = json.loads(event["payload"] or "{}")
        events.append(event)
    return events


def list_applications(page: int = 1, page_size: int = 25, q: str = "",
                      status: str = "", due: str = "", sort: str = "updated") -> dict:
    page = max(1, int(page))
    page_size = max(5, min(int(page_size), 100))
    conditions: list[str] = []
    params: list[object] = []
    if status:
        conditions.append("status = ?")
        params.append(status)
    if q.strip():
        token = f"%{q.strip().lower()}%"
        conditions.append(
            "(LOWER(title) LIKE ? OR LOWER(company) LIKE ? OR LOWER(location) LIKE ? "
            "OR LOWER(notes) LIKE ? OR LOWER(contact_name) LIKE ? OR LOWER(contact_email) LIKE ?)"
        )
        params.extend([token] * 6)
    today = date.today().isoformat()
    if due == "overdue":
        conditions.append("follow_up_at IS NOT NULL AND follow_up_at < ? AND status NOT IN ('rejected','offer')")
        params.append(today)
    elif due == "upcoming":
        conditions.append("follow_up_at IS NOT NULL AND follow_up_at >= ? AND status NOT IN ('rejected','offer')")
        params.append(today)
    where = " AND ".join(conditions) if conditions else "1 = 1"
    order = {
        "updated": "updated_at DESC",
        "follow_up": "follow_up_at IS NULL, follow_up_at ASC, updated_at DESC",
        "company": "LOWER(company) ASC, updated_at DESC",
        "status": "status ASC, updated_at DESC",
    }.get(sort, "updated_at DESC")
    with _LOCK, _connect() as conn:
        total = int(conn.execute(f"SELECT COUNT(*) FROM applications WHERE {where}", params).fetchone()[0])
        rows = conn.execute(
            f"SELECT * FROM applications WHERE {where} ORDER BY {order} LIMIT ? OFFSET ?",
            [*params, page_size, (page - 1) * page_size],
        ).fetchall()
        counts = conn.execute(
            "SELECT status, COUNT(*) AS count FROM applications GROUP BY status"
        ).fetchall()
    return {
        "applications": [_application_row(row) for row in rows],
        "page": page, "page_size": page_size, "total": total,
        "pages": max(1, (total + page_size - 1) // page_size),
        "counts": {row["status"]: row["count"] for row in counts},
    }


def all_applications() -> list[dict]:
    with _LOCK, _connect() as conn:
        rows = conn.execute("SELECT * FROM applications ORDER BY updated_at DESC").fetchall()
    return [_application_row(row) for row in rows]


def mark_application_cv_ready(url: str) -> bool:
    key = normalize_url(url)
    with _LOCK, _connect() as conn:
        current = conn.execute(
            "SELECT * FROM applications WHERE normalized_url = ?", (key,),
        ).fetchone()
        if not current or current["status"] != "to_review":
            return False
        conn.execute(
            "UPDATE applications SET status = 'cv_ready', updated_at = ?, revision = revision + 1 "
            "WHERE id = ?", (_now(), current["id"]),
        )
        _application_event(conn, current["id"], "cv_ready", "to_review", "cv_ready")
        return True


def create_cv_job(url: str, send_email: bool = False) -> str:
    job_id = uuid.uuid4().hex[:12]
    now = _now()
    with _LOCK, _connect() as conn:
        conn.execute(
            "INSERT INTO cv_jobs (id, url, created_at, status, started_at, updated_at, "
            "attempts, cancel_requested, send_email) "
            "VALUES (?, ?, ?, 'running', ?, ?, 1, 0, ?)",
            (job_id, url, now, now, now, int(send_email)),
        )
    return job_id


def finish_cv_job(job_id: str, status: str, payload: dict | None = None,
                  last_error: str | None = None) -> None:
    with _LOCK, _connect() as conn:
        conn.execute(
            "UPDATE cv_jobs SET status = ?, payload = ?, updated_at = ?, last_error = ? "
            "WHERE id = ?",
            (status, json.dumps(payload or {}, ensure_ascii=False), _now(), last_error, job_id),
        )


def restart_cv_job(job_id: str) -> bool:
    with _LOCK, _connect() as conn:
        cursor = conn.execute(
            "UPDATE cv_jobs SET status = 'running', payload = NULL, started_at = ?, "
            "updated_at = ?, attempts = attempts + 1, last_error = NULL, cancel_requested = 0 "
            "WHERE id = ? AND status IN ('failed', 'interrupted', 'cancelled')",
            (_now(), _now(), job_id),
        )
        return cursor.rowcount == 1


def request_cv_cancel(job_id: str) -> bool:
    with _LOCK, _connect() as conn:
        cursor = conn.execute(
            "UPDATE cv_jobs SET cancel_requested = 1, updated_at = ? "
            "WHERE id = ? AND status = 'running'", (_now(), job_id),
        )
        return cursor.rowcount == 1


def cv_cancel_requested(job_id: str) -> bool:
    with _LOCK, _connect() as conn:
        row = conn.execute("SELECT cancel_requested FROM cv_jobs WHERE id = ?", (job_id,)).fetchone()
    return bool(row and row["cancel_requested"])


def interrupt_running_cv_jobs() -> int:
    payload = json.dumps({"error": "Génération interrompue par un redémarrage"}, ensure_ascii=False)
    with _LOCK, _connect() as conn:
        cursor = conn.execute(
            "UPDATE cv_jobs SET status = 'interrupted', payload = ?, updated_at = ?, "
            "last_error = ? WHERE status = 'running'",
            (payload, _now(), "redémarrage de l’application"),
        )
        return cursor.rowcount


def get_cv_job(job_id: str) -> dict | None:
    with _LOCK, _connect() as conn:
        row = conn.execute("SELECT * FROM cv_jobs WHERE id = ?", (job_id,)).fetchone()
    if not row:
        return None
    job = dict(row)
    job["payload"] = json.loads(job["payload"]) if job["payload"] else None
    return job


def list_cv_jobs(limit: int = 20, status: str | None = None, offset: int = 0) -> list[dict]:
    """Recent CV jobs, including running ones so the UI can resume polling."""
    limit = max(1, min(int(limit), 200))
    offset = max(0, int(offset))
    query = "SELECT * FROM cv_jobs"
    params: list[object] = []
    if status:
        query += " WHERE status = ?"
        params.append(status)
    query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
    params.extend((limit, offset))
    with _LOCK, _connect() as conn:
        rows = conn.execute(query, params).fetchall()
    jobs = []
    for row in rows:
        job = dict(row)
        job["payload"] = json.loads(job["payload"]) if job["payload"] else None
        jobs.append(job)
    return jobs


def count_cv_jobs(status: str | None = None) -> int:
    query = "SELECT COUNT(*) FROM cv_jobs"
    params: tuple[object, ...] = ()
    if status:
        query += " WHERE status = ?"
        params = (status,)
    with _LOCK, _connect() as conn:
        return int(conn.execute(query, params).fetchone()[0])


def active_work_count() -> int:
    with _LOCK, _connect() as conn:
        runs = int(conn.execute("SELECT COUNT(*) FROM runs WHERE status = 'running'").fetchone()[0])
        cvs = int(conn.execute("SELECT COUNT(*) FROM cv_jobs WHERE status = 'running'").fetchone()[0])
    return runs + cvs


def backup_database(destination: str) -> None:
    os.makedirs(os.path.dirname(destination), exist_ok=True)
    with _LOCK, _connect() as source:
        target = sqlite3.connect(destination)
        try:
            source.backup(target)
            target.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        finally:
            target.close()


def latest_cvs_for(urls: list[str]) -> dict[str, dict]:
    unique = list(dict.fromkeys(url for url in urls if url))
    if not unique:
        return {}
    output: dict[str, dict] = {}
    with _LOCK, _connect() as conn:
        for start in range(0, len(unique), 500):
            chunk = unique[start:start + 500]
            placeholders = ",".join("?" for _ in chunk)
            rows = conn.execute(
                f"SELECT * FROM cv_jobs WHERE status = 'done' AND url IN ({placeholders}) "
                "ORDER BY created_at DESC", chunk,
            ).fetchall()
            for row in rows:
                if row["url"] in output:
                    continue
                job = dict(row)
                job["payload"] = json.loads(job["payload"]) if job["payload"] else None
                output[row["url"]] = job
    return output


def latest_cv_for(url: str) -> dict | None:
    return latest_cvs_for([url]).get(url)
