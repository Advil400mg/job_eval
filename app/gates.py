"""Hard gates applied before/next to the Jev score.

Mirrors the rules of PROFILE.json (hard_rejection_rules, freshness,
experience_filter). A gate never rewrites a Jev score: it only restricts
whether an offer can be qualified.
"""

from __future__ import annotations

import re
from datetime import date, datetime

from .job_facts import extract_facts
from . import locations, policy

STUDENT_RE = re.compile(
    r"\b(stage|stagiaire|internship|alternance|apprentissage|apprenti|"
    r"contrat de professionnalisation|statut étudiant|etudiant|Praktikum)\b",
    re.I,
)

JUNIOR_HINT_RE = re.compile(
    r"\b(débutant accepté|niveau débutant|jeune diplômé|junior|première expérience|"
    r"0 ?[-à] ?[12] ans|entry[- ]level|graduate|sortie d'école)\b",
    re.I,
)

EXPIRED_RE = re.compile(
    r"(n'est plus disponible|offre expirée|offre retirée|poste pourvu|"
    r"candidature clôturée|candidatures closes|this (?:job|position) is no longer)",
    re.I,
)


def contract_gate(text: str, facts: dict | None = None) -> dict:
    contract = (facts or extract_facts({"job_text": text}))["contract"]
    if contract["status"] == "contradictory":
        return {"gate": "contract_type", "status": "warn", "hard": False,
                "reason": "mentions de contrat contradictoires — à vérifier"}
    if contract["value"] == "internship":
        return {"gate": "contract_type", "status": "fail", "hard": True,
                "reason": f"stage ou alternance exigé (« {contract['evidence']} »)"}
    offer = text[:8000]
    kinds = []
    for pattern, label in (
        (r"\bCDI\b", "CDI"), (r"\bCDD\b", "CDD"),
        (r"\bcontractuel", "contractuel"), (r"\btitulaire", "titulaire"),
        (r"\bpermanent\b", "permanent"), (r"\bVIE\b", "VIE"),
        (r"\bfreelance\b", "freelance"),
    ):
        if re.search(pattern, offer, re.I):
            kinds.append(label)
    if kinds:
        return {"gate": "contract_type", "status": "pass", "hard": True,
                "reason": "type de contrat explicite : " + ", ".join(dict.fromkeys(kinds))}
    return {"gate": "contract_type", "status": "unknown", "hard": False,
            "reason": "type de contrat non identifiable dans la page"}


def contract_gate_for_profile(text: str, facts: dict, accepted: list[str]) -> dict:
    """Apply only the user's chosen contract exclusions, never a global internship ban."""
    fact = facts["contract"]
    if fact["status"] == "contradictory":
        return {"gate": "contract_type", "status": "warn", "hard": False,
                "reason": "mentions de contrat contradictoires — à vérifier"}
    if not accepted:
        return {"gate": "contract_type", "status": "pass", "hard": False,
                "reason": "aucune restriction de contrat déclarée (type non présumé)"}
    if fact["status"] != "known":
        return {"gate": "contract_type", "status": "unknown", "hard": False,
                "reason": "type de contrat non prouvé dans l'offre"}
    if fact["value"] not in accepted:
        return {"gate": "contract_type", "status": "fail", "hard": True,
                "reason": f"contrat {fact['value']} non accepté (« {fact['evidence']} »)"}
    return {"gate": "contract_type", "status": "pass", "hard": True,
            "reason": f"contrat accepté (« {fact['evidence']} »)"}


def experience_gate(text: str, reject_at_years: int = 2,
                    allowed_max_range: int = 2,
                    facts: dict | None = None) -> dict:
    """Reject only proven mandatory experience; preferences never become minima."""
    facts = facts or extract_facts({"job_text": text})
    minimum = facts["experience_min"]
    preferred = facts["experience_preferred"]
    junior_fact = facts["junior"]
    if minimum["status"] == "known":
        low = minimum["value"]
        maximum = facts.get("experience_max", {})
        high = maximum.get("value") if maximum.get("status") == "known" else None
        wording = minimum["evidence"]
    elif preferred["status"] == "known":
        return {"gate": "experience", "status": "warn", "hard": False,
                "reason": f"{preferred['value']} ans souhaités, pas exigés — accessibilité à vérifier"}
    else:
        low, high, wording = None, None, None
    explicit_unstated = bool(re.search(
        r"expérience (?:souhaitée|requise)\s*:?\s*(?:non renseigné|non renseignée)",
        text, re.I))
    junior = junior_fact["value"] is True
    junior_match = JUNIOR_HINT_RE.search(text) if junior else None
    junior_word = junior_match.group(0) if junior_match else junior_fact.get("evidence") or "junior"
    if low is None:
        if junior_fact["status"] == "contradictory":
            return {"gate": "experience", "status": "warn", "hard": False,
                    "reason": "indices de séniorité et d'accès junior contradictoires"}
        if not junior and explicit_unstated:
            return {"gate": "experience", "status": "pass", "hard": True,
                    "reason": "expérience requise « non renseignée » sur la fiche"}
        if junior and re.search(
            r"\b(?:définir seul|approuver les exceptions|astreinte critique|"
            r"lead (?:the |a )?team|own (?:the )?(?:security )?strategy)\b", text, re.I
        ):
            return {"gate": "experience", "status": "warn", "hard": False,
                    "reason": "intitulé junior, mais responsabilités de niveau confirmé"}
        if junior:
            return {"gate": "experience", "status": "pass", "hard": True,
                    "reason": f"aucun minimum en années ; mention junior explicite "
                              f"(« {junior_word} »)"}
        return {"gate": "experience", "status": "unknown", "hard": False,
                "reason": "aucun minimum d'expérience écrit en années, "
                          "aucune mention junior — non prouvable"}
    if low >= reject_at_years:
        return {"gate": "experience", "status": "fail", "hard": True,
                "reason": f"minimum exigé ≥ {reject_at_years} ans (« {wording} »)"}
    if high is not None and high > allowed_max_range:
        if junior:
            return {"gate": "experience", "status": "warn", "hard": False,
                    "reason": f"fourchette {low}-{high} ans et ouverture junior — vérifier l'exigence réelle"}
        return {"gate": "experience", "status": "fail", "hard": True,
                "reason": f"fourchette {low}-{high} ans sans mention junior/entry-level "
                          f"(« {wording} »)"}
    if junior_fact["status"] == "contradictory":
        return {"gate": "experience", "status": "warn", "hard": False,
                "reason": f"« {wording} » mais corps d'annonce au registre senior"}
    return {"gate": "experience", "status": "pass", "hard": True,
            "reason": f"exigence compatible (« {wording} »)"
                      + (f" + mention junior (« {junior_word} »)" if junior else "")}


def experience_gate_for_profile(facts: dict, candidate_years: float | None,
                                reject_at_years: int | None) -> dict:
    """Only an explicit required minimum can disqualify a structured profile."""
    minimum = facts["experience_min"]
    preferred = facts["experience_preferred"]
    if minimum["status"] == "contradictory":
        return {"gate": "experience", "status": "warn", "hard": False,
                "reason": "exigences d'expérience contradictoires — à vérifier"}
    if minimum["status"] != "known":
        if preferred["status"] == "known":
            return {"gate": "experience", "status": "warn", "hard": False,
                    "reason": f"{preferred['value']} ans souhaités, sans minimum exigé"}
        return {"gate": "experience", "status": "unknown", "hard": False,
                "reason": "aucun minimum d'expérience prouvé ; compatibilité à vérifier"}
    minimum_years = minimum["value"]
    evidence = minimum["evidence"]
    if (reject_at_years is not None and minimum_years >= reject_at_years) or (
            candidate_years is not None and minimum_years > candidate_years):
        return {"gate": "experience", "status": "fail", "hard": True,
                "reason": f"minimum exigé {minimum_years} ans incompatible (« {evidence} »)"}
    if candidate_years is None and minimum_years > 0:
        return {"gate": "experience", "status": "unknown", "hard": False,
                "reason": f"minimum exigé {minimum_years} ans, expérience du candidat non déclarée (« {evidence} »)"}
    return {"gate": "experience", "status": "pass", "hard": True,
            "reason": f"minimum exigé compatible (« {evidence} »)"}


def freshness_gate(published_at: str | None, max_age_days: int) -> dict:
    if not published_at:
        return {"gate": "freshness", "status": "fail", "hard": True,
                "reason": "date de publication non prouvable dans la page"}
    try:
        pub = datetime.strptime(published_at, "%Y-%m-%d").date()
    except ValueError:
        return {"gate": "freshness", "status": "fail", "hard": True,
                "reason": f"date de publication illisible ({published_at})"}
    age = (date.today() - pub).days
    if age < -1:
        return {"gate": "freshness", "status": "fail", "hard": True,
                "reason": f"date de publication dans le futur ({published_at})"}
    if age > max_age_days:
        return {"gate": "freshness", "status": "fail", "hard": True,
                "reason": f"publiée il y a {age} jours (> {max_age_days} j)"}
    return {"gate": "freshness", "status": "pass", "hard": True,
            "reason": f"publiée il y a {age} jour(s), dans la fenêtre de {max_age_days} j"}


def availability_gate(text: str) -> dict:
    hit = EXPIRED_RE.search(text)
    if hit:
        return {"gate": "availability", "status": "fail", "hard": True,
                "reason": f"page indique que l'offre n'est plus ouverte (« {hit.group(0)} »)"}
    deadline = re.search(
        r"[Dd]ate limite (?:de d[ée]p[ôo]t des candidatures|[^:\n]{0,30})\s*:?\s*"
        r"(\d{1,2}[/.]\d{1,2}[/.]\d{4}|\d{4}-\d{2}-\d{2})", text)
    if deadline:
        raw = deadline.group(1)
        try:
            if re.match(r"\d{4}-", raw):
                lim = datetime.strptime(raw, "%Y-%m-%d").date()
            else:
                day, month, year = re.split(r"[/.]", raw)
                lim = date(int(year), int(month), int(day))
        except ValueError:
            lim = None
        if lim:
            if lim < date.today():
                return {"gate": "availability", "status": "fail", "hard": True,
                        "reason": f"date limite de candidature dépassée ({lim.isoformat()})"}
            return {"gate": "availability", "status": "pass", "hard": True,
                    "reason": f"candidatures ouvertes jusqu'au {lim.isoformat()}"}
    return {"gate": "availability", "status": "pass", "hard": True,
            "reason": "page servie avec contenu d'offre complet, aucune mention de clôture"}


def run_gates(offer: dict, profile: dict, facts: dict | None = None) -> list[dict]:
    search = profile.get("search", {})
    exp_filter = search.get("experience_filter", {})
    reject_at = exp_filter.get("reject_if_minimum_required_years_gte", 2)
    max_age = search.get("max_age_days", 30)
    text = offer.get("job_text", "")
    facts = facts if facts is not None else extract_facts(offer)
    if policy.structured(profile):
        return [
            contract_gate_for_profile(text, facts, search.get("contract_types", [])),
            experience_gate_for_profile(facts, exp_filter.get("candidate_years"), reject_at),
            locations.location_gate(offer, search.get("locations", []),
                                    search.get("preferred_locations", [])),
            freshness_gate(offer.get("published_at"), max_age),
            availability_gate(text),
        ]
    return [
        contract_gate(text, facts),
        experience_gate(text, reject_at, facts=facts),
        freshness_gate(offer.get("published_at"), max_age),
        availability_gate(text),
    ]


def decide(jev_result: dict, gates: list[dict], facts: dict | None = None) -> dict:
    """Keep Jev's raw verdict; separate proven exclusion from human review."""
    hard_failed = [g for g in gates if g["status"] == "fail" and g.get("hard")]
    approved = bool(jev_result.get("jev_approved"))
    warnings = [{"gate": g["gate"], "reason": g["reason"]}
                for g in gates if g["status"] == "warn"]
    unknowns = [{"gate": g["gate"], "reason": g["reason"]}
                for g in gates if g["status"] == "unknown"]
    review_reasons = [g["reason"] for g in warnings + unknowns]
    confidence_reservations = []
    for criterion in jev_result.get("criteria") or []:
        if criterion.get("required") and criterion.get("id") in (jev_result.get("low_confidence_criteria") or []):
            note = f"faible confiance Jev : {criterion['id']}"
            junior_fact = (facts or {}).get("junior", {})
            minimum = (facts or {}).get("experience_min", {})
            supported_junior = (criterion.get("id") == "junior_fit"
                                and junior_fact.get("status") == "known"
                                and junior_fact.get("value") is True
                                and (minimum.get("status") != "known" or minimum.get("value", 99) < 2)
                                and criterion.get("evidence"))
            if supported_junior and approved:
                confidence_reservations.append(note)
            else:
                review_reasons.append(note)
        if approved and criterion.get("required") and criterion.get("passed") and not criterion.get("evidence"):
            review_reasons.append(f"preuve Jev absente : {criterion['id']}")
    for name, fact in (facts or {}).items():
        if fact.get("status") == "contradictory":
            review_reasons.append(f"fait contradictoire : {name}")
    if approved and hard_failed:
        status = "jev_excluded"
    elif hard_failed:
        status = "rejected"
    elif review_reasons:
        status = "review_required"
    elif approved:
        status = "qualified"
    else:
        status = "rejected"
    return {
        "status": status,
        "review_required": status == "review_required",
        "review_reasons": list(dict.fromkeys(review_reasons)) if status == "review_required" else [],
        "confidence_reservations": confidence_reservations,
        "hard_gate_failures": [{"gate": g["gate"], "reason": g["reason"]} for g in hard_failed],
        "warnings": warnings,
        "unknowns": unknowns,
    }