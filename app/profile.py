"""Validated, atomic and versioned management of PROFILE.json."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import tempfile
import threading
from pathlib import Path

from . import config, store

_LOCK = threading.Lock()
_CRITERION_ID = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")


class ProfileError(RuntimeError):
    pass


class ProfileConflict(ProfileError):
    pass


class ProfileNotFound(ProfileError):
    pass


def path() -> Path:
    return Path(config.settings()["profile_path"])


def revision(profile: dict) -> str:
    canonical = json.dumps(profile, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def load_profile() -> dict:
    try:
        value = json.loads(path().read_text(encoding="utf-8"))
    except OSError as exc:
        raise ProfileError(f"PROFILE.json illisible : {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ProfileError("PROFILE.json n’est pas un JSON valide") from exc
    if not isinstance(value, dict):
        raise ProfileError("PROFILE.json doit contenir un objet")
    return value


def _string_list(value: object, field: str, errors: list[str], maximum: int = 100) -> list[str]:
    if not isinstance(value, list):
        errors.append(f"{field} doit être une liste")
        return []
    if len(value) > maximum:
        errors.append(f"{field} contient plus de {maximum} valeurs")
    output = []
    for index, item in enumerate(value[:maximum]):
        if not isinstance(item, str) or not item.strip():
            errors.append(f"{field}[{index}] doit être une chaîne non vide")
            continue
        text = item.strip()
        if len(text) > 500:
            errors.append(f"{field}[{index}] dépasse 500 caractères")
        output.append(text)
    return output


def validate_profile(profile: dict) -> list[str]:
    errors: list[str] = []
    if not isinstance(profile, dict):
        return ["le profil doit être un objet"]

    global_score = profile.get("minimum_global_score")
    if isinstance(global_score, bool) or not isinstance(global_score, (int, float)) or not 0 <= global_score <= 100:
        errors.append("minimum_global_score doit être compris entre 0 et 100")
    confidence = profile.get("minimum_confidence")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
        errors.append("minimum_confidence doit être compris entre 0 et 1")

    search = profile.get("search")
    if not isinstance(search, dict):
        errors.append("search doit être un objet")
        search = {}
    _string_list(search.get("target_roles"), "search.target_roles", errors, 50)
    _string_list(search.get("locations"), "search.locations", errors, 100)
    max_age = search.get("max_age_days")
    if isinstance(max_age, bool) or not isinstance(max_age, int) or not 1 <= max_age <= 3650:
        errors.append("search.max_age_days doit être un entier entre 1 et 3650")
    experience = search.get("experience_filter")
    if not isinstance(experience, dict):
        errors.append("search.experience_filter doit être un objet")
    else:
        years = experience.get("reject_if_minimum_required_years_gte")
        if isinstance(years, bool) or not isinstance(years, int) or not 0 <= years <= 50:
            errors.append("search.experience_filter.reject_if_minimum_required_years_gte est invalide")
        if not isinstance(experience.get("internships_count_as_professional_experience"), bool):
            errors.append("search.experience_filter.internships_count_as_professional_experience doit être booléen")

    _string_list(profile.get("hard_rejection_rules"), "hard_rejection_rules", errors, 100)
    criteria = profile.get("criteria")
    if not isinstance(criteria, list) or not criteria:
        errors.append("criteria doit être une liste non vide")
        return errors
    if len(criteria) > 50:
        errors.append("criteria contient plus de 50 critères")
    seen: set[str] = set()
    for index, criterion in enumerate(criteria[:50]):
        prefix = f"criteria[{index}]"
        if not isinstance(criterion, dict):
            errors.append(f"{prefix} doit être un objet")
            continue
        identifier = criterion.get("id")
        if not isinstance(identifier, str) or not _CRITERION_ID.fullmatch(identifier):
            errors.append(f"{prefix}.id doit respecter [a-z][a-z0-9_-] et faire au plus 64 caractères")
        elif identifier in seen:
            errors.append(f"critère dupliqué : {identifier}")
        else:
            seen.add(identifier)
        for key, maximum in (("name", 200), ("description", 2000)):
            value = criterion.get(key)
            if not isinstance(value, str) or not value.strip():
                errors.append(f"{prefix}.{key} doit être une chaîne non vide")
            elif len(value.strip()) > maximum:
                errors.append(f"{prefix}.{key} dépasse {maximum} caractères")
        weight = criterion.get("weight")
        if isinstance(weight, bool) or not isinstance(weight, (int, float)) or not 0 < weight <= 100:
            errors.append(f"{prefix}.weight doit être supérieur à 0 et inférieur ou égal à 100")
        required = criterion.get("required")
        if not isinstance(required, bool):
            errors.append(f"{prefix}.required doit être booléen")
        min_score = criterion.get("min_score")
        if (required or min_score is not None) and (
            isinstance(min_score, bool) or not isinstance(min_score, (int, float))
            or not 0 <= min_score <= 100
        ):
            errors.append(f"{prefix}.min_score doit être compris entre 0 et 100")
    return errors


def editable_profile(current: dict, proposed: dict) -> dict:
    """Merge only user-editable evaluation settings; CV-derived identity stays immutable."""
    result = copy.deepcopy(current)
    for key in ("minimum_global_score", "minimum_confidence", "criteria", "hard_rejection_rules"):
        if key in proposed:
            result[key] = copy.deepcopy(proposed[key])
    if "search" in proposed:
        incoming = proposed["search"]
        current_search = result.get("search")
        existing: dict = copy.deepcopy(current_search) if isinstance(current_search, dict) else {}
        if isinstance(incoming, dict):
            for key in ("target_roles", "locations", "max_age_days", "experience_filter"):
                if key in incoming:
                    existing[key] = copy.deepcopy(incoming[key])
        else:
            existing = incoming
        result["search"] = existing
    return result


def _atomic_write(profile: dict) -> None:
    target = path()
    target.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(profile, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
    descriptor, temporary = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def current() -> dict:
    profile = load_profile()
    errors = validate_profile(profile)
    if errors:
        raise ProfileError("PROFILE.json invalide : " + " | ".join(errors[:12]))
    current_revision = revision(profile)
    store.save_profile_version(profile, current_revision, "initial")
    return {"profile": profile, "revision": current_revision}


def update_profile(proposed: dict, expected_revision: str, source: str = "manual") -> dict:
    with _LOCK:
        current_profile = load_profile()
        current_revision = revision(current_profile)
        if expected_revision != current_revision:
            raise ProfileConflict("Le profil a été modifié depuis son chargement")
        updated = editable_profile(current_profile, proposed)
        errors = validate_profile(updated)
        if errors:
            raise ProfileError(" | ".join(errors[:20]))
        updated_revision = revision(updated)
        store.save_profile_version(current_profile, current_revision, "initial")
        if updated_revision == current_revision:
            return {"profile": current_profile, "revision": current_revision, "changed": False}
        _atomic_write(updated)
        try:
            version = store.save_profile_version(updated, updated_revision, source)
        except Exception:
            _atomic_write(current_profile)
            raise
        return {"profile": updated, "revision": updated_revision, "version": version, "changed": True}


def history(limit: int = 50) -> list[dict]:
    current()
    return store.list_profile_versions(limit)


def restore(version_id: str, expected_revision: str) -> dict:
    version = store.get_profile_version(version_id)
    if not version:
        raise ProfileNotFound("Version du profil inconnue")
    return update_profile(
        version["profile"], expected_revision,
        source=f"restore:{version_id}",
    )
