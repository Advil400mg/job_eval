"""SQLite persistence for evaluation runs."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
import uuid

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


def _connect() -> sqlite3.Connection:
    directory = os.path.dirname(DB_PATH)
    if directory:
        os.makedirs(directory, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
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
    with _LOCK, _connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO results (run_id, url, created_at, status, payload) "
            "VALUES (?, ?, ?, ?, ?)",
            (run_id, url, time.strftime("%Y-%m-%dT%H:%M:%S"), status,
             json.dumps(payload, ensure_ascii=False)),
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


def list_runs(limit: int = 20) -> list[dict]:
    with _LOCK, _connect() as conn:
        rows = conn.execute(
            "SELECT id, created_at, status, progress, total, urls FROM runs "
            "ORDER BY created_at DESC LIMIT ?", (limit,),
        ).fetchall()
    out = []
    for row in rows:
        item = dict(row)
        item["urls"] = json.loads(item["urls"])
        out.append(item)
    return out


def all_results() -> list[dict]:
    """Every stored result, newest run first, tagged with its run."""
    with _LOCK, _connect() as conn:
        rows = conn.execute(
            "SELECT results.run_id, results.created_at, results.payload, "
            "runs.created_at AS run_created_at "
            "FROM results JOIN runs ON runs.id = results.run_id "
            "ORDER BY runs.created_at DESC, results.created_at DESC",
        ).fetchall()
    out = []
    for row in rows:
        item = json.loads(row["payload"])
        item["run_id"] = row["run_id"]
        item["created_at"] = row["created_at"]
        item["run_created_at"] = row["run_created_at"]
        out.append(item)
    return out


def runs_with_results(limit: int = 50) -> list[dict]:
    """Runs (newest first) with their decoded results, for history summaries."""
    runs = list_runs(limit=limit)
    with _LOCK, _connect() as conn:
        for run in runs:
            rows = conn.execute(
                "SELECT payload FROM results WHERE run_id = ? ORDER BY created_at",
                (run["id"],),
            ).fetchall()
            run["results"] = [json.loads(r["payload"]) for r in rows]
    return runs


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


def list_cv_jobs(limit: int = 20, status: str | None = None) -> list[dict]:
    """Recent CV jobs, including running ones so the UI can resume polling."""
    limit = max(1, min(int(limit), 200))
    query = "SELECT * FROM cv_jobs"
    params: list[object] = []
    if status:
        query += " WHERE status = ?"
        params.append(status)
    query += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    with _LOCK, _connect() as conn:
        rows = conn.execute(query, params).fetchall()
    jobs = []
    for row in rows:
        job = dict(row)
        job["payload"] = json.loads(job["payload"]) if job["payload"] else None
        jobs.append(job)
    return jobs


def latest_cv_for(url: str) -> dict | None:
    with _LOCK, _connect() as conn:
        row = conn.execute(
            "SELECT * FROM cv_jobs WHERE url = ? AND status = 'done' "
            "ORDER BY created_at DESC LIMIT 1", (url,),
        ).fetchone()
    if not row:
        return None
    job = dict(row)
    job["payload"] = json.loads(job["payload"]) if job["payload"] else None
    return job