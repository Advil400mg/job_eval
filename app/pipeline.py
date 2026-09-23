"""End-to-end pipeline: fetch -> extract -> gates -> Jev -> verdict."""

from __future__ import annotations

import concurrent.futures
import json
import os
import traceback

from . import config
from . import gates as gates_mod
from . import jev, store
from .extract import FetchError, extract, fetch_html


def profile_path() -> str:
    return str(config.settings()["profile_path"])


def load_profile() -> dict:
    with open(profile_path(), encoding="utf-8") as handle:
        return json.load(handle)


def evaluate_url(url: str, profile: dict, evaluator: str | None = None) -> dict:
    """Evaluate one URL. Never invents data: failures are reported as failures."""
    record: dict = {"url": url, "status": "error", "stage": None, "error": None}

    record["stage"] = "fetch"
    try:
        html_text = fetch_html(url)
    except FetchError as exc:
        record["error"] = str(exc)
        record["gate_results"] = []
        return record

    record["stage"] = "extract"
    try:
        offer = extract(url, html_text)
    except Exception as exc:  # noqa: BLE001 - reported, never hidden
        record["error"] = f"extraction failed: {exc}"
        return record

    record["title"] = offer["title"]
    record["company"] = offer["company"]
    record["location"] = offer["location"]
    record["published_at"] = offer["published_at"]
    record["published_at_provenance"] = offer["published_at_provenance"]
    record["job_text_chars"] = len(offer["job_text"])

    record["stage"] = "gates"
    gate_results = gates_mod.run_gates(offer, profile)
    record["gate_results"] = gate_results

    record["stage"] = "jev"
    try:
        jev_result = jev.evaluate(offer, profile, evaluator)
    except jev.JevError as exc:
        record["error"] = f"Jev evaluation failed: {exc}"
        record["decision"] = {"status": "unverified",
                              "hard_gate_failures": [],
                              "warnings": [],
                              "unknowns": []}
        return record

    record["jev"] = jev_result
    record["decision"] = gates_mod.decide(jev_result, gate_results)
    record["status"] = "ok"
    record["stage"] = "done"
    return record


def _worker(args: tuple[str, dict, str | None, str]) -> None:
    url, profile, evaluator, run_id = args
    try:
        record = evaluate_url(url, profile, evaluator)
    except Exception:  # noqa: BLE001
        record = {"url": url, "status": "error", "stage": "internal",
                  "error": traceback.format_exc(limit=2).strip().splitlines()[-1]}
    store.save_result(run_id, url, record.get("status", "error"), record)


def run_batch(run_id: str, urls: list[str], max_workers: int | None = None) -> None:
    profile = load_profile()
    if max_workers is None:
        max_workers = config.settings()["fetch"]["max_workers"]
    evaluator = jev.evaluator_path()
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
            list(pool.map(_worker,
                          [(url, profile, evaluator, run_id) for url in urls]))
        store.finish_run(run_id, "done")
    except Exception:  # noqa: BLE001
        store.finish_run(run_id, "failed")