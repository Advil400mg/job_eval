"""Extract only source-backed contract and experience facts from an offer.

This small deterministic layer is intentionally conservative: a preferred skill or
an internship mentioned as past experience is not a hiring requirement. Every
known value carries a verbatim excerpt from the offer text.
"""
from __future__ import annotations

import re

_INTERNSHIP_ROLE = re.compile(
    r"\b(?:contrat de stage|convention de stage (?:requise|obligatoire)|"
    r"stage de (?:fin d['’]études|\d+ (?:mois|semaines))|poste de stagiaire|statut étudiant (?:requis|obligatoire)|"
    r"contrat d['’]alternance|alternance (?:obligatoire|de \d+ mois)|"
    r"(?:an? )?internship (?:position|role|contract|requiring student status|of \d+ months?)|"
    r"(?:student status|internship agreement) (?:is )?required)\b",
    re.I,
)
_INTERNSHIP_TITLE = re.compile(r"^(?:stage|stagiaire|alternance|internship|intern)\b", re.I)
_PERMANENT = re.compile(r"\b(?:CDI|permanent|full[- ]time employment|indefinite contract)\b", re.I)
_JUNIOR = re.compile(r"\b(?:junior|entry[- ]level|débutant(?:s)?|jeune[s]? diplômé[s]?|"
                     r"recent graduates?|graduate[s]? welcome|0\s*(?:-|à|to)\s*[12]\s*(?:ans|years?))\b", re.I)
_SENIOR = re.compile(r"\b(?:senior|principal|expert confirmé|architecte? confirmé|"
                     r"expérience (?:professionnelle )?confirmée)\b", re.I)
# A mentor's seniority does not make the advertised role senior. Match the
# mentor's action, not a particular job title (engineer, analyst, ingénieure…).
_SENIOR_MENTOR = re.compile(
    r"(?:\b(?:senior|confirmé[e]?)\b.{0,65}\b(?:reviews?|relit|relisent|"
    r"mentors?|encadre|accompagne|assure le mentorat|provides?(?:\s+\w+){0,3}\s+training)\b|"
    r"\b(?:binômage|mentorat|paired|binômé|reviewed|revus|relus)\b.{0,65}"
    r"\b(?:senior|confirmé[e]?)\b)", re.I,
)
_YEAR_WORDS = {"zéro": 0, "zero": 0, "une": 1, "un": 1, "one": 1,
               "deux": 2, "two": 2, "trois": 3, "three": 3,
               "quatre": 4, "four": 4, "cinq": 5, "five": 5,
               "six": 6, "huit": 8, "eight": 8}
_NUMBER = r"(?:\d{1,2}|zéro|zero|une|un|one|deux|two|trois|three|quatre|four|cinq|five|six|huit|eight)"
_EXPERIENCE_RANGE = re.compile(
    rf"\b(?P<low>{_NUMBER})\s*(?:ans?|années?|years?)?\s*(?:à|-|to)\s*"
    rf"(?P<high>{_NUMBER})\s*(?:ans?|années?|years?)\b", re.I,
)
_YEARS = re.compile(
    rf"\b(?:(?:minimum(?: de)?|au moins|at least)\s*)?(?P<years>{_NUMBER})\s*"
    r"(?:\+\s*)?(?:ans?|années?|years?)(?:\s+(?:of|d['’])\s*(?:professional\s+)?experience)?\b",
    re.I,
)
_PREFERRED = re.compile(r"\b(?:preferred|preferably|souhaité[e]?|apprécié[e]?|"
                        r"un plus|nice to have|not mandatory|non obligatoire|non exigé[e]?)\b", re.I)
_REQUIRED = re.compile(r"\b(?:required|mandatory|must have|minimum|at least|"
                       r"au moins|exigé[e]?|requi[st]|obligatoire)\b", re.I)


def _number(value: str) -> int:
    return int(value) if value.isdigit() else _YEAR_WORDS[value.lower()]


def _sentences(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+|\n+", text) if part.strip()]


def _fact(value: object = None, evidence: str | None = None,
          status: str = "unknown") -> dict:
    return {"value": value, "status": status, "evidence": evidence}


def extract_facts(offer: dict) -> dict:
    """Return source-backed facts; never infer a mandatory minimum from preference."""
    text = str(offer.get("job_text") or "")
    title = str(offer.get("title") or "")
    sentences = _sentences(text)
    permanent = next((s for s in sentences if _PERMANENT.search(s) and not re.search(
        r"\b(?:pas|aucun[e]?|not|no)\b.{0,40}\b(?:CDI|permanent)\b", s, re.I
    )), None)
    internship = next((s for s in sentences if _INTERNSHIP_ROLE.search(s)), None)
    if not internship and _INTERNSHIP_TITLE.search(title):
        internship = title if title in text else next(
            (s for s in sentences if _INTERNSHIP_TITLE.search(s)), None)
    if permanent and internship:
        contract = _fact(None, internship, "contradictory")
    elif internship:
        contract = _fact("internship", internship, "known")
    elif permanent:
        contract = _fact("permanent", permanent, "known")
    else:
        contract = _fact()

    required: list[tuple[int, int | None, str]] = []
    preferred: list[tuple[int, str]] = []
    for sentence in sentences:
        spans: list[tuple[int, int]] = []
        candidates: list[tuple[int, int | None]] = []
        for match in _EXPERIENCE_RANGE.finditer(sentence):
            low = _number(match.group("low"))
            high = _number(match.group("high"))
            if high < low or high > 20:
                continue
            spans.append(match.span())
            candidates.append((low, high))
        for match in _YEARS.finditer(sentence):
            if any(start <= match.start() < end for start, end in spans):
                continue
            years = _number(match.group("years"))
            if years <= 20:
                candidates.append((years, None))
        for low, high in candidates:
            if low == 1 and high is None and re.search(
                r"\b(?:less than|under|moins d['’]|moins de)\s*(?:un|une|one|1)\s*(?:an|ann[ée]e|year)",
                sentence, re.I,
            ):
                low = 0
            explicit_required = re.search(
                r"\b(?:required|mandatory|minimum|at least|au moins|exigé[e]?)\b", sentence, re.I
            ) and not re.search(r"\b(?:not mandatory|non obligatoire|non exigé[e]?)\b", sentence, re.I)
            if _PREFERRED.search(sentence) and not explicit_required:
                preferred.append((low, sentence))
            else:
                required.append((low, high, sentence))
    minimum = min(required, key=lambda pair: pair[0]) if required else None
    wish = min(preferred, key=lambda pair: pair[0]) if preferred else None
    junior_hit = next((s for s in sentences if _JUNIOR.search(s) and not re.search(
        r"\b(?:ne mentionne ni|does not mention)\b.{0,30}\bjunior\b", s, re.I
    )), None)
    senior_hit = next((s for s in sentences if _SENIOR.search(s) and not _SENIOR_MENTOR.search(s)
                       and not re.search(
        r"\b(?:ne mentionne ni|does not mention)\b.{0,40}\bsenior\b", s, re.I
    )), None)
    junior = (_fact(None, senior_hit, "contradictory") if junior_hit and senior_hit
              else _fact(True, junior_hit, "known") if junior_hit
              else _fact(False, senior_hit, "known") if senior_hit else _fact())
    return {
        "contract": contract,
        "experience_min": _fact(minimum[0], minimum[2], "known") if minimum else _fact(),
        "experience_max": _fact(minimum[1], minimum[2], "known") if minimum and minimum[1] is not None else _fact(),
        "experience_preferred": _fact(wish[0], wish[1], "known") if wish else _fact(),
        "junior": junior,
    }
