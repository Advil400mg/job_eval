"""Fetch and extract job-offer content from a URL (stdlib only)."""

from __future__ import annotations

import html
import json
import re

from . import config, locations, network

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

MONTHS_FR = {
    "janvier": 1, "février": 2, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5,
    "juin": 6, "juillet": 7, "août": 8, "aout": 8, "septembre": 9,
    "octobre": 10, "novembre": 11, "décembre": 12, "decembre": 12,
    "january": 1, "february": 2, "march": 3, "april": 4, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11,
    "december": 12,
}

# Navigation / UI phrases that must never leak into job facts.  These are
# page-shell markers, not advertised requirements.
_NAV_PATTERNS = [
    # Skip-to-content links (common in French job boards)
    r"Aller au contenu principal",
    r"Aller au menu",
    r"Passer au contenu principal",
    r"Aller à la navigation",
    r"Accéder au contenu",
    r"Skip to main content",
    r"Skip to content",
    r"Skip to navigation",
    r"Menu principal",
    # Breadcrumb labels
    r"Accueil\s*[>›»/]\s*(?:Recherche|Offres|Emploi|Détail)s?\b[^\n]{0,40}(?:\n|$)",
    # "Offres recommandées" / "Related jobs" section headings — the broader cut
    # below handles the list, but the heading alone can leak seniority signals.
    r"Des offres d'emplois recommand[ée]es",
    r"Offres similaires",
    r"Related (?:jobs|offers)",
    r"Vous pourriez aussi aimer",
    r"Consultez aussi",
]

_NAV_RE = re.compile(
    "|".join(f"(?:{p})" for p in _NAV_PATTERNS),
    re.I,
)

# Only discard related-offer sections as a whole. Contract/salary lines can be
# part of the advertised role; removing them individually destroys real facts.


class FetchError(RuntimeError):
    pass


def fetch_html(url: str, timeout: int | None = None) -> str:
    """Download a public HTTP(S) page with SSRF-safe redirect handling."""
    settings = config.settings()["fetch"]
    try:
        return network.fetch_text(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "fr,en;q=0.8",
            },
            timeout=float(timeout or settings["timeout_seconds"]),
            max_bytes=max(1_000_000, int(settings["max_text_chars"]) * 10),
        )
    except network.UnsafeUrl as exc:
        raise FetchError(str(exc)) from exc


def _job_posting(html_text: str) -> dict:
    for block in re.findall(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html_text, re.S | re.I,
    ):
        try:
            data = json.loads(block.strip())
        except json.JSONDecodeError:
            continue
        candidates = data if isinstance(data, list) else [data]
        for node in candidates:
            if isinstance(node, dict) and node.get("@type") == "JobPosting":
                return node
            if isinstance(node, dict) and isinstance(node.get("@graph"), list):
                for sub in node["@graph"]:
                    if isinstance(sub, dict) and sub.get("@type") == "JobPosting":
                        return sub
    return {}


def visible_text(html_text: str) -> str:
    text = re.sub(r"<script.*?</script>", " ", html_text, flags=re.S | re.I)
    text = re.sub(r"<style.*?</style>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<(nav|footer)\b[^>]*>.*?</\1\s*>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"</(p|li|div|h1|h2|h3|h4|h5|tr|section|article)>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"[ \t\xa0]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    return text.strip()


def _meta(html_text: str, prop: str) -> str | None:
    pattern = (
        r'<meta[^>]+(?:property|name)=["\']' + re.escape(prop) + r'["\'][^>]+content=["\'](.*?)["\']'
    )
    match = re.search(pattern, html_text, re.S | re.I)
    if not match:
        match = re.search(
            r'<meta[^>]+content=["\'](.*?)["\'][^>]+(?:property|name)=["\']'
            + re.escape(prop) + r'["\']', html_text, re.S | re.I,
        )
    return html.unescape(match.group(1)).strip() if match else None


def parse_french_date(value: str) -> str | None:
    """Normalise '22 septembre 2026', '28/08/2026', '2026-08-28' to ISO."""
    if not value:
        return None
    value = value.strip()
    iso = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", value)
    if iso:
        return f"{iso.group(1)}-{iso.group(2)}-{iso.group(3)}"
    fr = re.search(r"\b(\d{1,2})[/.](\d{1,2})[/.](\d{4})\b", value)
    if fr:
        return f"{fr.group(3)}-{int(fr.group(2)):02d}-{int(fr.group(1)):02d}"
    named = re.search(
        r"\b(\d{1,2})\s*(?:er)?\s+([A-Za-zéûôàè]+)\s+(\d{4})\b", value
    )
    if named and named.group(2).lower() in MONTHS_FR:
        return (f"{named.group(3)}-{MONTHS_FR[named.group(2).lower()]:02d}"
                f"-{int(named.group(1)):02d}")
    return None


def published_date(html_text: str, posting: dict, text: str) -> tuple[str | None, str | None]:
    """Return (iso_date, provenance). Only proven dates are returned."""
    posted = posting.get("datePosted")
    if posted:
        iso = parse_french_date(str(posted))
        if iso:
            return iso, "JSON-LD datePosted (page de l'offre)"
    for pattern, label in (
        (r"[Oo]ffre (?:publiée|mise en ligne) le ([^\.\n]{3,40})", "mention « offre publiée le »"),
        (r"[Pp]ubli[ée]e? le ([^\.\n]{3,40})", "mention « publiée le »"),
        (r"[Ee]n ligne depuis le ([^\.\n]{3,40})", "mention « en ligne depuis le »"),
        (r"Job (?:posted|published) (?:on )?([^\.\n]{3,40})", "mention « job posted »"),
    ):
        match = re.search(pattern, text)
        if match:
            iso = parse_french_date(match.group(1))
            if iso:
                return iso, label
    return None, None


def _clean_job_text(raw_text: str) -> str:
    """Strip navigation, sidebar, and related-offer noise from visible text."""
    # Cut at related-offer headings FIRST (before nav-phrase removal changes
    # the heading text).
    text = raw_text
    for heading in (
        r"Des offres d'emplois recommand[ée]es",
        r"Offres similaires",
        r"Related (?:jobs|offers)",
        r"Vous pourriez aussi aimer",
        r"Consultez aussi",
    ):
        cut = re.search(r"(?m)^[ \t]*" + heading + r"[ \t]*$", text, re.I)
        if cut and cut.start() > 10:
            text = text[:cut.start()]
    # Then strip inline navigation / UI phrases.
    text = _NAV_RE.sub(" ", text)
    # Collapse whitespace again after removals.
    text = re.sub(r"[ \t\xa0]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    return text.strip()[:60000]


# ── Location parsing ──────────────────────────────────────────────────────

# Common French city/suffix patterns for extracting city from a location string.
_CITY_IN_LOCATION = re.compile(
    r"\b([A-ZÉÈÊËÀÂÎÏÔÛÜŸÇ][a-zéèêëàâîïôûüÿçÀ-ÿ]+(?:[- ][A-ZÉÈÊËÀÂÎÏÔÛÜŸÇ]"
    r"[a-zéèêëàâîïôûüÿçÀ-ÿ]+){0,2})\s*"
    r"(?:\([^)]*\d{2,5}[^)]*\)|\d{5}\s*\d{0,3})?\s*$",
    re.I,
)

# Country recognition delegates to locations.country_code (ISO plus aliases).


def _parse_location(location_raw: str) -> dict:
    """Return location_city, location_country, location_provenance.

    Provenance describes how the location was sourced without exposing the
    raw structured data (it is a label, not the JSON-LD snippet).
    """
    if not location_raw or location_raw in ("Non renseignée", "Non renseigné", ""):
        return {
            "location_city": None,
            "location_country": None,
            "location_provenance": "non renseignée",
        }
    parts = [p.strip() for p in location_raw.replace(",", ",").split(",") if p.strip()]
    city = None
    country = None
    for part in parts:
        if locations.country_code(part) and country is None:
            country = part
            continue
        if city is None:
            city_match = _CITY_IN_LOCATION.search(part)
            if city_match:
                city = city_match.group(1).strip()
                # If the whole part looks like a city (no numbers, short)
                if len(part) < 60 and re.match(
                    r"^[A-ZÉÈÊËÀÂÎÏÔÛÜŸÇ][a-zéèêëàâîïôûüÿçA-ZÉÈÊËÀÂÎÏÔÛÜŸÇ\- ]+$",
                    part.strip(),
                ):
                    city = part.strip()
    # If no comma-separated structure, try the whole string as city.
    if city is None and len(location_raw) < 80:
        m = _CITY_IN_LOCATION.search(location_raw)
        if m:
            city = m.group(1).strip()
    if city is None:
        city = location_raw[:60]
    return {
        "location_city": city,
        "location_country": country,
        "location_provenance": "extraite",
    }


def extract(url: str, html_text: str) -> dict:
    """Build the offer record used by the gates and by the Jev payload."""
    posting = _job_posting(html_text)
    text = visible_text(html_text)
    job_text = _clean_job_text(text)

    title = (posting.get("title") or _meta(html_text, "og:title") or "").strip()
    if not title:
        h1 = re.search(r"<h1[^>]*>(.*?)</h1>", html_text, re.S | re.I)
        if h1:
            title = html.unescape(re.sub(r"<[^>]+>", "", h1.group(1))).strip()
    if not title:
        page_title = re.search(r"<title[^>]*>(.*?)</title>", html_text, re.S | re.I)
        title = html.unescape(page_title.group(1)).strip() if page_title else url

    org = posting.get("hiringOrganization")
    if isinstance(org, dict):
        org = org.get("name")
    company = (org or _meta(html_text, "og:site_name") or "").strip()
    if not company:
        employer = re.search(r"Employeur\s*:?\s*\n?\s*([^\n]{3,80})", job_text)
        company = employer.group(1).strip() if employer else "Non renseigné"

    location_provenance_base = None
    location = ""
    job_location = posting.get("jobLocation")
    if isinstance(job_location, dict):
        address = job_location.get("address") or {}
        if isinstance(address, dict):
            country = address.get("addressCountry")
            if isinstance(country, dict):
                country = country.get("name") or country.get("identifier")
            location = ", ".join(
                str(value).strip() for value in
                (address.get("addressLocality"), address.get("addressRegion"), country)
                if isinstance(value, (str, int)) and str(value).strip()
            )
            if location:
                location_provenance_base = "JSON-LD jobLocation"
    if not location:
        loc = re.search(r"Localisation\s*:?\s*\n?\s*([^\n]{3,120})", job_text)
        if loc:
            location = loc.group(1).strip()
            location_provenance_base = "texte « Localisation »"
        else:
            location = "Non renseignée"
            location_provenance_base = "non trouvée"

    iso, provenance = published_date(html_text, posting, job_text)

    parsed = _parse_location(location)

    return {
        "url": url,
        "title": title,
        "company": company,
        "location": location,
        "location_city": parsed["location_city"],
        "location_country": parsed["location_country"],
        "location_provenance": location_provenance_base,
        "published_at": iso,
        "published_at_provenance": provenance,
        "job_text": job_text,
    }