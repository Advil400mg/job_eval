"""Conservative country/city matching for a user's accepted places.

Country names use ISO 3166-1 translations; unknown or unverified metadata never
becomes a proven geographic exclusion.
"""

from __future__ import annotations

import gettext
import re
import unicodedata
from functools import lru_cache
from pathlib import Path

import pycountry


def _fold(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.casefold())
    return " ".join("".join(c for c in normalized if not unicodedata.combining(c)).split())


@lru_cache(maxsize=1)
def _translated_countries() -> dict[str, str | None]:
    mapping: dict[str, str | None] = {}
    for country in pycountry.countries:
        for label in (country.name, getattr(country, "official_name", ""),
                      getattr(country, "common_name", "")):
            if label:
                mapping[_fold(label)] = country.alpha_2
    for locale in Path(pycountry.LOCALES_DIR).iterdir():
        if not locale.is_dir():
            continue
        try:
            translated = gettext.translation("iso3166-1", pycountry.LOCALES_DIR,
                                             languages=[locale.name])
        except FileNotFoundError:
            continue
        for country in pycountry.countries:
            name = _fold(translated.gettext(country.name))
            if name in mapping and mapping[name] != country.alpha_2:
                mapping[name] = None  # Ambiguous country names cannot prove a match.
            else:
                mapping[name] = country.alpha_2
    return mapping


def country_code(label: str) -> str | None:
    raw = label.strip()
    if raw.casefold().startswith("country:"):
        raw = raw.split(":", 1)[1].strip()
    if not raw:
        return None
    try:
        return pycountry.countries.lookup(raw).alpha_2
    except LookupError:
        return _translated_countries().get(_fold(raw))


def _place(label: str) -> tuple[str, str | None]:
    parts = [part.strip() for part in label.split(",") if part.strip()]
    if not parts:
        return "", None
    if len(parts) == 1 and (code := country_code(parts[0])):
        return "", code
    city = _fold(parts[0].removeprefix("city:").strip())
    code = country_code(parts[-1]) if len(parts) > 1 else None
    return city, code


def location_gate(offer: dict, accepted: list[str], preferred: list[str] | None = None) -> dict:
    """A hard failure needs a source-backed location, not inferred metadata."""
    if not accepted:
        return {"gate": "location", "status": "pass", "hard": False,
                "reason": "aucune restriction géographique déclarée"}
    location = str(offer.get("location") or "").strip()
    provenance = str(offer.get("location_provenance") or "").casefold()
    text = str(offer.get("job_text") or "")
    if re.search(r"\b(?:remote|worldwide|télétravail|teletravail|home[- ]office|anywhere)\b", location, re.I):
        return {"gate": "location", "status": "unknown", "hard": False,
                "reason": f"{location} : pays d'emploi ou d'éligibilité à vérifier"}
    proven = (bool(location and location in text) or
              provenance.startswith("json-ld joblocation") or
              provenance.startswith("texte « localisation »") or
              provenance in {"json-ld", "json_ld", "jobposting", "offer_text"})
    if not location or not proven:
        return {"gate": "location", "status": "unknown", "hard": False,
                "reason": "lieu de l'offre absent ou non confirmé par la fiche"}
    city, country = _place(location)
    for place in accepted:
        accepted_city, accepted_country = _place(place)
        if ((accepted_country is None or accepted_country == country)
                and (not accepted_city or accepted_city == city)):
            preferred_match = any(
                (p_country is None or p_country == country) and
                (not p_city or p_city == city)
                for p_city, p_country in map(_place, preferred or [])
            )
            return {"gate": "location", "status": "pass", "hard": True,
                    "reason": (f"{location} appartient aux lieux acceptés"
                               + (" et préférés" if preferred_match else ""))}
    # A city is not a country. If the job does not prove the country, a
    # country-only preference cannot justify a rejection.
    if country is None and any(_place(place)[1] for place in accepted):
        return {"gate": "location", "status": "unknown", "hard": False,
                "reason": f"pays d'emploi non prouvé pour {location}"}
    if not city and not country:
        return {"gate": "location", "status": "unknown", "hard": False,
                "reason": "localisation non structurée — à vérifier"}
    return {"gate": "location", "status": "fail", "hard": True,
            "reason": f"{location} est hors des lieux acceptés : {', '.join(accepted)}"}
