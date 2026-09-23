"""Jev Job Offer Evaluator — dashboard, JSON API and tailored-CV generation."""

from __future__ import annotations

import csv
import io
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from starlette.requests import Request

from . import analytics, config, cv, pipeline, store

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = FastAPI(title="Jev Job Offer Evaluator", version="1.4.0")
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

POOL = ThreadPoolExecutor(max_workers=2)
CV_POOL = ThreadPoolExecutor(max_workers=1)


class EvaluateRequest(BaseModel):
    urls: list[str] = Field(..., min_length=1, max_length=200)


class CvRequest(BaseModel):
    url: str
    send_email: bool = False


def _clean_urls(raw: list[str]) -> list[str]:
    seen, urls = set(), []
    for item in raw:
        for candidate in re.split(r"[\s,;]+", item.strip()):
            if not candidate:
                continue
            if not re.match(r"^https?://", candidate, re.I):
                raise HTTPException(400, f"URL invalide (http/https requis) : {candidate}")
            if candidate not in seen:
                seen.add(candidate)
                urls.append(candidate)
    if not urls:
        raise HTTPException(400, "Aucune URL fournie")
    if len(urls) > 200:
        raise HTTPException(400, "200 URLs maximum par lot")
    return urls


def _offer_row(item: dict) -> dict:
    """Flatten one stored result for the offers table."""
    jev = item.get("jev") or {}
    decision = item.get("decision") or {}
    latest_cv = store.latest_cv_for(item.get("url", ""))
    return {
        "run_id": item.get("run_id"),
        "evaluated_at": item.get("created_at"),
        "url": item.get("url"),
        "title": item.get("title"),
        "company": item.get("company"),
        "location": item.get("location"),
        "published_at": item.get("published_at"),
        "status": decision.get("status") or item.get("status"),
        "error": item.get("error"),
        "score": jev.get("global_score"),
        "minimum_global_score": jev.get("minimum_global_score"),
        "blocking_criteria": jev.get("blocking_criteria") or [],
        "low_confidence_criteria": jev.get("low_confidence_criteria") or [],
        "criteria": [{"id": c["id"], "score": c["score"], "confidence": c["confidence"],
                      "required": c["required"], "passed": c["passed"],
                      "min_score": c["min_score"]} for c in jev.get("criteria") or []],
        "gates": [{"gate": g["gate"], "status": g["status"], "reason": g["reason"]}
                  for g in item.get("gate_results") or []],
        "gate_failures": [g["gate"] for g in (decision.get("hard_gate_failures") or [])],
        "jev_model": jev.get("jev_model"),
        "usage": jev.get("usage"),
        "cv": ({"job_id": latest_cv["id"], "pdf": (latest_cv["payload"] or {}).get("pdf"),
                "created_at": latest_cv["created_at"]} if latest_cv else None),
    }


def _email_target() -> str:
    """Adresse d'envoi du moteur CV (EMAIL_ADDRESS), pour affichage uniquement."""
    return config.email_target()


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    try:
        profile = pipeline.load_profile()
        criteria = profile.get("criteria", [])
        settings = config.settings()
        thresholds = {
            "minimum_global_score": settings["minimum_global_score"]
            or profile.get("minimum_global_score", 68),
            "minimum_confidence": settings["minimum_confidence"]
            or profile.get("minimum_confidence", 0.5),
            "max_age_days": profile.get("search", {}).get("max_age_days", 30),
        }
    except FileNotFoundError:
        criteria, thresholds = [], {}
    cv_ok, cv_why = cv.available()
    return templates.TemplateResponse("index.html", {
        "request": request,
        "criteria": criteria,
        "thresholds": thresholds,
        "api_key_set": config.settings()["api_key_set"],
        "cv_available": cv_ok,
        "cv_bin": cv_why,
        "cv_email_target": _email_target(),
        "config_file": config.settings()["config_file"],
        "config_file_exists": config.settings()["config_file_exists"],
    })


@app.get("/healthz")
def healthz():
    """État + configuration effective (jamais de secret ici)."""
    settings = config.settings()
    cv_ok, cv_why = cv.available()
    return {"ok": True,
            "config_file": settings["config_file"],
            "config_file_exists": settings["config_file_exists"],
            "api_key_set": settings["api_key_set"],
            "profile": str(settings["profile_path"]),
            "evaluator": str(settings["evaluator_path"]),
            "jev_model": settings["openrouter"]["model"],
            "jev_endpoint": settings["openrouter"]["endpoint"],
            "db_file": str(settings["db_file"]),
            "cv_available": cv_ok,
            "cv_detail": cv_why,
            "cv_out_dir": str(settings["cv"]["out_dir"]),
            "cv_email_target": settings["email_target"]}


@app.post("/api/evaluate")
def evaluate(payload: EvaluateRequest):
    urls = _clean_urls(payload.urls)
    run_id = store.create_run(urls)
    POOL.submit(pipeline.run_batch, run_id, urls)
    return {"run_id": run_id, "total": len(urls)}


@app.get("/api/runs/{run_id}")
def get_run(run_id: str):
    run = store.get_run(run_id)
    if not run:
        raise HTTPException(404, "Run inconnu")
    run["summary"] = analytics.run_summary(run)
    return run


@app.get("/api/stats")
def get_stats():
    """Global dashboard: counts, score spread, per-criterion and per-gate aggregates."""
    results = store.all_results()
    payload = analytics.summarize(results)
    payload["runs"] = len(store.list_runs(limit=1000))
    return payload


@app.get("/api/offers")
def get_offers(limit: int = 500):
    return {"offers": [_offer_row(item) for item in store.all_results()[:limit]]}


@app.get("/api/history")
def get_history(limit: int = 30):
    return {"runs": [analytics.run_summary(run)
                     for run in store.runs_with_results(limit=limit)]}


@app.get("/api/criteria")
def get_criteria():
    profile = pipeline.load_profile()
    return {"criteria": profile.get("criteria", []),
            "minimum_global_score": profile.get("minimum_global_score", 68),
            "minimum_confidence": profile.get("minimum_confidence", 0.5)}


@app.get("/api/cv")
def list_cv_jobs(limit: int = 20, status: str | None = None):
    if status not in (None, "running", "done", "failed"):
        raise HTTPException(400, "statut CV invalide")
    return {"jobs": store.list_cv_jobs(limit=limit, status=status)}


@app.post("/api/cv")
def create_cv(payload: CvRequest):
    ok, why = cv.available()
    if not ok:
        raise HTTPException(501, f"moteur CV indisponible : {why}")
    url = payload.url.strip()
    if not re.match(r"^https?://", url, re.I):
        raise HTTPException(400, "URL invalide")
    job_id = store.create_cv_job(url)

    def _run():
        try:
            result = cv.generate(url, send_email=payload.send_email)
            store.finish_cv_job(job_id, "done", result)
        except cv.CvError as exc:
            store.finish_cv_job(job_id, "failed", {"error": str(exc)})
        except Exception as exc:  # noqa: BLE001 - reported, never hidden
            store.finish_cv_job(job_id, "failed", {"error": str(exc)})

    CV_POOL.submit(_run)
    return {"job_id": job_id, "url": url}


@app.get("/api/cv/{job_id}")
def get_cv(job_id: str):
    job = store.get_cv_job(job_id)
    if not job:
        raise HTTPException(404, "Job CV inconnu")
    return job


@app.get("/api/cv/{job_id}/pdf")
def download_cv(job_id: str):
    job = store.get_cv_job(job_id)
    if not job:
        raise HTTPException(404, "Job CV inconnu")
    payload = job.get("payload") or {}
    path = payload.get("pdf")
    if not path or not os.path.isfile(path):
        raise HTTPException(404, "PDF indisponible")
    root = os.path.realpath(cv.out_dir())
    if not os.path.realpath(path).startswith(root):
        raise HTTPException(403, "PDF hors du répertoire de sortie configuré")
    return FileResponse(path, media_type="application/pdf",
                        filename=os.path.basename(path))


@app.get("/api/runs/{run_id}/export")
def export_run(run_id: str, fmt: str = "json"):
    run = store.get_run(run_id)
    if not run:
        raise HTTPException(404, "Run inconnu")
    if fmt == "csv":
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(["entreprise", "localisation", "poste", "score_jev",
                         "seuil", "statut", "portes_bloquantes", "publiee_le",
                         "criteres_bloquants", "url"])
        for item in run["results"]:
            jev = item.get("jev") or {}
            decision = item.get("decision") or {}
            writer.writerow([
                item.get("company", ""), item.get("location", ""), item.get("title", ""),
                jev.get("global_score", ""), jev.get("minimum_global_score", ""),
                decision.get("status", item.get("status", "")),
                " | ".join(g["gate"] for g in decision.get("hard_gate_failures", [])),
                item.get("published_at") or "",
                " | ".join(jev.get("blocking_criteria", [])),
                item.get("url", ""),
            ])
        buffer.seek(0)
        return StreamingResponse(
            iter([buffer.getvalue()]), media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename=jev-{run_id}.csv"},
        )
    return JSONResponse(
        run, headers={"Content-Disposition": f"attachment; filename=jev-{run_id}.json"},
    )