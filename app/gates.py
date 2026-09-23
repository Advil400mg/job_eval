"""Hard gates applied before/next to the Jev score.

Mirrors the rules of PROFILE.json (hard_rejection_rules, freshness,
experience_filter). A gate never rewrites a Jev score: it only restricts
whether an offer can be qualified.
"""

from __future__ import annotations

import re
from datetime import date, datetime

STUDENT_RE = re.compile(
    r"\b(stage|stagiaire|internship|alternance|apprentissage|apprenti|"
    r"contrat de professionnalisation|statut étudiant|etudiant|Praktikum)\b",
    re.I,
)

SENIOR_ONLY_RE = re.compile(
    r"\b(expérience (?:professionnelle )?(?:confirmée|démontrée|significative)|"
    r"senior|expert confirmé|minimum \d+ ans|au moins \d+ ans)\b",
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


def _years_requirement(text: str) -> tuple[int | None, int | None, str | None]:
    """Lowest stated experience requirement.

    Returns (low, high, wording): high is filled when the announcement states a
    range ("1 à 3 ans", "0-2 ans").
    """
    range_patterns = [
        r"(\d{1,2})\s*(?:\+|ans?)?\s*(?:à|-|to)\s*(\d{1,2})\s*ans",
        r"(\d{1,2})\s*(?:à|-|to)\s*(\d{1,2})\s*years?",
    ]
    single_patterns = [
        r"minimum (?:de )?(\d{1,2})\s*ans?",
        r"au moins (\d{1,2})\s*ans?",
        r"(\d{1,2})\s*\+\s*(?:ans?|years?)",
        r"(\d{1,2})\s*years?(?:\+)? (?:of )?experience",
        r"expérience (?:professionnelle )?(?:minimale|requise|exigée|souhaitée)\s*:?\s*(\d{1,2})\s*ans?",
    ]
    candidates: list[tuple[int, int | None, str]] = []
    for pattern in range_patterns:
        for match in re.finditer(pattern, text, re.I):
            low, high = int(match.group(1)), int(match.group(2))
            if low > 20 or high > 20 or high < low:
                continue
            candidates.append((low, high, match.group(0).strip()))
    for pattern in single_patterns:
        for match in re.finditer(pattern, text, re.I):
            try:
                low = int(match.group(1))
            except (IndexError, ValueError):
                continue
            if low > 20:
                continue
            candidates.append((low, None, match.group(0).strip()))
    if not candidates:
        return None, None, None
    low, high, wording = min(candidates, key=lambda c: c[0])
    return low, high, wording


def contract_gate(text: str) -> dict:
    offer = text[:8000]
    if STUDENT_RE.search(offer):
        hit = STUDENT_RE.search(offer)
        return {"gate": "contract_type", "status": "fail", "hard": True,
                "reason": f"statut étudiant / stage / alternance détecté (« {hit.group(0)} »)"}
    student_body = STUDENT_RE.search(text)
    if student_body and not re.search(r"\b(stage|alternance)\b.{0,40}(exclu|pas|aucun)", text, re.I):
        return {"gate": "contract_type", "status": "warn", "hard": False,
                "reason": f"mention de « {student_body.group(0)} » dans le corps du texte "
                          f"— à vérifier manuellement"}
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


def experience_gate(text: str, reject_at_years: int = 2,
                    allowed_max_range: int = 2) -> dict:
    """Apply the profile's experience_filter (reject at >= 2 years; a range that
    reaches beyond 2 years needs an explicit junior/entry-level mention)."""
    low, high, wording = _years_requirement(text)
    explicit_unstated = bool(re.search(
        r"expérience (?:souhaitée|requise)\s*:?\s*(?:non renseigné|non renseignée)",
        text, re.I))
    junior = JUNIOR_HINT_RE.search(text)
    if low is None:
        if not junior and explicit_unstated:
            return {"gate": "experience", "status": "pass", "hard": True,
                    "reason": "expérience requise « non renseignée » sur la fiche"}
        if junior:
            return {"gate": "experience", "status": "pass", "hard": True,
                    "reason": f"aucun minimum en années ; mention junior explicite "
                              f"(« {junior.group(0)} »)"}
        return {"gate": "experience", "status": "unknown", "hard": False,
                "reason": "aucun minimum d'expérience écrit en années, "
                          "aucune mention junior — non prouvable"}
    if low >= reject_at_years and not junior:
        return {"gate": "experience", "status": "fail", "hard": True,
                "reason": f"minimum exigé ≥ {reject_at_years} ans (« {wording} »)"}
    if high is not None and high > allowed_max_range and not junior:
        return {"gate": "experience", "status": "fail", "hard": True,
                "reason": f"fourchette {low}-{high} ans sans mention junior/entry-level "
                          f"(« {wording} »)"}
    if low >= 1 and junior and SENIOR_ONLY_RE.search(text):
        return {"gate": "experience", "status": "warn", "hard": False,
                "reason": f"« {wording} » mais corps d'annonce au registre senior"}
    return {"gate": "experience", "status": "pass", "hard": True,
            "reason": f"exigence compatible (« {wording} »)"
                      + (f" + mention junior (« {junior.group(0)} »)" if junior else "")}


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


def run_gates(offer: dict, profile: dict) -> list[dict]:
    search = profile.get("search", {})
    exp_filter = search.get("experience_filter", {})
    reject_at = exp_filter.get("reject_if_minimum_required_years_gte", 2)
    max_age = search.get("max_age_days", 30)
    text = offer.get("job_text", "")
    return [
        contract_gate(text),
        experience_gate(text, reject_at),
        freshness_gate(offer.get("published_at"), max_age),
        availability_gate(text),
    ]


def decide(jev_result: dict, gates: list[dict]) -> dict:
    """Final status: qualified / jev_excluded / rejected (+ reasons)."""
    hard_failed = [g for g in gates if g["status"] == "fail" and g.get("hard")]
    approved = bool(jev_result.get("jev_approved"))
    if approved and not hard_failed:
        status = "qualified"
    elif approved and hard_failed:
        status = "jev_excluded"
    else:
        status = "rejected"
    return {
        "status": status,
        "hard_gate_failures": [{"gate": g["gate"], "reason": g["reason"]} for g in hard_failed],
        "warnings": [{"gate": g["gate"], "reason": g["reason"]}
                     for g in gates if g["status"] == "warn"],
        "unknowns": [{"gate": g["gate"], "reason": g["reason"]}
                     for g in gates if g["status"] == "unknown"],
    }