"""Extract only source-backed contract and experience facts from an offer.

This small deterministic layer is intentionally conservative: a preferred skill or
an internship mentioned as past experience is not a hiring requirement. Every
known value carries a verbatim excerpt from the offer text.
"""
from __future__ import annotations

import re

_INTERNSHIP_ROLE = re.compile(
    r"\b(?:contrat de stage|convention de stage (?:requise|obligatoire)|"
    r"stage\w*(?:\s+\w+){0,2}\s+de (?:fin d['’]études|\d+ (?:mois|semaines))|poste de stagiaire|statut étudiant (?:requis|obligatoire)|"
    r"contrat d['’]alternance|alternance (?:obligatoire|de \d+ mois)|"
    r"(?:an? )?internship (?:position|role|contract|requiring student status|of \d+ months?)|"
    r"(?:student status|internship agreement) (?:is )?required|"
    r"apprenticeship|Praktikum)\b",
    re.I,
)
_INTERNSHIP_TITLE = re.compile(r"^(?:stage|stagiaire|alternance|internship|intern|apprenti|apprentice|Praktikant)\b", re.I)
_PERMANENT = re.compile(r"\b(?:CDI|permanent|full[- ]time employment|indefinite contract)\b", re.I)
# Fixed-term / CDD / befristet — excludes negated mentions.
_FIXED_TERM = re.compile(
    r"\b(?:CDD|contrat (?:à|a) durée déterminée|fixed[- ]term|befristet\w*|"
    r"contrat (?:à|a) durée limitée)\b", re.I,
)
_FREELANCE = re.compile(
    r"\b(?:freelance|free[- ]lance|indépendant|portage salarial|"
    r"contrat de freelance|auto[- ]entrepreneur|"
    r"travailleur indépendant|consultant indépendant)\b", re.I,
)
_PAST_CONTRACT = re.compile(
    r"\b(?:expérience|experience|background|parcours)\b.{0,35}"
    r"\b(?:en|as|in|de|comme)\s+(?:freelance|CDD|fixed[- ]term|indépendant)\b",
    re.I,
)
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
# A duration of a programme or assignment is not a candidate experience minimum.
_EXPERIENCE_CONTEXT = re.compile(
    r"\b(?:expériences?|experiences?|pratique|practice|profils? de|"
    r"justifi\w*|minimum|au moins|at least|exig\w*|requis\w*|"
    r"required|mandatory|ans? min\b|années? min\b|years? min\b)", re.I,
)
_SENIOR_PROGRESSION = re.compile(
    r"\b(?:évolution|évoluer|progression|passage)\b.{0,45}\bvers\s+"
    r"(?:un |le |une |la )?(?:poste |niveau )?(?:senior|confirmé[e]?)\b|"
    r"\b(?:à terme|par la suite|plus tard)\b[^,;.!?]{0,30}\b(?:senior|confirmé[e]?)\b", re.I,
)
# Navigation / UI phrases that must never be scanned as seniority evidence.
_NAVIGATION_SENTENCE = re.compile(
    r"\b(?:Aller au contenu principal|Skip to main content|"
    r"Aller au menu|Skip to navigation|Menu principal|"
    r"Accueil\s*[>›»/]\s*(?:Recherche|Offres|Emploi)|"
    r"Offres d'emplois recommand[ée]es|Related (?:jobs|offers)|"
    r"Vous pourriez aussi aimer|Consultez aussi)\b", re.I,
)


def _number(value: str) -> int:
    return int(value) if value.isdigit() else _YEAR_WORDS[value.lower()]


def _sentences(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+|\n+", text) if part.strip()]


def _fact(value: object = None, evidence: str | None = None,
          status: str = "unknown") -> dict:
    return {"value": value, "status": status, "evidence": evidence}


def _negated(sentence: str, keyword: str) -> bool:
    """True when *keyword* in *sentence* is explicitly negated.

    Uses word-level proximity so that 'pas un CDD mais un CDI' correctly
    negates CDD but not CDI.
    """
    return bool(re.search(
        rf"\b(?:pas|aucun[e]?|not|no)\b(?:\s+\S+){{0,3}}\s+\b{keyword}\b",
        sentence, re.I,
    ))


def _contract_fact(text: str, title: str, sentences: list[str]) -> dict:
    """Extract contract-type fact from sentences, returning a fact dict.

    Only recognised when the offer context explicitly states the type.
    Past-experience mentions (e.g. "a first internship" where the role itself
    is CDI) are excluded by the regex patterns — they require the role/contract
    to be advertised, not merely mentioned.
    """
    # Map type → (sentence, keyword_for_negation_check)
    candidates: dict[str, str] = {}

    # Permanent
    perm = next((s for s in sentences if _PERMANENT.search(s)
                 and not _negated(s, "CDI")
                 and not _negated(s, "permanent")), None)
    if perm:
        candidates["permanent"] = perm

    # Internship / apprenticeship
    intern = next((s for s in sentences if _INTERNSHIP_ROLE.search(s)), None)
    if not intern and _INTERNSHIP_TITLE.search(title):
        intern = title if title in text else next(
            (s for s in sentences if _INTERNSHIP_TITLE.search(s)), None)
    if intern:
        candidates["internship"] = intern

    # Fixed-term / CDD
    fixed_term = next((s for s in sentences if _FIXED_TERM.search(s)
                       and not _PAST_CONTRACT.search(s)
                       and not _negated(s, "CDD")
                       and not _negated(s, "fixed.?term")
                       and not _negated(s, "befristet")), None)
    if fixed_term:
        candidates["fixed_term"] = fixed_term

    # Freelance
    freelance = next((s for s in sentences if _FREELANCE.search(s)
                      and not _PAST_CONTRACT.search(s)
                      and not re.search(r"\bindépendant d['’]esprit\b", s, re.I)
                      and not _negated(s, "freelance")
                      and not _negated(s, "indépendant")), None)
    if freelance:
        candidates["freelance"] = freelance

    if len(candidates) > 1:
        first_type, first_evidence = next(iter(candidates.items()))
        return _fact(None, first_evidence, "contradictory")
    if len(candidates) == 1:
        ctype, cevidence = next(iter(candidates.items()))
        return _fact(ctype, cevidence, "known")
    return _fact()


def _experience_facts(sentences: list[str]) -> dict:
    """Extract experience-minimum facts from sentences."""
    required: list[tuple[int, int | None, str, bool]] = []
    preferred: list[tuple[int, str]] = []
    for sentence in sentences:
        if not _EXPERIENCE_CONTEXT.search(sentence):
            continue
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
            # "Une année passée en formation" describes the programme, even if
            # another clause in the sentence mentions professional experience.
            if re.match(r"\s+(?:passée?|spent|de formation|d['’]apprentissage)\b",
                        sentence[match.end():], re.I):
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
                required.append((low, high, sentence, bool(explicit_required)))
    # A generic junior range must not erase an explicit, stricter minimum in
    # the same offer. Preferences were separated above and cannot hard-fail.
    explicit_minima = [item for item in required if item[3]]
    minimum = (max(explicit_minima, key=lambda item: item[0]) if explicit_minima
               else min(required, key=lambda item: item[0]) if required else None)
    wish = min(preferred, key=lambda pair: pair[0]) if preferred else None
    return {
        "experience_min": _fact(minimum[0], minimum[2], "known") if minimum else _fact(),
        "experience_max": _fact(minimum[1], minimum[2], "known") if minimum and minimum[1] is not None else _fact(),
        "experience_preferred": _fact(wish[0], wish[1], "known") if wish else _fact(),
    }


def _junior_fact(sentences: list[str]) -> dict:
    """Extract junior/senior level fact from sentences, filtering navigation."""
    junior_hit = next((s for s in sentences if _JUNIOR.search(s) and not re.search(
        r"\b(?:ne mentionne ni|does not mention)\b.{0,30}\bjunior\b", s, re.I
    )), None)
    senior_hit = None
    for sentence in sentences:
        # Skip sentences that are purely navigation / UI chrome.
        if _NAVIGATION_SENTENCE.search(sentence):
            continue
        if re.search(r"\b(?:ne mentionne ni|does not mention)\b.{0,40}\bsenior\b",
                     sentence, re.I):
            continue
        exclusions = [match.span() for pattern in (_SENIOR_MENTOR, _SENIOR_PROGRESSION)
                      for match in pattern.finditer(sentence)]
        if any(not any(start <= hit.start() < end for start, end in exclusions)
               for hit in _SENIOR.finditer(sentence)):
            senior_hit = sentence
            break
    return _fact(None, senior_hit, "contradictory") if junior_hit and senior_hit \
        else _fact(True, junior_hit, "known") if junior_hit \
        else _fact(False, senior_hit, "known") if senior_hit else _fact()


def extract_facts(offer: dict) -> dict:
    """Return source-backed facts; never infer a mandatory minimum from preference.

    Contract type supports: permanent, fixed_term, freelance, internship.
    Facts are intentionally conservative — only explicitly advertised terms.
    """
    text = str(offer.get("job_text") or "")
    title = str(offer.get("title") or "")
    sentences = _sentences(text)
    junior = _junior_fact(sentences)
    experience = _experience_facts(sentences)
    return {
        "contract": _contract_fact(text, title, sentences),
        **experience,
        "junior": junior,
    }