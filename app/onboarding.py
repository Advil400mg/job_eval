"""First-launch onboarding: turn an uploaded CV PDF into portable app data."""

from __future__ import annotations

import json
import os
import re
import tempfile
import threading
import time
import unicodedata
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

from . import config, profile as profile_mod

MAX_PDF_BYTES = 10 * 1024 * 1024
MIN_TEXT_CHARS = 500
DEFAULT_CV_MODEL = "deepseek/deepseek-v4.1-flash"
_LOCK = threading.Lock()


class OnboardingError(RuntimeError):
    pass


def paths(user_id: str | None = None) -> tuple[Path, Path, Path]:
    u_dir = config.user_dir(user_id)
    return (
        u_dir / "PROFILE.json",
        u_dir / "CV_MASTER.json",
        u_dir / "source_cv.pdf",
    )


def _load_json(path: Path) -> dict | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def status(user_id: str | None = None) -> dict:
    profile_path, master_path, _ = paths(user_id)
    profile = _load_json(profile_path)
    master = _load_json(master_path)
    missing = []
    if profile is None or not isinstance(profile.get("criteria"), list) or not profile["criteria"]:
        missing.append("PROFILE.json")
    if master is None or validate_master(master):
        missing.append("CV_MASTER.json")
    return {
        "needed": bool(missing),
        "missing": missing,
        "api_key_set": config.settings()["api_key_set"],
        "profile_path": str(profile_path),
        "master_path": str(master_path),
    }


def extract_pdf_text(pdf_bytes: bytes) -> str:
    if not pdf_bytes.startswith(b"%PDF-"):
        raise OnboardingError("Le fichier fourni n'est pas un PDF valide.")
    if len(pdf_bytes) > MAX_PDF_BYTES:
        raise OnboardingError("Le CV dépasse la taille maximale de 10 Mo.")
    try:
        import pymupdf
        document = pymupdf.open(stream=pdf_bytes, filetype="pdf")
        if document.page_count > 20:
            document.close()
            raise OnboardingError("Le CV dépasse 20 pages.")
        text = "\n".join(page.get_text("text") for page in document)
        document.close()
    except OnboardingError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise OnboardingError(f"Lecture du PDF impossible : {exc}") from exc
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if len(text) < MIN_TEXT_CHARS:
        raise OnboardingError(
            "Le PDF ne contient pas assez de texte exploitable. Les CV scannés sans couche texte "
            "ne sont pas pris en charge."
        )
    return text


def _slug(value: str, fallback: str) -> str:
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value).strip("-")
    return value[:48] or fallback


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if isinstance(item, str) and item.strip()]


def _normalise_master(raw: dict, source_name: str) -> dict:
    master = dict(raw)
    master["version"] = 1
    master["updated"] = date.today().isoformat()
    master["source"] = f"CV PDF importé lors de l'initialisation : {source_name}. Aucune autre source."
    master["rules"] = [
        "Le contenu du CV généré doit provenir exclusivement de ce fichier.",
        "Ne jamais inventer d'expérience, d'entreprise, de technologie, de date, de diplôme ou de chiffre.",
        "Toute information absente du CV source doit rester absente.",
    ]
    identity = master.get("identity") if isinstance(master.get("identity"), dict) else {}
    for key in ("name", "headline_default", "email", "phone", "linkedin", "mobility", "languages_line"):
        identity[key] = str(identity.get(key) or "").strip()
    master["identity"] = identity

    for section in ("experiences", "education"):
        items = master.get(section) if isinstance(master.get(section), list) else []
        clean = []
        seen = set()
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or "").strip()
            entry_id = _slug(str(item.get("id") or title), f"{section}-{index + 1}")
            if entry_id in seen:
                entry_id = f"{entry_id}-{index + 1}"
            seen.add(entry_id)
            clean.append({
                "id": entry_id,
                "dates": str(item.get("dates") or "").strip(),
                "place": str(item.get("place") or "").strip(),
                "title": title,
                "bullets": _string_list(item.get("bullets")),
                "tags": _string_list(item.get("tags")),
            })
        master[section] = clean

    groups = master.get("skill_groups") if isinstance(master.get("skill_groups"), list) else []
    master["skill_groups"] = [
        {"id": _slug(str(g.get("id") or g.get("label") or ""), f"skills-{i + 1}"),
         "label": str(g.get("label") or "Compétences").strip(),
         "text": str(g.get("text") or "").strip()}
        for i, g in enumerate(groups) if isinstance(g, dict) and str(g.get("text") or "").strip()
    ]
    projects = master.get("projects") if isinstance(master.get("projects"), list) else []
    master["projects"] = [
        {"id": _slug(str(p.get("id") or p.get("title") or ""), f"project-{i + 1}"),
         "title": str(p.get("title") or "Projet").strip(),
         "text": str(p.get("text") or "").strip(),
         "tags": _string_list(p.get("tags"))}
        for i, p in enumerate(projects) if isinstance(p, dict) and str(p.get("text") or "").strip()
    ]
    for key in ("headline_words", "profile_facts", "eligibility_defense_only", "gap_notes_for_email"):
        master[key] = _string_list(master.get(key))
    if not master["headline_words"]:
        master["headline_words"] = [
            word for word in re.findall(r"[\wÀ-ÿ/+.-]+", identity["headline_default"])
            if len(word) > 1
        ]
    return master


def validate_master(master: dict) -> list[str]:
    errors = []
    identity = master.get("identity")
    if not isinstance(identity, dict):
        return ["identity manquante"]
    for key in ("name", "headline_default", "email", "phone", "linkedin", "mobility", "languages_line"):
        if not isinstance(identity.get(key), str):
            errors.append(f"identity.{key} doit être une chaîne")
    if not identity.get("name", "").strip():
        errors.append("identity.name manquant")
    if not identity.get("headline_default", "").strip():
        errors.append("identity.headline_default manquant")
    for section in ("experiences", "education", "skill_groups", "projects", "headline_words"):
        if not isinstance(master.get(section), list):
            errors.append(f"{section} doit être une liste")
    for section in ("experiences", "education"):
        ids = set()
        for index, item in enumerate(master.get(section) or []):
            if not isinstance(item, dict):
                errors.append(f"{section}[{index}] doit être un objet")
                continue
            for key in ("id", "title", "place"):
                if not isinstance(item.get(key), str):
                    errors.append(f"{section}[{index}].{key} doit être une chaîne")
            if not isinstance(item.get("bullets"), list):
                errors.append(f"{section}[{index}].bullets doit être une liste")
            if item.get("id") in ids:
                errors.append(f"id dupliqué dans {section} : {item.get('id')}")
            ids.add(item.get("id"))
    return errors


_SYSTEM_PROMPT = """Tu extrais fidèlement les faits d'un CV vers un JSON structuré.
Règles absolues :
- Le texte du CV fourni est l'unique source. N'invente rien et n'enrichis rien.
- Conserve les dates, employeurs, diplômes, technologies, niveaux et chiffres exactement.
- Une valeur absente devient une chaîne vide ou une liste vide.
- Les expériences restent dans l'ordre antéchronologique du CV.
- Réponds avec un seul objet JSON, sans markdown.

Schéma obligatoire :
{
  "identity": {"name":"", "headline_default":"", "email":"", "phone":"", "linkedin":"", "mobility":"", "languages_line":""},
  "headline_words": ["mots réellement présents dans le CV et utilisables dans un titre"],
  "profile_facts": ["faits courts uniquement tirés du CV"],
  "experiences": [{"id":"slug", "dates":"", "place":"", "title":"", "bullets":[""], "tags":[""]}],
  "education": [{"id":"slug", "dates":"", "place":"", "title":"", "bullets":[""]}],
  "skill_groups": [{"id":"slug", "label":"", "text":"compétences séparées par des virgules"}],
  "projects": [{"id":"slug", "title":"", "text":"", "tags":[""]}],
  "eligibility_defense_only": [],
  "gap_notes_for_email": []
}"""


def _call_llm(cv_text: str, api_key: str, model: str) -> dict:
    body = {
        "model": model,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": "CV SOURCE :\n" + cv_text[:30000]},
        ],
    }
    request = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json",
                 "X-Title": "Jev webapp onboarding"},
        method="POST",
    )
    last_error = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                payload = json.loads(response.read().decode("utf-8"))
            content = payload["choices"][0]["message"]["content"]
            content = re.sub(r"^```(?:json)?|```$", "", content.strip(), flags=re.M).strip()
            result = json.loads(content)
            if not isinstance(result, dict):
                raise ValueError("la réponse n'est pas un objet JSON")
            return result
        except urllib.error.HTTPError as exc:
            last_error = f"OpenRouter HTTP {exc.code}"
            if exc.code not in (429, 500, 502, 503, 504) or attempt == 2:
                break
        except (urllib.error.URLError, TimeoutError, KeyError, json.JSONDecodeError, ValueError) as exc:
            last_error = str(exc)
            if attempt == 2:
                break
        time.sleep(2 ** attempt)
    raise OnboardingError(f"Création du profil impossible : {last_error or 'réponse LLM invalide'}")


def _generate_master(cv_text: str, source_name: str) -> dict:
    api_key = config.resolve_api_key()
    if not api_key:
        raise OnboardingError("OPENROUTER_API_KEY est requise pour analyser le CV.")
    model = config.settings()["cv"]["model"] or DEFAULT_CV_MODEL
    errors = []
    for _ in range(2):
        master = _normalise_master(_call_llm(cv_text, api_key, model), source_name)
        errors = validate_master(master)
        if not errors:
            return master
    raise OnboardingError("CV_MASTER invalide après deux tentatives : " + " | ".join(errors[:12]))


def _split_preferences(value: str) -> list[str]:
    return [part.strip() for part in re.split(r"[\n,;]+", value or "") if part.strip()]


def build_profile(master: dict, target_roles: str, locations: str,
                  reject_experience_years: int, max_age_days: int) -> dict:
    identity = master["identity"]
    roles = _split_preferences(target_roles) or [identity["headline_default"]]
    places = _split_preferences(locations)
    skill_text = ", ".join(group["text"] for group in master["skill_groups"][:8])
    role_text = ", ".join(roles)
    location_text = (", ".join(places) if places else
                     "aucune préférence géographique explicite ; ne pas inventer de contrainte")
    language_text = identity.get("languages_line") or "langues indiquées dans le CV"
    return {
        "version": 1,
        "generated_from": "CV_MASTER.json + préférences saisies lors de l'initialisation",
        "candidate": {
            "name": identity["name"],
            "headline": identity["headline_default"],
            "skills": [group["text"] for group in master["skill_groups"]],
        },
        "search": {
            "locations": places,
            "target_roles": roles,
            "max_age_days": max_age_days,
            "experience_filter": {
                "reject_if_minimum_required_years_gte": reject_experience_years,
                "internships_count_as_professional_experience": False,
            },
        },
        "criteria": [
            {"id": "experience_fit", "name": "Compatibilité du niveau d'expérience",
             "description": f"Le poste reste compatible avec le niveau du CV et n'exige pas {reject_experience_years} ans d'expérience ou plus.",
             "weight": 5, "required": True, "min_score": 60},
            {"id": "role_fit", "name": "Adéquation du poste recherché",
             "description": f"Le poste correspond principalement aux fonctions ciblées : {role_text}.",
             "weight": 5, "required": True, "min_score": 60},
            {"id": "skills_match", "name": "Correspondance des compétences",
             "description": f"Les missions et technologies correspondent aux compétences réellement présentes dans le CV : {skill_text or 'voir le CV candidat'}.",
             "weight": 5, "required": False},
            {"id": "hands_on_content", "name": "Contenu concret du poste",
             "description": "Les missions, responsabilités, outils et livrables sont suffisamment précis pour évaluer le travail réel.",
             "weight": 3, "required": False},
            {"id": "location_fit", "name": "Localisation",
             "description": f"La localisation est compatible avec les préférences déclarées : {location_text}.",
             "weight": 2, "required": False},
            {"id": "language_fit", "name": "Compatibilité linguistique",
             "description": f"Les langues exigées sont compatibles avec le CV : {language_text}.",
             "weight": 2, "required": False},
        ],
        "hard_rejection_rules": [
            f"Minimum obligatoire de {reject_experience_years} ans d'expérience ou plus.",
            "Stage, alternance ou programme exigeant un statut étudiant.",
            "Offre expirée ou sans chemin de candidature actif.",
            f"Date de publication non prouvable dans la fenêtre de {max_age_days} jours.",
        ],
        "minimum_global_score": 68,
        "minimum_confidence": 0.5,
    }


def validate_profile(profile: dict) -> list[str]:
    return profile_mod.validate_profile(profile)


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(handle, "wb") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temp_name, path)
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass


def initialize(pdf_bytes: bytes, filename: str, target_roles: str = "", locations: str = "",
               reject_experience_years: int = 2, max_age_days: int = 30,
               user_id: str | None = None) -> dict:
    if not 1 <= reject_experience_years <= 50:
        raise OnboardingError("Le seuil d'expérience doit être compris entre 1 et 50 ans.")
    if not 1 <= max_age_days <= 365:
        raise OnboardingError("La fraîcheur doit être comprise entre 1 et 365 jours.")
    with _LOCK:
        cv_text = extract_pdf_text(pdf_bytes)
        master = _generate_master(cv_text, Path(filename or "cv.pdf").name)
        profile = build_profile(master, target_roles, locations,
                                reject_experience_years, max_age_days)
        profile_errors = validate_profile(profile)
        if profile_errors:
            raise OnboardingError("PROFILE invalide : " + " | ".join(profile_errors[:12]))
        profile_path, master_path, source_path = paths(user_id)
        _atomic_write(master_path, json.dumps(master, ensure_ascii=False, indent=2).encode("utf-8") + b"\n")
        _atomic_write(profile_path, json.dumps(profile, ensure_ascii=False, indent=2).encode("utf-8") + b"\n")
        _atomic_write(source_path, pdf_bytes)
    return {
        "ok": True,
        "candidate": master["identity"]["name"],
        "experiences": len(master["experiences"]),
        "education": len(master["education"]),
        "skill_groups": len(master["skill_groups"]),
        "profile_path": str(profile_path),
        "master_path": str(master_path),
    }
