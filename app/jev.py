"""Thin wrapper around the Jev evaluator script.

The scoring itself is delegated to evaluate_job.py (same script the Job Hunt
skill uses): it validates the payload, calls the TypeSafe Jev API through
OpenRouter, retries transient errors and computes the weighted score. This app
never re-implements nor adjusts the scoring.

Seul ajout par rapport au script d'origine : le point d'entrée, le modèle et la
clé API peuvent venir de la configuration (config.toml) et sont transmis dans
l'entrée JSON. Sans configuration, le script garde exactement ses valeurs par
défaut.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile

from . import config, policy
from .job_facts import extract_facts


class JevError(RuntimeError):
    pass


def evaluator_path() -> str:
    return os.environ.get("JEV_EVALUATOR") or str(config.settings()["evaluator_path"])


def evaluate(offer: dict, profile: dict, evaluator: str | None = None) -> dict:
    evaluator = evaluator or evaluator_path()
    if not os.path.isfile(evaluator):
        raise JevError(f"Évaluateur introuvable : {evaluator} "
                       f"(régler [profile].evaluator dans config.toml)")

    settings = config.settings()
    api_key = config.resolve_api_key()
    if not api_key:
        raise JevError("clé API absente : renseigner OPENROUTER_API_KEY ou "
                       "[openrouter] dans config.toml")

    text = offer["job_text"]
    facts = extract_facts(offer)
    verified_context = {
        name: {"value": fact["value"], "evidence": fact["evidence"]}
        for name in ("contract", "experience_min", "experience_preferred", "junior")
        if (fact := facts[name])["status"] == "known" and fact["evidence"] in text
    }
    for name in ("title", "location"):
        value = offer.get(name)
        if isinstance(value, str) and value and value in text:
            verified_context[name] = {"value": value, "evidence": value}
    payload = {
        "url": offer["url"],
        "title": offer["title"],
        "company": offer["company"],
        "job_text": offer["job_text"],
        "location": offer.get("location"),
        "published_at": offer.get("published_at"),
        "minimum_global_score": settings["minimum_global_score"]
        or profile.get("minimum_global_score", 68),
        "minimum_confidence": settings["minimum_confidence"]
        or profile.get("minimum_confidence", 0.5),
        "criteria": policy.effective_criteria(profile),
        "offer_context": verified_context,
        # surcharges optionnelles, lues par scripts/evaluate_job.py
        "api_endpoint": settings["openrouter"]["endpoint"],
        "model": settings["openrouter"]["model"],
        "timeout_seconds": settings["openrouter"]["timeout_seconds"],
        "max_retries": settings["openrouter"]["max_retries"],
    }
    if context := policy.context(profile):
        payload["profile_context"] = context

    env = dict(os.environ)
    env["OPENROUTER_API_KEY"] = api_key
    with tempfile.NamedTemporaryFile(
        "w", suffix=".json", delete=False, encoding="utf-8"
    ) as handle:
        json.dump(payload, handle, ensure_ascii=False)
        path = handle.name
    try:
        proc = subprocess.run(
            [sys.executable, evaluator, path],
            capture_output=True, text=True,
            timeout=settings["openrouter"]["timeout_seconds"] * 4, env=env,
        )
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass

    if proc.returncode != 0:
        detail = (proc.stderr or "").strip().splitlines()
        raise JevError(detail[-1] if detail else f"evaluator exit {proc.returncode}")
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise JevError(f"evaluator returned invalid JSON: {exc}") from exc
