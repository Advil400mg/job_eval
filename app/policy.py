"""Effective evaluation policy for a user profile (legacy profiles are unchanged)."""

from __future__ import annotations


CONTRACT_TYPES = frozenset({"permanent", "fixed_term", "freelance", "internship"})
SENIORITY = frozenset({"any", "junior", "intermediate", "senior"})


def structured(profile: dict) -> bool:
    return profile.get("search", {}).get("policy_version") == 2


def candidate_facts(profile: dict) -> dict:
    """User-confirmed facts override CV extraction for evaluation, never for CV writing."""
    return profile.get("candidate_facts") or profile.get("candidate") or {}


def context(profile: dict) -> dict | None:
    """Only opted-in profiles get generic prompts; existing saved profiles retain theirs."""
    if not structured(profile):
        return None
    search = profile["search"]
    facts = candidate_facts(profile)
    experience = search["experience_filter"]
    return {
        "target_roles": search["target_roles"],
        "seniority": search["seniority"],
        "candidate_years": experience.get("candidate_years"),
        "accepted_locations": search["locations"],
        "preferred_locations": search.get("preferred_locations", []),
        "contract_types": search.get("contract_types", []),
        "languages": facts.get("languages_line", ""),
    }


def effective_criteria(profile: dict) -> list[dict]:
    """Give Jev the current structured settings, without modifying stored descriptions.

    Existing profiles keep their historical descriptions until the owner explicitly
    adopts the structured policy. Free-text descriptions are preserved in the editor.
    """
    if not structured(profile):
        return profile["criteria"]
    search = profile["search"]
    facts = candidate_facts(profile)
    experience = search["experience_filter"]
    injected = {
        "experience_fit": (f"Expérience déclarée : {experience.get('candidate_years')} années. "
                           if experience.get("candidate_years") is not None else
                           "Années d'expérience non déclarées : ne pas supposer le niveau. "),
        "role_fit": "Postes visés : " + ", ".join(search["target_roles"]) + ". ",
        "skills_match": "Compétences déclarées : " + (", ".join(facts.get("skills") or []) or
                                                  "non renseignées") + ". ",
        "location_fit": ("Lieux acceptés : " + (", ".join(search["locations"]) or "sans restriction")
                         + ". Lieux préférés : "
                         + (", ".join(search.get("preferred_locations") or []) or "aucun") + ". "),
        "language_fit": "Langues déclarées : " + (facts.get("languages_line") or "non renseignées") + ". ",
    }
    result = []
    for criterion in profile["criteria"]:
        item = criterion.copy()
        if item["id"] in injected:
            item["description"] = injected[item["id"]] + item["description"]
        result.append(item)
    return result
