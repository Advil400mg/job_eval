"""Separate source-backed uncertainty from Jev's configured weighted score.

The four standard dimensions are explanatory, not a replacement for profile
criteria. A proven hard rejection is never turned into a review by missing data.
"""
from __future__ import annotations

import re

from . import gates

_WORK_UNCERTAINTY = re.compile(
    r"\b(?:astreintes?|on-call|déplacements|travel|interventions sur site)\b.*"
    r"(?:volume exact|fréquence|compensation|night frequency|autonomy|"
    r"(?:n['’]est|ne sont) pas (?:indiqu|communiqu|précis)\w*|"
    r"not (?:stated|given|provided|described)|does not state|"
    r"unspecified|unclear|undisclosed|inconnue?s?)", re.I,
)
_ENGLISH = re.compile(r"\b(?:anglais|english|anglophone)\b", re.I)
_ENGLISH_MANDATORY = re.compile(
    r"\b(?:exclusiv\w*|seul[e]?s?|uniquement|obligatoire|exig\w*|"
    r"couran\w*|professionnel\w*|indispensable|essential|fluent|mandatory|required|must|"
    r"only|sole|exclusively|working language)\b", re.I,
)
_ENGLISH_OPTIONAL = re.compile(
    r"\b(?:anglais|english)\b.{0,55}\b(?:optional|not required|non exigé|"
    r"facultatif|not mandatory|pas obligatoire)\b", re.I,
)
_REMOTE_UNKNOWN = re.compile(
    r"(?:does not identify the employing country|permitted countries|"
    r"can legally be hired|pays d'embauche non précisé)", re.I,
)
_ASSIGNMENT_UNKNOWN = re.compile(
    r"(?:first assignment will be decided after joining|"
    r"premier client.{0,90}(?:pas connus|non connu)|"
    r"futures missions dépendront des besoins|"
    r"(?:ne (?:sait|savons|savent) pas encore|not yet known).{0,110}"
    r"(?:client|mission|affectation|outils|assignment)|"
    r"(?:client|mission|affectation|outils|assignment).{0,90}"
    r"(?:reste(?:nt)? à définir|non confirmé[e]?s?|not yet defined|to be determined))", re.I,
)
_EXPLICIT_NONTECHNICAL = re.compile(
    r"(?:there are no cybersecurity.{0,120}responsibilities|"
    r"ne (?:comprend|comporte|prévoit) (?:pas |ni |aucun[e]? ).{0,110}"
    r"(?:technique|sécurité|détection|ingénierie)|"
    r"no (?:technical )?cybersecurity (?:duties|responsibilities))",
    re.I,
)


def _matching_sentence(text: str, pattern: re.Pattern) -> str | None:
    sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+|\n+", text)
                 if part.strip()]
    for index, excerpt in enumerate(sentences):
        if pattern.search(excerpt):
            return excerpt
        if pattern is _WORK_UNCERTAINTY and index + 1 < len(sentences):
            following = sentences[index + 1]
            if pattern.search(excerpt + " " + following):
                start = text.find(excerpt)
                end = text.find(following, start + len(excerpt))
                if start >= 0 and end >= 0:
                    return text[start:end + len(following)]
    return None


def _required_english_sentence(text: str) -> str | None:
    """A language mentioned as optional is not an eligibility requirement."""
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", text):
        excerpt = sentence.strip()
        if (_ENGLISH.search(excerpt) and _ENGLISH_MANDATORY.search(excerpt)
                and not _ENGLISH_OPTIONAL.search(excerpt)):
            return excerpt
    return None


def assess_evaluation(jev_result: dict, facts: dict, gate_results: list[dict],
                      offer: dict, profile: dict) -> dict:
    """Add review flags without altering Jev scores or inventing a source quote."""
    decision = gates.decide(jev_result, gate_results, facts)
    text = offer.get("job_text") or ""
    missing: list[dict] = []
    flags: list[str] = []
    reasons: list[str] = []

    for name in ("contract", "experience_min", "junior"):
        fact = facts.get(name, {})
        if fact.get("status") in ("unknown", "contradictory"):
            missing.append({"field": name, "status": fact.get("status"),
                            "evidence": fact.get("evidence")})
            flags.append(f"{fact.get('status')}:{name}")

    for field, pattern, reason in (
        ("work_conditions", _WORK_UNCERTAINTY, "volume des déplacements ou astreintes non précisé"),
        ("employment_country", _REMOTE_UNKNOWN, "pays employeur ou droit au télétravail non précisé"),
        ("first_assignment", _ASSIGNMENT_UNKNOWN, "première mission non confirmée"),
    ):
        evidence = _matching_sentence(text, pattern)
        if evidence:
            missing.append({"field": field, "status": "unknown", "evidence": evidence})
            flags.append(f"unknown:{field}")
            reasons.append(reason)

    requirement = _required_english_sentence(text)
    languages = (profile.get("candidate") or {}).get("languages") or {}
    # The presence of a language name without a proficiency level proves nothing.
    english_level = languages.get("en") or languages.get("english") if isinstance(languages, dict) else None
    if requirement and not english_level:
        missing.append({"field": "candidate_english_level", "status": "unknown",
                        "evidence": requirement})
        flags.append("unknown:candidate_english_level")
        reasons.append("niveau d'anglais requis, mais non vérifiable dans le profil")

    dimensions = jev_result.get("dimensions") or []
    clarity = next((dimension for dimension in dimensions if dimension.get("id") == "clarity"), {})
    if jev_result.get("jev_approved") and clarity.get("score", 100) < 40:
        flags.append("low_clarity")
        reasons.append("clarté de l'offre jugée insuffisante par Jev")

    score = jev_result.get("global_score")
    threshold = jev_result.get("minimum_global_score")
    if (score is not None and threshold is not None
            and abs(score - threshold) <= 2):
        flags.append("near_threshold")
        reasons.append("score proche du seuil global — vérification recommandée")

    for cid in jev_result.get("low_confidence_criteria") or []:
        flags.append(f"low_confidence:{cid}")
    for criterion in jev_result.get("criteria") or []:
        if criterion.get("required") and criterion.get("passed") and not criterion.get("evidence"):
            flags.append(f"missing_evidence:{criterion['id']}")

    # An unresolved, source-backed assignment stays reviewable even when Jev's
    # independent score is below threshold; model confidence cannot erase it.
    # A proven hard gate still rejects, and the clear technical rejection below
    # remains authoritative.
    if (reasons and not decision["hard_gate_failures"]
            and decision["status"] in ("qualified", "review_required", "rejected")):
        decision["status"] = "review_required"
        decision["review_required"] = True
        decision["review_reasons"] = list(dict.fromkeys(decision["review_reasons"] + reasons))
    explicit_exclusion = _matching_sentence(text, _EXPLICIT_NONTECHNICAL)
    technical = next((item for item in dimensions if item.get("id") == "technical"), {})
    if not technical:
        technical = next((item for item in jev_result.get("criteria") or []
                          if item.get("id") == "technical_fit"), {})
    # A clearly non-cyber role may lack stated experience. That unknown cannot
    # override a confident Jev rejection on the required technical criterion.
    if (decision["status"] == "review_required" and not jev_result.get("jev_approved")
            and technical.get("score", 100) < 25
            and technical.get("confidence", 0) >= max(
                jev_result.get("minimum_confidence", 0.5), 0.8)):
        decision["status"] = "rejected"
        decision["review_required"] = False
        decision["review_reasons"] = []
        decision["technical_rejection"] = {"score": technical["score"],
                                           "confidence": technical["confidence"]}
        if explicit_exclusion:
            decision["explicit_exclusion"] = explicit_exclusion
        flags.append("confident_non_technical")
    return {"decision": decision, "dimensions": dimensions,
            "missing_information": missing, "quality_flags": list(dict.fromkeys(flags)),
            "review_required": decision["review_required"], "evaluation_schema_version": 2}
