"""Jev Job Offer Evaluator — multipage UI, JSON API and tailored-CV generation."""

from __future__ import annotations

import csv
import io
import json
import os
import re
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from starlette.requests import Request

from . import analytics, backup, config, cv, jobs, network, onboarding, pipeline, security, store

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


@asynccontextmanager
async def lifespan(_app: FastAPI):
    security.validate_configuration()
    _app.state.recovery = jobs.recover_after_restart()
    yield
    jobs.shutdown()


app = FastAPI(title="Jev Job Offer Evaluator", version="2.1.0", lifespan=lifespan)
app.add_middleware(security.AuthMiddleware)
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))


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
            try:
                network.validate_url(candidate)
            except network.UnsafeUrl as exc:
                raise HTTPException(400, f"URL refusée : {exc}") from exc
            key = store.normalize_url(candidate)
            if key not in seen:
                seen.add(key)
                urls.append(candidate)
    if not urls:
        raise HTTPException(400, "Aucune URL fournie")
    if len(urls) > 200:
        raise HTTPException(400, "200 URLs maximum par lot")
    return urls


def _cv_summary(url: str, cv_jobs: dict[str, dict] | None = None) -> dict | None:
    latest = cv_jobs.get(url) if cv_jobs is not None else store.latest_cv_for(url)
    if not latest:
        return None
    return {"job_id": latest["id"], "pdf": (latest["payload"] or {}).get("pdf"),
            "created_at": latest["created_at"]}


def _offer_row(item: dict, cv_jobs: dict[str, dict] | None = None) -> dict:
    """Flatten one stored result for compact offer lists."""
    jev = item.get("jev") or {}
    decision = item.get("decision") or {}
    return {
        "run_id": item.get("run_id"),
        "evaluated_at": item.get("created_at") or item.get("run_created_at"),
        "url": item.get("url"), "title": item.get("title"),
        "company": item.get("company"), "location": item.get("location"),
        "published_at": item.get("published_at"),
        "published_at_provenance": item.get("published_at_provenance"),
        "status": decision.get("status") or item.get("status"),
        "error": item.get("error"), "score": jev.get("global_score"),
        "minimum_global_score": jev.get("minimum_global_score"),
        "minimum_confidence": jev.get("minimum_confidence"),
        "blocking_criteria": jev.get("blocking_criteria") or [],
        "low_confidence_criteria": jev.get("low_confidence_criteria") or [],
        "criteria": [
            {"id": criterion.get("id"), "name": criterion.get("name"),
             "score": criterion.get("score"), "confidence": criterion.get("confidence"),
             "required": criterion.get("required"), "passed": criterion.get("passed"),
             "min_score": criterion.get("min_score")}
            for criterion in jev.get("criteria") or []
        ],
        "gates": [
            {"gate": gate.get("gate"), "status": gate.get("status"),
             "reason": gate.get("reason")}
            for gate in item.get("gate_results") or []
        ],
        "gate_failures": [gate.get("gate")
                          for gate in decision.get("hard_gate_failures") or []],
        "jev_model": jev.get("jev_model"), "usage": jev.get("usage"),
        "evaluation_count": item.get("evaluation_count", 1),
        "cv": _cv_summary(item.get("url", ""), cv_jobs),
    }


def _email_target() -> str:
    return config.email_target()


def _profile_context() -> tuple[dict, dict, list[dict]]:
    profile = pipeline.load_profile()
    settings = config.settings()
    thresholds = {
        "minimum_global_score": settings["minimum_global_score"]
        or profile.get("minimum_global_score", 68),
        "minimum_confidence": settings["minimum_confidence"]
        or profile.get("minimum_confidence", 0.5),
        "max_age_days": profile.get("search", {}).get("max_age_days", 30),
    }
    return profile, thresholds, profile.get("criteria", [])


def _page_context(request: Request, active: str, title: str) -> dict:
    settings = config.settings()
    cv_ok, cv_why = cv.available()
    return {
        "request": request, "active": active, "page_title": title,
        "api_key_set": settings["api_key_set"], "cv_available": cv_ok,
        "cv_detail": cv_why, "cv_email_target": _email_target(),
        "config_file": settings["config_file"],
        "config_file_exists": settings["config_file_exists"],
        "auth_enabled": settings["security"]["auth_enabled"],
    }


def _render_page(request: Request, template: str, active: str, title: str,
                 extra: dict | None = None):
    setup = onboarding.status()
    if setup["needed"]:
        return templates.TemplateResponse(request, "setup.html", {
            "request": request, "setup": setup,
            "config_file": config.settings()["config_file"],
        })
    context = _page_context(request, active, title)
    context.update(extra or {})
    return templates.TemplateResponse(request, template, context)


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, next: str = "/"):
    if not security.auth_enabled():
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(request, "login.html", {
        "request": request, "next": security.safe_next(next), "error": "",
    })


@app.post("/login", response_class=HTMLResponse)
def login(request: Request, password: str = Form(...), next: str = Form("/")):
    settings = config.settings()["security"]
    security.enforce_rate(
        request, "login", settings["login_attempts"], settings["login_window_seconds"],
    )
    target = security.safe_next(next)
    if not security.verify_password(password):
        return templates.TemplateResponse(request, "login.html", {
            "request": request, "next": target, "error": "Mot de passe incorrect.",
        }, status_code=401)
    response = RedirectResponse(target, status_code=303)
    security.set_session_cookie(response)
    return response


@app.post("/logout")
def logout():
    response = RedirectResponse("/login", status_code=303)
    security.clear_session_cookie(response)
    return response


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    if onboarding.status()["needed"]:
        return _render_page(request, "evaluate.html", "evaluate", "Évaluer")
    profile, thresholds, criteria = _profile_context()
    return _render_page(request, "evaluate.html", "evaluate", "Évaluer", {
        "thresholds": thresholds, "criteria": criteria,
        "target_roles": profile.get("search", {}).get("target_roles", []),
    })


@app.get("/offers", response_class=HTMLResponse)
def offers_page(request: Request):
    return _render_page(request, "offers.html", "offers", "Offres")


@app.get("/runs", response_class=HTMLResponse)
def runs_page(request: Request):
    return _render_page(request, "runs.html", "runs", "Lots")


@app.get("/runs/{run_id}", response_class=HTMLResponse)
def run_page(request: Request, run_id: str):
    if not store.get_run(run_id):
        raise HTTPException(404, "Lot inconnu")
    return _render_page(request, "run_detail.html", "runs", f"Lot {run_id}", {"run_id": run_id})


@app.get("/cv", response_class=HTMLResponse)
def cv_page(request: Request):
    return _render_page(request, "cv_jobs.html", "cv", "CV")


@app.get("/analytics", response_class=HTMLResponse)
def analytics_page(request: Request):
    return _render_page(request, "analytics.html", "analytics", "Analyses")


@app.get("/profile", response_class=HTMLResponse)
def profile_page(request: Request):
    if onboarding.status()["needed"]:
        return _render_page(request, "profile.html", "profile", "Profil")
    profile, thresholds, criteria = _profile_context()
    master = json.loads(config.settings()["cv"]["master_path"].read_text(encoding="utf-8"))
    return _render_page(request, "profile.html", "profile", "Profil", {
        "profile": profile, "thresholds": thresholds, "criteria": criteria,
        "identity": master.get("identity", {}),
    })


def _require_onboarding_complete() -> None:
    setup = onboarding.status()
    if setup["needed"]:
        raise HTTPException(
            428,
            detail={"message": "Initialisation requise : importer d'abord un CV PDF.",
                    "onboarding": setup},
        )


@app.get("/api/onboarding")
def get_onboarding():
    return onboarding.status()


@app.post("/api/onboarding")
async def create_onboarding(
    request: Request, cv_pdf: UploadFile = File(...), target_roles: str = Form(""),
    locations: str = Form(""), reject_experience_years: int = Form(2),
    max_age_days: int = Form(30),
):
    security.enforce_rate(
        request, "onboarding", config.settings()["security"]["onboarding_per_hour"], 3600,
    )
    if not onboarding.status()["needed"]:
        raise HTTPException(409, "L'application est déjà initialisée. Réinitialiser les données avant un nouvel import.")
    if cv_pdf.content_type not in ("application/pdf", "application/x-pdf", "application/octet-stream"):
        raise HTTPException(400, "Un fichier PDF est requis.")
    content = await cv_pdf.read(onboarding.MAX_PDF_BYTES + 1)
    try:
        return onboarding.initialize(
            content, cv_pdf.filename or "cv.pdf", target_roles, locations,
            reject_experience_years, max_age_days,
        )
    except onboarding.OnboardingError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/healthz")
def healthz():
    return {"ok": True, "version": "2.1.0", "auth_required": security.auth_enabled()}


@app.post("/api/evaluate")
def evaluate(request: Request, payload: EvaluateRequest):
    _require_onboarding_complete()
    security.enforce_rate(
        request, "evaluate", config.settings()["security"]["evaluate_per_minute"], 60,
    )
    urls = _clean_urls(payload.urls)
    run_id = store.create_run(urls)
    jobs.submit_run(run_id, urls)
    return {"run_id": run_id, "total": len(urls), "url": f"/runs/{run_id}"}


@app.get("/api/runs/{run_id}")
def get_run(run_id: str):
    run = store.get_run(run_id)
    if not run:
        raise HTTPException(404, "Lot inconnu")
    cv_jobs = store.latest_cvs_for([item.get("url", "") for item in run["results"]])
    for item in run["results"]:
        item["cv"] = _cv_summary(item.get("url", ""), cv_jobs)
    run["summary"] = analytics.run_summary(run)
    return run


@app.post("/api/runs/{run_id}/retry")
def retry_run(run_id: str):
    if not jobs.retry_run(run_id):
        raise HTTPException(409, "Ce lot ne peut pas être relancé")
    return {"run_id": run_id, "status": "running"}


@app.post("/api/runs/{run_id}/cancel")
def cancel_run(run_id: str):
    if not store.request_run_cancel(run_id):
        raise HTTPException(409, "Ce lot n’est pas en cours")
    return {"run_id": run_id, "cancel_requested": True}


@app.get("/api/stats")
def get_stats(view: str = "latest", days: int | None = Query(None, ge=1, le=3650)):
    if view not in ("latest", "all"):
        raise HTTPException(400, "vue statistique invalide")
    payload = analytics.summarize(store.results_for_analytics(view=view, days=days))
    payload.update({"runs": store.count_runs(), "view": view, "days": days})
    return payload


@app.get("/api/offers")
def get_offers(
    page: int = Query(1, ge=1), page_size: int = Query(50, ge=10, le=100),
    q: str = "", status: str = "", company: str = "", location: str = "",
    run_id: str = "", score_min: float | None = Query(None, ge=0, le=100),
    score_max: float | None = Query(None, ge=0, le=100), scored: str = "",
    has_cv: str = "", view: str = "latest", sort: str = "newest",
):
    if view not in ("latest", "all"):
        raise HTTPException(400, "vue d'offres invalide")
    if scored not in ("", "yes", "no") or has_cv not in ("", "yes", "no"):
        raise HTTPException(400, "filtre invalide")
    result = store.query_offers(
        page=page, page_size=page_size, q=q, status=status, company=company,
        location=location, run_id=run_id, score_min=score_min, score_max=score_max,
        scored=scored, has_cv=has_cv, view=view, sort=sort,
    )
    items = result.pop("items")
    cv_jobs = store.latest_cvs_for([item.get("url", "") for item in items])
    result["offers"] = [_offer_row(item, cv_jobs) for item in items]
    result["facets"] = store.offer_facets(view=view)
    return result


@app.get("/api/offers/history")
def get_offer_history(url: str):
    if not re.match(r"^https?://", url, re.I):
        raise HTTPException(400, "URL invalide")
    items = store.offer_history(url)
    if not items:
        raise HTTPException(404, "Offre inconnue")
    cv_jobs = store.latest_cvs_for([item.get("url", "") for item in items])
    return {"offer": _offer_row(items[0], cv_jobs),
            "history": [_offer_row(item, cv_jobs) for item in items]}


@app.get("/api/history")
def get_history(
    page: int = Query(1, ge=1), page_size: int = Query(20, ge=5, le=100),
    status: str | None = None,
):
    if status not in (None, "running", "done", "failed", "interrupted", "cancelled"):
        raise HTTPException(400, "statut de lot invalide")
    total = store.count_runs(status=status)
    runs = [analytics.run_summary(run) for run in store.runs_with_results(
        limit=page_size, offset=(page - 1) * page_size, status=status,
    )]
    return {"runs": runs, "items": runs, "page": page, "page_size": page_size,
            "total": total, "pages": max(1, (total + page_size - 1) // page_size)}


@app.get("/api/criteria")
def get_criteria():
    _require_onboarding_complete()
    profile = pipeline.load_profile()
    return {"criteria": profile.get("criteria", []),
            "minimum_global_score": profile.get("minimum_global_score", 68),
            "minimum_confidence": profile.get("minimum_confidence", 0.5)}


@app.get("/api/profile")
def get_profile():
    _require_onboarding_complete()
    profile, thresholds, criteria = _profile_context()
    return {"profile": profile, "thresholds": thresholds, "criteria": criteria}


@app.get("/api/cv")
def list_cv_jobs(
    limit: int = Query(20, ge=1, le=200), status: str | None = None,
    page: int = Query(1, ge=1), page_size: int | None = Query(None, ge=5, le=100),
):
    if status not in (None, "running", "done", "failed", "interrupted", "cancelled"):
        raise HTTPException(400, "statut CV invalide")
    size = page_size or limit
    total = store.count_cv_jobs(status=status)
    jobs = store.list_cv_jobs(limit=size, status=status, offset=(page - 1) * size)
    return {"jobs": jobs, "page": page, "page_size": size, "total": total,
            "pages": max(1, (total + size - 1) // size)}


@app.post("/api/cv")
def create_cv(request: Request, payload: CvRequest):
    _require_onboarding_complete()
    security.enforce_rate(
        request, "cv", config.settings()["security"]["cv_per_hour"], 3600,
    )
    ok, why = cv.available()
    if not ok:
        raise HTTPException(501, f"moteur CV indisponible : {why}")
    url = payload.url.strip()
    try:
        network.validate_url(url)
    except network.UnsafeUrl as exc:
        raise HTTPException(400, f"URL refusée : {exc}") from exc
    job_id = store.create_cv_job(url, send_email=payload.send_email)
    jobs.submit_cv(job_id)
    return {"job_id": job_id, "url": url}


@app.get("/api/cv/{job_id}")
def get_cv(job_id: str):
    job = store.get_cv_job(job_id)
    if not job:
        raise HTTPException(404, "Job CV inconnu")
    return job


@app.post("/api/cv/{job_id}/retry")
def retry_cv(job_id: str):
    if not jobs.retry_cv(job_id):
        raise HTTPException(409, "Ce job CV ne peut pas être relancé")
    return {"job_id": job_id, "status": "running"}


@app.post("/api/cv/{job_id}/cancel")
def cancel_cv(job_id: str):
    if not store.request_cv_cancel(job_id):
        raise HTTPException(409, "Ce job CV n’est pas en cours")
    return {"job_id": job_id, "cancel_requested": True}


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
    resolved = os.path.realpath(path)
    if os.path.commonpath((root, resolved)) != root:
        raise HTTPException(403, "PDF hors du répertoire de sortie configuré")
    return FileResponse(resolved, media_type="application/pdf", filename=os.path.basename(resolved))


@app.get("/api/backups")
def get_backups():
    return {"backups": backup.list_backups()}


@app.post("/api/backups")
def create_backup():
    return backup.create_backup("manual")


@app.get("/api/backups/{name}")
def download_backup(name: str):
    try:
        path = backup.backup_path(name)
    except backup.BackupError as exc:
        raise HTTPException(404, str(exc)) from exc
    return FileResponse(path, media_type="application/zip", filename=path.name)


@app.delete("/api/backups/{name}")
def delete_backup(name: str):
    try:
        backup.delete_backup(name)
    except backup.BackupError as exc:
        raise HTTPException(404, str(exc)) from exc
    return {"deleted": name}


@app.post("/api/backups/restore")
async def restore_backup(
    request: Request, archive: UploadFile = File(...), confirmation: str = Form(...),
):
    if confirmation != "RESTAURER":
        raise HTTPException(400, "Confirmation de restauration invalide")
    security.enforce_rate(
        request, "restore", config.settings()["security"]["restore_per_hour"], 3600,
    )
    limit = config.settings()["backup"]["max_upload_bytes"]
    data_dir = Path(config.settings()["data_dir"])
    data_dir.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=data_dir, prefix=".restore-upload-", delete=False) as handle:
            temporary_path = Path(handle.name)
            total = 0
            while chunk := await archive.read(1024 * 1024):
                total += len(chunk)
                if total > limit:
                    raise HTTPException(413, "Archive de restauration trop volumineuse")
                handle.write(chunk)
        return backup.restore_backup(temporary_path)
    except backup.BackupError as exc:
        raise HTTPException(400, str(exc)) from exc
    finally:
        if temporary_path:
            temporary_path.unlink(missing_ok=True)


@app.get("/api/runs/{run_id}/export")
def export_run(run_id: str, fmt: str = "json"):
    run = store.get_run(run_id)
    if not run:
        raise HTTPException(404, "Lot inconnu")
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
                " | ".join(jev.get("blocking_criteria", [])), item.get("url", ""),
            ])
        buffer.seek(0)
        return StreamingResponse(
            iter([buffer.getvalue()]), media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename=jev-{run_id}.csv"},
        )
    return JSONResponse(run, headers={
        "Content-Disposition": f"attachment; filename=jev-{run_id}.json",
    })
