"""Jev Job Offer Evaluator — multipage UI, JSON API and tailored-CV generation."""

from __future__ import annotations

import csv
import io
import json
import os
import re
import tempfile
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from starlette.requests import Request

from . import analytics, backup, config, cv, jobs, network, onboarding, pipeline
from . import profile as profile_mod
from . import security, store

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


@asynccontextmanager
async def lifespan(_app: FastAPI):
    security.validate_configuration()
    _app.state.recovery = jobs.recover_after_restart()
    yield
    jobs.shutdown()


app = FastAPI(title="Jev Job Offer Evaluator", version="2.2.0", lifespan=lifespan)
app.add_middleware(security.AuthMiddleware)
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))


class EvaluateRequest(BaseModel):
    urls: list[str] = Field(..., min_length=1, max_length=200)


class CvRequest(BaseModel):
    url: str
    send_email: bool = False


class ManualEvaluateRequest(BaseModel):
    url: str = Field(..., max_length=2048)
    text: str = Field(..., min_length=200, max_length=60000)
    title: str = Field("", max_length=300)
    company: str = Field("", max_length=300)
    location: str = Field("", max_length=300)
    published_at: str | None = Field(None, max_length=10)


class ProfileUpdateRequest(BaseModel):
    profile: dict
    expected_revision: str = Field(..., min_length=64, max_length=64)


class ProfileRestoreRequest(BaseModel):
    expected_revision: str = Field(..., min_length=64, max_length=64)


class ApplicationCreateRequest(BaseModel):
    url: str = Field(..., max_length=2048)
    status: str = "to_review"
    title: str = Field("", max_length=300)
    company: str = Field("", max_length=300)
    location: str = Field("", max_length=300)


class ApplicationUpdateRequest(BaseModel):
    revision: int = Field(..., ge=1)
    status: str | None = None
    notes: str | None = Field(None, max_length=10000)
    contact_name: str | None = Field(None, max_length=300)
    contact_email: str | None = Field(None, max_length=320)
    applied_at: str | None = Field(None, max_length=10)
    follow_up_at: str | None = Field(None, max_length=10)
    title: str | None = Field(None, max_length=300)
    company: str | None = Field(None, max_length=300)
    location: str | None = Field(None, max_length=300)


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


def _optional_date(value: str | None, field: str) -> str | None:
    if value is None or not value.strip():
        return None
    try:
        return date.fromisoformat(value.strip()).isoformat()
    except ValueError as exc:
        raise HTTPException(400, f"{field} doit être une date ISO AAAA-MM-JJ") from exc


def _manual_url(value: str) -> str:
    """Validate a reference URL without DNS lookup: manual evaluation performs no fetch."""
    candidate = value.strip()
    try:
        parsed = urlsplit(candidate)
    except ValueError as exc:
        raise HTTPException(400, "URL invalide") from exc
    if parsed.scheme.lower() not in ("http", "https") or not parsed.hostname:
        raise HTTPException(400, "URL invalide (http/https requis)")
    if parsed.username or parsed.password:
        raise HTTPException(400, "L’URL ne doit pas contenir d’identifiants")
    return candidate


def _application_changes(payload: ApplicationUpdateRequest) -> dict:
    changes = payload.model_dump(exclude={"revision"}, exclude_unset=True)
    for field in ("applied_at", "follow_up_at"):
        if field in changes:
            changes[field] = _optional_date(changes[field], field)
    if changes.get("contact_email") and not re.fullmatch(
        r"[^\s@]+@[^\s@]+\.[^\s@]+", str(changes["contact_email"]), re.I,
    ):
        raise HTTPException(400, "contact_email invalide")
    for field in ("notes", "contact_name", "contact_email", "title", "company", "location"):
        if field in changes and changes[field] is not None:
            changes[field] = str(changes[field]).strip()
    return changes


def _cv_summary(url: str, cv_jobs: dict[str, dict] | None = None) -> dict | None:
    latest = cv_jobs.get(url) if cv_jobs is not None else store.latest_cv_for(url)
    if not latest:
        return None
    return {"job_id": latest["id"], "pdf": (latest["payload"] or {}).get("pdf"),
            "created_at": latest["created_at"]}


def _offer_row(item: dict, cv_jobs: dict[str, dict] | None = None,
               applications: dict[str, dict] | None = None) -> dict:
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
        "application": (applications or {}).get(store.normalize_url(item.get("url", ""))),
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


@app.get("/applications", response_class=HTMLResponse)
def applications_page(request: Request):
    return _render_page(request, "applications.html", "applications", "Candidatures")


@app.get("/profile", response_class=HTMLResponse)
def profile_page(request: Request):
    if onboarding.status()["needed"]:
        return _render_page(request, "profile.html", "profile", "Profil")
    current = profile_mod.current()
    profile, thresholds, criteria = _profile_context()
    master = json.loads(config.settings()["cv"]["master_path"].read_text(encoding="utf-8"))
    return _render_page(request, "profile.html", "profile", "Profil", {
        "profile": profile, "thresholds": thresholds, "criteria": criteria,
        "identity": master.get("identity", {}), "profile_revision": current["revision"],
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
    return {"ok": True, "version": "2.2.0", "auth_required": security.auth_enabled()}


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


@app.post("/api/evaluate/manual")
def evaluate_manual(request: Request, payload: ManualEvaluateRequest):
    _require_onboarding_complete()
    security.enforce_rate(
        request, "evaluate", config.settings()["security"]["evaluate_per_minute"], 60,
    )
    url = _manual_url(payload.url)
    published_at = _optional_date(payload.published_at, "published_at")
    run_id = store.create_run([url])
    try:
        record = pipeline.evaluate_text(
            url, payload.text, pipeline.load_profile(),
            metadata={"title": payload.title, "company": payload.company,
                      "location": payload.location, "published_at": published_at},
        )
        store.save_result(run_id, url, record.get("status", "error"), record)
        store.finish_run(run_id, "done")
    except Exception as exc:  # noqa: BLE001
        store.finish_run(run_id, "failed", str(exc))
        raise HTTPException(500, "Évaluation manuelle impossible") from exc
    return {"run_id": run_id, "total": 1, "url": f"/runs/{run_id}", "result": record}


@app.get("/api/runs/{run_id}")
def get_run(run_id: str):
    run = store.get_run(run_id)
    if not run:
        raise HTTPException(404, "Lot inconnu")
    cv_jobs = store.latest_cvs_for([item.get("url", "") for item in run["results"]])
    applications = store.applications_for_urls([item.get("url", "") for item in run["results"]])
    for item in run["results"]:
        item["cv"] = _cv_summary(item.get("url", ""), cv_jobs)
        item["application"] = applications.get(store.normalize_url(item.get("url", "")))
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
    applications = store.applications_for_urls([item.get("url", "") for item in items])
    result["offers"] = [_offer_row(item, cv_jobs, applications) for item in items]
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
    applications = store.applications_for_urls([item.get("url", "") for item in items])
    return {"offer": _offer_row(items[0], cv_jobs, applications),
            "history": [_offer_row(item, cv_jobs, applications) for item in items]}


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
    current = profile_mod.current()
    profile, thresholds, criteria = _profile_context()
    return {"profile": profile, "thresholds": thresholds, "criteria": criteria,
            "revision": current["revision"]}


@app.put("/api/profile")
def update_profile(payload: ProfileUpdateRequest):
    _require_onboarding_complete()
    try:
        return profile_mod.update_profile(payload.profile, payload.expected_revision)
    except profile_mod.ProfileConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    except profile_mod.ProfileError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/api/profile/history")
def profile_history(limit: int = Query(50, ge=1, le=200)):
    _require_onboarding_complete()
    return {"versions": profile_mod.history(limit)}


@app.post("/api/profile/history/{version_id}/restore")
def restore_profile(version_id: str, payload: ProfileRestoreRequest):
    _require_onboarding_complete()
    try:
        return profile_mod.restore(version_id, payload.expected_revision)
    except profile_mod.ProfileConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    except profile_mod.ProfileNotFound as exc:
        raise HTTPException(404, str(exc)) from exc
    except profile_mod.ProfileError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/api/applications")
def list_applications(
    page: int = Query(1, ge=1), page_size: int = Query(25, ge=5, le=100),
    q: str = "", status: str = "", due: str = "", sort: str = "updated",
):
    if status and status not in store.APPLICATION_STATUSES:
        raise HTTPException(400, "statut de candidature invalide")
    if due not in ("", "overdue", "upcoming"):
        raise HTTPException(400, "filtre de relance invalide")
    if sort not in ("updated", "follow_up", "company", "status"):
        raise HTTPException(400, "tri de candidature invalide")
    return store.list_applications(
        page=page, page_size=page_size, q=q, status=status, due=due, sort=sort,
    )


@app.post("/api/applications")
def create_application(payload: ApplicationCreateRequest):
    _require_onboarding_complete()
    url = _clean_urls([payload.url])[0]
    try:
        return store.create_application(
            url, payload.status, title=payload.title, company=payload.company,
            location=payload.location,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/api/applications/export")
def export_applications(fmt: str = "csv"):
    applications = store.all_applications()
    if fmt == "json":
        return JSONResponse(applications)
    if fmt != "csv":
        raise HTTPException(400, "format attendu : csv ou json")
    output = io.StringIO()
    fields = [
        "id", "url", "title", "company", "location", "status", "notes",
        "contact_name", "contact_email", "applied_at", "follow_up_at",
        "created_at", "updated_at", "revision",
    ]
    writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(applications)
    return StreamingResponse(
        iter([output.getvalue()]), media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=jev-applications.csv"},
    )


@app.get("/api/applications/{application_id}")
def get_application(application_id: str):
    application = store.get_application(application_id)
    if not application:
        raise HTTPException(404, "Candidature inconnue")
    application["events"] = store.application_events(application_id)
    return application


@app.patch("/api/applications/{application_id}")
def update_application(application_id: str, payload: ApplicationUpdateRequest):
    try:
        application = store.update_application(
            application_id, _application_changes(payload), payload.revision,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    if not application:
        raise HTTPException(404, "Candidature inconnue")
    return application


@app.delete("/api/applications/{application_id}")
def delete_application(application_id: str):
    if not store.delete_application(application_id):
        raise HTTPException(404, "Candidature inconnue")
    return {"deleted": application_id}


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
