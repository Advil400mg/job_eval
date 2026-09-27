"""Isolated JEV server used by Playwright tests."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
DATA_DIR = Path(tempfile.mkdtemp(prefix="jev-e2e-"))
os.environ.update({
    "JEV_CONFIG": str(DATA_DIR / "missing.toml"),
    "JEV_DATA_DIR": str(DATA_DIR),
    "JEV_SESSION_SECRET": "e2e-session-secret-with-at-least-32-characters",
    "JEV_ALLOW_INSECURE_REMOTE": "true",
})

from app import accounts, config, store  # noqa: E402

PROFILE = {
    "version": 1,
    "candidate": {"name": "E2E", "headline": "Security Engineer", "skills": []},
    "search": {"locations": ["Bruxelles"], "target_roles": ["Security Engineer"],
               "max_age_days": 30, "experience_filter": {
                   "reject_if_minimum_required_years_gte": 2,
                   "internships_count_as_professional_experience": False,
               }},
    "criteria": [{"id": "technical", "name": "Technique", "description": "Adéquation technique",
                  "weight": 1, "required": False}],
    "hard_rejection_rules": [], "minimum_global_score": 68, "minimum_confidence": 0.5,
}
MASTER = {
    "identity": {"name": "E2E", "headline_default": "Security Engineer", "email": "",
                 "phone": "", "linkedin": "", "mobility": "", "languages_line": ""},
    "experiences": [], "education": [], "skill_groups": [], "projects": [], "headline_words": [],
}


def seed() -> None:
    config.reset_cache()
    store.DB_PATH = str(DATA_DIR / "jev.db")
    admin = accounts.create_user(
        "admin", "admin-correct-password", "admin@example.test", "Admin E2E",
        role="admin", user_id="e2e-admin",
    )
    user = accounts.create_user(
        "member", "member-correct-password", "member@example.test", "Member E2E",
        user_id="e2e-member",
    )
    for account in (admin, user):
        directory = config.user_dir(account["id"])
        directory.mkdir(parents=True, exist_ok=True)
        profile = {**PROFILE, "candidate": {**PROFILE["candidate"], "name": account["display_name"]}}
        master = {**MASTER, "identity": {**MASTER["identity"], "name": account["display_name"]}}
        (directory / "PROFILE.json").write_text(json.dumps(profile), encoding="utf-8")
        (directory / "CV_MASTER.json").write_text(json.dumps(master), encoding="utf-8")
    run_id = store.create_run(["https://jobs.example.test/security-engineer"], admin["id"])
    store.save_result(run_id, "https://jobs.example.test/security-engineer", "ok", {
        "url": "https://jobs.example.test/security-engineer", "title": "Security Engineer",
        "company": "Example Corp", "location": "Bruxelles",
        "decision": {"status": "qualified", "hard_gate_failures": []},
        "jev": {"global_score": 82, "minimum_global_score": 68,
                "minimum_confidence": 0.5, "criteria": [], "blocking_criteria": []},
        "gate_results": [],
    })
    store.finish_run(run_id)
    store.create_application(
        "https://jobs.example.test/security-engineer", title="Security Engineer",
        company="Example Corp", location="Bruxelles", user_id=admin["id"],
    )


if __name__ == "__main__":
    seed()
    import uvicorn
    uvicorn.run("app.main:app", host="127.0.0.1", port=8769, log_level="warning")
