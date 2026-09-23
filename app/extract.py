"""Fetch and extract job-offer content from a URL (stdlib only)."""

from __future__ import annotations

import html
import json
import re
import urllib.error
import urllib.request

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


class FetchError(RuntimeError):
    pass


def fetch_html(url: str, timeout: int = 30) -> str:
    """Download a page, retrying once on transient errors."""
    if not re.match(r"^https?://", url, re.I):
        raise FetchError("URL must start with http:// or https://")
    last = None
    for attempt in range(2):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "fr,en;q=0.8",
            })
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                charset = resp.headers.get_content_charset() or "utf-8"
                return resp.read().decode(charset, "replace")
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError) as exc:
            last = exc
    raise FetchError(f"Fetch failed: {last}")


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


def extract(url: str, html_text: str) -> dict:
    """Build the offer record used by the gates and by the Jev payload."""
    posting = _job_posting(html_text)
    text = visible_text(html_text)

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
        employer = re.search(r"Employeur\s*:?\s*\n?\s*([^\n]{3,80})", text)
        company = employer.group(1).strip() if employer else "Non renseigné"

    location = ""
    job_location = posting.get("jobLocation")
    if isinstance(job_location, dict):
        address = job_location.get("address") or {}
        if isinstance(address, dict):
            location = ", ".join(
                filter(None, [address.get("addressLocality"),
                              address.get("addressRegion"),
                              address.get("addressCountry")])
            )
    if not location:
        loc = re.search(r"Localisation\s*:?\s*\n?\s*([^\n]{3,120})", text)
        location = loc.group(1).strip() if loc else "Non renseignée"

    iso, provenance = published_date(html_text, posting, text)

    job_text = text
    # Keep the offer body, drop the "recommended offers" tail when identifiable.
    cut = re.search(r"Des offres d'emplois recommand[ée]es", job_text)
    if cut and cut.start() > 200:
        job_text = job_text[:cut.start()]
    job_text = job_text[:60000]

    return {
        "url": url,
        "title": title,
        "company": company,
        "location": location,
        "published_at": iso,
        "published_at_provenance": provenance,
        "job_text": job_text,
    }