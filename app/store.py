"""SQLite persistence for evaluation runs and CV jobs."""

from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
import time
import uuid
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
    total INTEGER NOT NULL DEFAULT 0
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
    payload TEXT
);
"""

_RESULT_COLUMNS = {
    "normalized_url": "TEXT",
    "title": "TEXT",
    "company": "TEXT",
    "location": "TEXT",
    "decision_status": "TEXT",
    "score": "REAL",
    "published_at": "TEXT",
}
_TRACKING_PARAMS = {
    "fbclid", "gclid", "mc_cid", "mc_eid", "ref", "referrer", "source",
}


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


def _migrate(conn: sqlite3.Connection) -> None:
    columns = {row[1] for row in conn.execute("PRAGMA table_info(results)").fetchall()}
    for name, sql_type in _RESULT_COLUMNS.items():
        if name not in columns:
            conn.execute(f"ALTER TABLE results ADD COLUMN {name} {sql_type}")
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
    """)


def _connect() -> sqlite3.Connection:
    directory = os.path.dirname(DB_PATH)
    if directory:
        os.makedirs(directory, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    _migrate(conn)
    return conn


def create_run(urls: list[str]) -> str:
    run_id = uuid.uuid4().hex[:12]
    with _LOCK, _connect() as conn:
        conn.execute(
            "INSERT INTO runs (id, created_at, urls, status, progress, total) "
            "VALUES (?, ?, ?, 'running', 0, ?)",
            (run_id, time.strftime("%Y-%m-%dT%H:%M:%S"), json.dumps(urls, ensure_ascii=False),
             len(urls)),
        )
    return run_id


def set_total(run_id: str, total: int) -> None:
    with _LOCK, _connect() as conn:
        conn.execute("UPDATE runs SET total = ? WHERE id = ?", (total, run_id))


def save_result(run_id: str, url: str, status: str, payload: dict) -> None:
    indexed = _payload_columns(url, status, payload)
    with _LOCK, _connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO results "
            "(run_id, url, created_at, status, payload, normalized_url, title, company, "
            "location, decision_status, score, published_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (run_id, url, time.strftime("%Y-%m-%dT%H:%M:%S"), status,
             json.dumps(payload, ensure_ascii=False), *indexed),
        )
        conn.execute(
            "UPDATE runs SET progress = (SELECT COUNT(*) FROM results WHERE run_id = ?) "
            "WHERE id = ?", (run_id, run_id),
        )


def finish_run(run_id: str, status: str = "done") -> None:
    with _LOCK, _connect() as conn:
        conn.execute("UPDATE runs SET status = ? WHERE id = ?", (status, run_id))


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
    query = "SELECT id, created_at, status, progress, total, urls FROM runs"
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


def create_cv_job(url: str) -> str:
    job_id = uuid.uuid4().hex[:12]
    with _LOCK, _connect() as conn:
        conn.execute(
            "INSERT INTO cv_jobs (id, url, created_at, status) VALUES (?, ?, ?, 'running')",
            (job_id, url, time.strftime("%Y-%m-%dT%H:%M:%S")),
        )
    return job_id


def finish_cv_job(job_id: str, status: str, payload: dict | None = None) -> None:
    with _LOCK, _connect() as conn:
        conn.execute("UPDATE cv_jobs SET status = ?, payload = ? WHERE id = ?",
                     (status, json.dumps(payload or {}, ensure_ascii=False), job_id))


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
