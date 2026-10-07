"""Fetch and extract source-backed job content with DOM and text parsers."""

from __future__ import annotations

import html
import json
import re
from copy import deepcopy
from urllib.parse import urljoin, urlsplit, urlunsplit

from lxml import etree
from lxml import html as dom_html
import trafilatura

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


def _document(html_text: str):
    # The response has already been decoded by network.fetch_text. Encoding it
    # explicitly avoids a conflicting page charset reinterpreting Unicode.
    parser = dom_html.HTMLParser(encoding="utf-8", no_network=True, recover=True)
    try:
        return dom_html.document_fromstring(html_text.encode("utf-8"), parser=parser)
    except (etree.ParserError, ValueError) as exc:
        raise ValueError("HTML vide ou inexploitable") from exc


def _postings(tree) -> list[dict]:
    jobs = []
    for script in tree.iter("script"):
        mime = script.get("type", "").split(";", 1)[0].strip().casefold()
        if mime != "application/ld+json":
            continue
        try:
            data = json.loads(script.text or "")
        except (ValueError, RecursionError):
            continue
        pending = [data]
        while pending:
            node = pending.pop()
            if isinstance(node, list):
                pending.extend(reversed(node))
            elif isinstance(node, dict):
                kinds = node.get("@type", [])
                kinds = [kinds] if isinstance(kinds, str) else kinds
                if isinstance(kinds, list) and any(
                    isinstance(kind, str) and kind.rstrip("/").rsplit("/", 1)[-1] == "JobPosting"
                    for kind in kinds
                ):
                    if node not in jobs:
                        jobs.append(node)
                    # Nested metadata belongs to this job, not another page.
                    continue
                pending.extend(reversed([v for v in node.values() if isinstance(v, (dict, list))]))
    return jobs


def _same_page(value: object, url: str) -> bool:
    if isinstance(value, dict):
        value = value.get("@id") or value.get("url")
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        def canonical(raw):
            parts = urlsplit(raw)
            return urlunsplit((parts.scheme.casefold(), parts.netloc.casefold(),
                               parts.path.rstrip("/") or "/", parts.query, ""))
        return canonical(urljoin(url, value)) == canonical(url)
    except ValueError:
        return False


def _selected_posting(tree, url: str | None = None) -> dict:
    jobs = _postings(tree)
    if len(jobs) <= 1:
        return jobs[0] if jobs else {}
    matches = [job for job in jobs if url and any(
        _same_page(job.get(field), url) for field in ("url", "@id", "mainEntityOfPage")
    )]
    if len(matches) == 1:
        return matches[0]
    raise ValueError("Plusieurs annonces JobPosting sans correspondance unique avec l'URL")


def _job_posting(html_text: str, url: str | None = None) -> dict:
    """Decode real DOM attributes and select only the requested job."""
    return _selected_posting(_document(html_text), url)


_BLOCK_TAGS = frozenset({"p", "li", "div", "section", "article", "main", "header",
                         "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "tr", "dl", "dt", "dd"})
_HIDDEN_TAGS = frozenset({"script", "style", "noscript", "svg", "template", "nav", "footer"})


def _tree_text(tree) -> str:
    parts = []

    def walk(node):
        if not isinstance(node.tag, str) or node.tag.casefold() in _HIDDEN_TAGS:
            return
        tag = node.tag.casefold()
        if tag in _BLOCK_TAGS or tag == "br":
            parts.append("\n")
        if node.text:
            parts.append(node.text)
        for child in node:
            walk(child)
            if child.tail:
                parts.append(child.tail)
        if tag in _BLOCK_TAGS:
            parts.append("\n")
        elif tag in {"td", "th"}:
            parts.append(" ")

    walk(tree)
    lines = [re.sub(r"[ \t\xa0]+", " ", line).strip()
             for line in "".join(parts).splitlines()]
    return "\n".join(line for line in lines if line)


def visible_text(html_text: str) -> str:
    """Extract text nodes, never attribute fragments or script/style contents."""
    if not html_text or not html_text.strip():
        return ""
    return _tree_text(_document(html_text))


def _meta_from_tree(tree, prop: str) -> str | None:
    for node in tree.iter("meta"):
        if node.get("property") == prop or node.get("name") == prop:
            value = node.get("content", "").strip()
            if value:
                return value
    return None


def _meta(html_text: str, prop: str) -> str | None:
    return _meta_from_tree(_document(html_text), prop)


def parse_french_date(value: str) -> str | None:
    """Normalise '22 septembre 2026', '28/08/2026', '2026-08-28' to ISO."""
    if not value:
        return None
    value = value.strip()
    iso = re.search(r"\b(\d{4})-(\d{2})-(\d{2})(?:[Tt]|\b)", value)
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


_RELATED_HEADINGS = (
    r"Des offres d['’]emplois recommand[ée]es", r"Offres similaires",
    r"Related (?:jobs|offers)", r"Vous pourriez aussi aimer", r"Consultez aussi",
    r"Ces offres pourraient aussi\s+vous intéresser", r"Recherches similaires",
)


def _trim_related(tree) -> None:
    """Cut the DOM at an exact related-offer heading before content extraction."""
    for node in tree.iter():
        if not isinstance(node.tag, str) or node.tag.casefold() not in _BLOCK_TAGS:
            continue
        text = _tree_text(node).strip()
        if not any(re.fullmatch(pattern, text, re.I) for pattern in _RELATED_HEADINGS):
            continue
        path = [node, *node.iterancestors()]
        for current in path:
            current.tail = None
            parent = current.getparent()
            if parent is not None:
                for sibling in list(current.itersiblings()):
                    parent.remove(sibling)
        parent = node.getparent()
        if parent is not None:
            parent.remove(node)
        return


def _clean_job_text(raw_text: str) -> str:
    """Strip navigation, sidebar, and related-offer noise from visible text."""
    # Cut at related-offer headings FIRST (before nav-phrase removal changes
    # the heading text).
    text = raw_text
    for heading in _RELATED_HEADINGS:
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


def _source_string(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        return ""
    return " ".join(visible_text(html.unescape(value)).split())


def _structured_locations(posting: dict) -> list[str]:
    nodes = posting.get("jobLocation")
    nodes = nodes if isinstance(nodes, list) else [nodes]
    result = []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        address = node.get("address") or {}
        if not isinstance(address, dict):
            continue
        country = address.get("addressCountry")
        if isinstance(country, dict):
            country = country.get("name") or country.get("identifier")
        parts = [_source_string(value) for value in (
            address.get("addressLocality"), address.get("addressRegion"), country,
        )]
        location = ", ".join(part for part in parts if part)
        if location and location not in result:
            result.append(location)
    return result


def _offer_scope(tree):
    for selector in ("//main", "//article", "//body"):
        nodes = tree.xpath(selector)
        if nodes:
            return nodes[0], selector != "//body"
    return tree, False


def _offer_body(tree, posting: dict, scoped_text: str, scoped: bool) -> str:
    description = posting.get("description")
    if isinstance(description, str) and description.strip():
        body = _clean_job_text(visible_text(html.unescape(description)))
        if body:
            return body
    if scoped:
        return scoped_text
    # Feed the already-pruned body to Trafilatura, never the whole page shell.
    cleaned = deepcopy(tree)
    for node in list(cleaned.iter()):
        if isinstance(node.tag, str) and node.tag.casefold() in _HIDDEN_TAGS | {"head"}:
            if node.getparent() is not None:
                node.drop_tree()
    _trim_related(cleaned)
    content = dom_html.tostring(cleaned, encoding="unicode")
    body = trafilatura.extract(content, include_comments=False, include_tables=True,
                               favor_precision=True, with_metadata=False)
    return _clean_job_text(body) if body else scoped_text


def extract(url: str, html_text: str) -> dict:
    """Build the existing offer shape from a selected, source-backed document."""
    tree = _document(html_text)
    posting = _selected_posting(tree, url)
    scope, scoped = _offer_scope(tree)
    scoped_text = _clean_job_text(_tree_text(scope))
    body = _offer_body(tree, posting, scoped_text, scoped)
    if not body.strip():
        raise ValueError("La page ne contient aucun texte d'offre exploitable")

    title = _source_string(posting.get("title"))
    if not title:
        headings = scope.xpath(".//h1")
        title = _tree_text(headings[0]) if headings else ""
    if not title:
        title = _meta_from_tree(tree, "og:title") or _meta_from_tree(tree, "twitter:title") or ""
    if not title:
        titles = tree.xpath("//title")
        title = _tree_text(titles[0]) if titles else url
    title = " ".join(title.split())

    org = posting.get("hiringOrganization")
    if isinstance(org, dict):
        org = org.get("name")
    company = _source_string(org)
    if not company:
        employer = re.search(r"Employeur[ \t]*:?[ \t]*\n?[ \t]*([^\n]{3,80})", scoped_text, re.I)
        company = employer.group(1).strip() if employer else "Non renseigné"

    places = _structured_locations(posting)
    location = places[0] if len(places) == 1 else ""
    location_provenance = "JSON-LD jobLocation" if location else "non trouvée"
    if len(places) > 1:
        # The existing gate understands one location only. Retain all source
        # places in the document, but do not claim a proven single geography.
        location_provenance = "plusieurs lieux JSON-LD — choix non déterminé"
    elif not location:
        match = re.search(r"Localisation[ \t]*:?[ \t]*\n?[ \t]*([^\n]{3,120})", scoped_text, re.I)
        if match:
            location = match.group(1).strip()
            location_provenance = "texte « Localisation »"
    location = location or "Non renseignée"

    dated_posting = posting if isinstance(posting.get("datePosted"), str) else {}
    iso, provenance = published_date(html_text, dated_posting, scoped_text)
    parsed = _parse_location(location)

    # Include only available source metadata. It may be outside the description
    # in the DOM, but must not disappear merely because the text cleaner omits it.
    context = [title]
    if company != "Non renseigné":
        context.append("Employeur : " + company)
    if len(places) > 1:
        context.append("Lieux de travail annoncés : " + "; ".join(places))
    elif location != "Non renseignée":
        context.append("Localisation : " + location)
    kinds = posting.get("employmentType") or []
    kinds = [kinds] if isinstance(kinds, str) else kinds
    if isinstance(kinds, list):
        kinds = [_source_string(kind) for kind in kinds]
        if any(kinds):
            context.append("Type d'emploi : " + ", ".join(kind for kind in kinds if kind))
    if iso:
        context.append("Date de publication : " + iso)
    job_text = _clean_job_text("\n".join(context + [body]))

    return {
        "url": url,
        "title": title,
        "company": company,
        "location": location,
        "location_city": parsed["location_city"],
        "location_country": parsed["location_country"],
        "location_provenance": location_provenance,
        "published_at": iso,
        "published_at_provenance": provenance,
        "job_text": job_text,
    }