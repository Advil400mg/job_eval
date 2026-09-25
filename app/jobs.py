"""Durable background job dispatch and restart recovery."""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

from . import config, cv, pipeline, store

_RUN_POOL: ThreadPoolExecutor | None = None
_CV_POOL: ThreadPoolExecutor | None = None
_POOL_LOCK = threading.Lock()


def _pools() -> tuple[ThreadPoolExecutor, ThreadPoolExecutor]:
    global _RUN_POOL, _CV_POOL
    with _POOL_LOCK:
        if _RUN_POOL is None:
            _RUN_POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix="jev-run")
        if _CV_POOL is None:
            _CV_POOL = ThreadPoolExecutor(max_workers=1, thread_name_prefix="jev-cv")
        return _RUN_POOL, _CV_POOL


def submit_run(run_id: str, urls: list[str]) -> None:
    run_pool, _ = _pools()
    run_pool.submit(pipeline.run_batch, run_id, urls)


def _execute_cv(job_id: str) -> None:
    job = store.get_cv_job(job_id)
    if not job:
        return
    if store.cv_cancel_requested(job_id):
        store.finish_cv_job(job_id, "cancelled", {"error": "Génération annulée"})
        return
    try:
        payload = cv.generate(
            job["url"],
            send_email=bool(job.get("send_email")),
            should_cancel=lambda: store.cv_cancel_requested(job_id),
        )
        store.finish_cv_job(job_id, "done", payload)
    except cv.CvCancelled as exc:
        store.finish_cv_job(job_id, "cancelled", {"error": str(exc)}, str(exc))
    except cv.CvError as exc:
        store.finish_cv_job(job_id, "failed", {"error": str(exc)}, str(exc))
    except Exception as exc:  # noqa: BLE001 - persisted for the user
        store.finish_cv_job(job_id, "failed", {"error": str(exc)}, str(exc))


def submit_cv(job_id: str) -> None:
    _, cv_pool = _pools()
    cv_pool.submit(_execute_cv, job_id)


def retry_run(run_id: str) -> bool:
    run = store.get_run(run_id)
    if not run or int(run.get("attempts") or 1) >= config.settings()["jobs"]["max_attempts"]:
        return False
    missing = store.missing_run_urls(run_id)
    if not missing or not store.resume_run(run_id):
        return False
    submit_run(run_id, missing)
    return True


def retry_cv(job_id: str) -> bool:
    job = store.get_cv_job(job_id)
    if not job or int(job.get("attempts") or 1) >= config.settings()["jobs"]["max_attempts"]:
        return False
    if not store.restart_cv_job(job_id):
        return False
    submit_cv(job_id)
    return True


def recover_after_restart() -> dict[str, int]:
    interrupted_cv = store.interrupt_running_cv_jobs()
    resumed_runs = 0
    failed_runs = 0
    for run in store.running_runs():
        missing = store.missing_run_urls(run["id"])
        if not missing:
            store.finish_run(run["id"], "done")
            continue
        if int(run.get("attempts") or 1) >= config.settings()["jobs"]["max_attempts"]:
            store.finish_run(run["id"], "interrupted", "nombre maximal de reprises atteint")
            failed_runs += 1
            continue
        if store.resume_run(run["id"]):
            submit_run(run["id"], missing)
            resumed_runs += 1
    return {"resumed_runs": resumed_runs, "interrupted_runs": failed_runs,
            "interrupted_cv": interrupted_cv}


def shutdown() -> None:
    global _RUN_POOL, _CV_POOL
    with _POOL_LOCK:
        if _RUN_POOL is not None:
            _RUN_POOL.shutdown(wait=False, cancel_futures=True)
            _RUN_POOL = None
        if _CV_POOL is not None:
            _CV_POOL.shutdown(wait=False, cancel_futures=True)
            _CV_POOL = None
