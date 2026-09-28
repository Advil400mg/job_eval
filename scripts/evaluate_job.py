#!/usr/bin/env python3
"""
Evaluate a single job offer against profile criteria using TypeSafe Jev (typesafe/jev-1.13)
via OpenRouter.  Never simulates — always calls the real API.

Input: a single JSON object with fields:
  url, title, company, job_text, criteria (list of objects each with id/name/description)
  location (optional, passed through)
  published_at (optional, passed through)
  minimum_global_score (optional, default from PROFILE fallback or explicit)
  minimum_confidence  (optional, default from PROFILE fallback or explicit)

Output: JSON to stdout with scores, jev_approved, low_confidence_criteria, etc.
On error: exits non-zero, no fabricated JSON.
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request
import re
from typing import NoReturn


OPENROUTER_URL = "https://openrouter.ai/api/alpha/decisions"
MODEL = "typesafe/jev-1.13"
MAX_RETRIES = 3
DEFAULT_MIN_GLOBAL_SCORE = 68
DEFAULT_MIN_CONFIDENCE = 0.5
MAX_QUESTIONS_PER_CALL = 12
STANDARD_DIMENSIONS = (
    ("technical", "Adéquation technique", "Technical cybersecurity or network engineering work, not generic IT support, governance or awareness."),
    ("junior", "Accessibilité junior", "Actual responsibilities and mandatory requirements are accessible to a graduate with less than one year of employment; a junior title alone is insufficient."),
    ("growth", "Progression professionnelle", "Named mentoring, training, varied hands-on work or a credible technical growth path, not only a vague promise."),
    ("clarity", "Clarté et fiabilité", "The first assignment, team, contract, location and work constraints are explicitly stated; important missing facts reduce this score."),
)

# ---------------------------------------------------------------------------
# Profile context schema & sanitisation
# ---------------------------------------------------------------------------

PROFILE_CONTEXT_FIELDS = frozenset({
    "target_roles", "seniority", "candidate_years",
    "accepted_locations", "preferred_locations",
    "languages", "contract_types",
})
ALLOWED_SENIORITY = frozenset({"junior", "intermediate", "senior", "any"})


def _sanitize_profile_string(value):
    """Reject control chars, injection patterns, and excessive length."""
    if not isinstance(value, str):
        return value
    if re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", value):
        die("ERROR: profile_context string contains control characters.")
    if len(value) > 500:
        die("ERROR: profile_context string exceeds max length (500).")
    injection = re.compile(
        r"(?:ignore\s+(?:all\s+)?(?:previous|above)"
        r"|forget\s+(?:all\s+)?(?:previous|above)"
        r"|you\s+are\s+(?:now\s+)?an?\s+\w+\s+(?:AI|assistant|model|agent)"
        r"|new\s+instructions?\s*[:=]"
        r"|rewrite\s+(?:the\s+)?(?:prompt|system)"
        r"|override\s+(?:all\s+)?(?:instructions?|rules?|system|prompts?)"
        r")",
        re.IGNORECASE,
    )
    if injection.search(value):
        die("ERROR: profile_context string contains disallowed pattern.")
    return value.strip()


def _sanitize_profile_list(items):
    """Sanitise each element of a string list."""
    return [_sanitize_profile_string(v) for v in items]


def validate_profile_context(ctx):
    """Validate profile_context payload; die on the first defect."""
    if not isinstance(ctx, dict):
        die("ERROR: profile_context must be a JSON object.")
    for key in ctx:
        if key not in PROFILE_CONTEXT_FIELDS:
            die(f"ERROR: profile_context contains unknown field '{key}'.")

    if "target_roles" in ctx:
        tr = ctx["target_roles"]
        if not isinstance(tr, list) or not all(
            isinstance(v, str) and v.strip() for v in tr
        ):
            die("ERROR: profile_context.target_roles must be a list of non-empty strings.")
        ctx["target_roles"] = _sanitize_profile_list(tr)

    if "seniority" in ctx:
        s = ctx["seniority"]
        if not isinstance(s, str) or s not in ALLOWED_SENIORITY:
            die("ERROR: profile_context.seniority must be one of: junior, intermediate, senior, any.")

    if "candidate_years" in ctx:
        cy = ctx["candidate_years"]
        if cy is not None:
            if isinstance(cy, bool) or not isinstance(cy, (int, float)):
                die("ERROR: profile_context.candidate_years must be a number or null.")
            if cy < 0 or cy > 100:
                die("ERROR: profile_context.candidate_years out of range (0-100).")

    if "accepted_locations" in ctx:
        al = ctx["accepted_locations"]
        if not isinstance(al, list) or not all(
            isinstance(v, str) and v.strip() for v in al
        ):
            die("ERROR: profile_context.accepted_locations must be a list of non-empty strings.")
        ctx["accepted_locations"] = _sanitize_profile_list(al)

    if "preferred_locations" in ctx:
        pl = ctx["preferred_locations"]
        if not isinstance(pl, list) or not all(
            isinstance(v, str) and v.strip() for v in pl
        ):
            die("ERROR: profile_context.preferred_locations must be a list of non-empty strings.")
        ctx["preferred_locations"] = _sanitize_profile_list(pl)

    if "languages" in ctx:
        lang = ctx["languages"]
        if not isinstance(lang, str):
            die("ERROR: profile_context.languages must be a string.")
        ctx["languages"] = _sanitize_profile_string(lang)

    if "contract_types" in ctx:
        ct = ctx["contract_types"]
        if not isinstance(ct, list) or not all(
            isinstance(v, str) and v.strip() for v in ct
        ):
            die("ERROR: profile_context.contract_types must be a list of non-empty strings.")
        ctx["contract_types"] = _sanitize_profile_list(ct)

    return ctx


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def die(msg) -> NoReturn:
    """Print error to stderr and exit non-zero."""
    print(msg, file=sys.stderr)
    sys.exit(1)


def _number_in_range(value, low, high, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        die(f"ERROR: {label} must be numeric.")
    if not low <= float(value) <= high:
        die(f"ERROR: {label} must be between {low} and {high}.")


def validate_input(data):
    """Validate one complete job object; die on the first defect."""

    if isinstance(data, list):
        die("ERROR: Input is a JSON array — expected a single JSON object.")
    if not isinstance(data, dict):
        die("ERROR: Input is not a JSON object.")

    for key in ("url", "title", "company", "job_text"):
        if key not in data:
            die(f"ERROR: Missing required input field '{key}'.")
        if not isinstance(data[key], str) or not data[key].strip():
            die(f"ERROR: Input field '{key}' must be a non-empty string.")
    if "criteria" not in data:
        die("ERROR: Missing required input field 'criteria'.")
    if not data["url"].lower().startswith(("http://", "https://")):
        die("ERROR: Input field 'url' must be an HTTP(S) URL.")
    criteria = data["criteria"]
    if not isinstance(criteria, list) or not criteria:
        die("ERROR: 'criteria' must be a non-empty list.")

    seen_ids = set()
    for i, c in enumerate(criteria):
        if not isinstance(c, dict):
            die(f"ERROR: criteria[{i}] is not an object.")
        for k in ("id", "name", "description"):
            if k not in c:
                die(f"ERROR: criteria[{i}] missing required field '{k}'.")
            if not isinstance(c[k], str) or not c[k].strip():
                die(f"ERROR: criteria[{i}].{k} must be a non-empty string.")
        if c["id"] in seen_ids:
            die(f"ERROR: duplicate criterion id '{c['id']}'.")
        seen_ids.add(c["id"])
        weight = c.get("weight", 1)
        if isinstance(weight, bool) or not isinstance(weight, (int, float)) or weight <= 0:
            die(f"ERROR: criteria[{i}].weight must be a positive number.")
        if "required" in c and not isinstance(c["required"], bool):
            die(f"ERROR: criteria[{i}].required must be boolean.")
        if c.get("required"):
            _number_in_range(c.get("min_score", 0), 0, 100,
                             f"criteria[{i}].min_score")

    _number_in_range(data.get("minimum_global_score", DEFAULT_MIN_GLOBAL_SCORE),
                     0, 100, "minimum_global_score")
    _number_in_range(data.get("minimum_confidence", DEFAULT_MIN_CONFIDENCE),
                     0, 1, "minimum_confidence")
    context = data.get("offer_context")
    if context is not None:
        if not isinstance(context, dict):
            die("ERROR: offer_context must be an object.")
        for name, item in context.items():
            if name not in {"title", "location", "contract", "experience_min",
                            "experience_preferred", "junior"} or not isinstance(item, dict):
                die(f"ERROR: invalid offer_context field '{name}'.")
            evidence = item.get("evidence")
            if not isinstance(evidence, str) or evidence not in data["job_text"]:
                die(f"ERROR: unverified offer_context evidence for '{name}'.")

    if "profile_context" in data:
        validate_profile_context(data["profile_context"])


def validate_response(response, criteria_ids, proof_questions=None):
    """Validate all scored answers and every requested evidence choice."""
    if not isinstance(response, dict):
        die("ERROR: Jev API returned a non-object response.")

    if "answers" not in response:
        die("ERROR: Jev API response missing 'answers'.")

    answers = response["answers"]
    if not isinstance(answers, dict):
        die("ERROR: Jev API 'answers' is not an object.")

    for cid in criteria_ids:
        if cid not in answers:
            die(f"ERROR: Jev API response missing answer for criterion '{cid}'.")
        answer = answers[cid]
        if not isinstance(answer, dict):
            die(f"ERROR: Jev API answer for '{cid}' is not an object.")
        if "score" not in answer:
            die(f"ERROR: Jev API answer for '{cid}' missing 'score'.")
        if "confidence" not in answer:
            die(f"ERROR: Jev API answer for '{cid}' missing 'confidence'.")
        _number_in_range(answer["score"], 0, 4,
                         f"Jev API answer for '{cid}'.score")
        _number_in_range(answer["confidence"], 0, 1,
                         f"Jev API answer for '{cid}'.confidence")
    for cid, (question_id, options) in (proof_questions or {}).items():
        answer = answers.get(question_id)
        if not isinstance(answer, dict):
            die(f"ERROR: Jev API returned invalid evidence choice for '{cid}'.")
            continue
        if answer.get("choice") not in options:
            die(f"ERROR: Jev API returned invalid evidence choice for '{cid}'.")
        _number_in_range(answer.get("confidence"), 0, 1,
                         f"Jev API evidence confidence for '{cid}'")


def evidence_sentences(job_text, maximum=80):
    """Bound candidates; every excerpt remains an exact source substring."""
    import re
    chunks = re.split(r"(?<=[.!?])\s+|\n+", job_text)
    return {f"s{index}": chunk.strip()[:350] for index, chunk in enumerate(chunks)
            if len(chunk.strip()) >= 18 and index < maximum}


def build_questions(criteria, sentences, profile_context=None):
    """Score configured criteria, plus a typed source-passage selection."""
    import re
    questions = {}
    proofs = {}
    ids = {criterion["id"] for criterion in criteria}
    for criterion in criteria:
        cid = criterion["id"]
        description = criterion["description"]
        instructions = (
            "A preferred qualification is not mandatory; a mandatory minimum is "
            "not cancelled by a job title. Use only explicit evidence; "
            "missing information is unknown, not a positive match."
        ) if profile_context else (
            "A preferred qualification is not mandatory; a mandatory minimum is "
            "not cancelled by a junior title. Distinguish hands-on duties from "
            "governance or unspecified staffing. Use only explicit evidence; "
            "missing information is unknown, not a positive match."
        )
        questions[cid] = {
            "type": "score",
            "instructions": f"Evaluate how well this job offer satisfies this criterion: {description}. "
                            + instructions,
            "criteria": [
                f"The offer clearly conflicts with: {description}",
                f"The offer mostly fails to satisfy: {description}",
                f"The offer partially satisfies: {description}",
                f"The offer mostly satisfies: {description}",
                f"The offer clearly and strongly satisfies: {description}",
            ],
        }
        if not sentences:
            continue
        terms = set(re.findall(r"[\wÀ-ÿ]{4,}", description.lower()))
        ranked = sorted(sentences.items(), key=lambda item: (
            -len(terms & set(re.findall(r"[\wÀ-ÿ]{4,}", item[1].lower()))),
            int(item[0][1:]),
        ))[:12]
        options = {sid: text for sid, text in ranked}
        proof_id = f"proof_{cid}"
        while proof_id in ids or proof_id in questions:
            proof_id = "_" + proof_id
        questions[proof_id] = {
            "type": "choice",
            "instructions": ("Which exact offered passage best supports this criterion: "
                             f"{description}? Select none if no passage proves it."),
            "criteria": {**options, "none": "No offered passage supports this criterion"},
        }
        proofs[cid] = (proof_id, {**options, "none": None})
    return questions, proofs


def _parameterize_dimension(key, base_description, context):
    """Generate profile-aware dimension descriptions; context already sanitised."""
    if key == "technical":
        roles = context.get("target_roles") or []
        role_str = ", ".join(r.strip() for r in roles[:3] if r.strip())
        return ("Does the actual work match the targeted occupation(s): "
                f"{role_str or 'not specified'}? Do not privilege technical over "
                "non-technical roles, or infer fit from the title alone.")

    if key == "junior":
        seniority = context.get("seniority") or "any"
        candidate_years = context.get("candidate_years")
        years = (f"The candidate reports {candidate_years:g} years of professional experience. "
                 if candidate_years is not None else
                 "The candidate has not declared years of professional experience. ")
        return (years + f"Compare actual responsibilities and mandatory requirements with "
                f"the candidate's target seniority ({seniority}); do not assume a junior "
                "candidate or an entry-level opening. An unknown requirement is not a match.")

    if key == "growth":
        return ("Credible professional development aligned with the candidate's career stage: "
                "specific responsibilities, progression or mentoring where appropriate, "
                "not only vague promises.")

    return base_description


def dimension_criteria(profile_criteria, profile_context=None):
    """Keep standard assessments beside, not inside, the configured global score.

    When profile_context is provided, descriptions for 'technical' and 'junior'
    dimensions are parameterized based on target_roles, seniority, etc.
    """
    reserved = {criterion["id"] for criterion in profile_criteria}
    dimensions = []
    for key, name, description in STANDARD_DIMENSIONS:
        if profile_context:
            description = _parameterize_dimension(key, description, profile_context)
            name = {"technical": "Adéquation au métier",
                    "junior": "Adéquation du niveau"}.get(key, name)
        question_id = f"dim_{key}"
        while question_id in reserved:
            question_id = "_" + question_id
        reserved.add(question_id)
        dimensions.append({"id": question_id, "key": key, "name": name,
                           "description": description})
    return dimensions


def merge_jev_batches(batches):
    """Never expose a partial result if a required batch fails validation."""
    combined = {"answers": {}, "model": None, "usage": {"cost": 0}}
    for result, question_ids in batches:
        if not isinstance(result, dict) or not isinstance(result.get("answers"), dict):
            die("ERROR: Jev API returned invalid batch response.")
        if any(qid not in result["answers"] for qid in question_ids):
            die("ERROR: Jev API response missing an answer in a required batch.")
        combined["answers"].update(result["answers"])
        combined["model"] = result.get("model") or combined["model"]
        cost = (result.get("usage") or {}).get("cost")
        if isinstance(cost, (int, float)):
            combined["usage"]["cost"] += cost
    return combined


# ---------------------------------------------------------------------------
# API call with retries (transient errors only)
# ---------------------------------------------------------------------------

def call_jev(job_text, criteria, endpoint=None, model=None, api_key=None,
             timeout=120.0, max_retries=MAX_RETRIES, questions=None, offer_context=None):
    api_key = api_key or os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY is missing")

    if questions is None:
        questions, _ = build_questions(criteria, {})
    state = {"document_type": "job_offer", "job_offer": job_text}
    if offer_context:
        state["verified_context"] = offer_context
    payload = {"model": model or MODEL, "state": state, "questions": questions}

    body = json.dumps(payload).encode("utf-8")
    url = endpoint or OPENROUTER_URL

    last_exc = None
    for attempt in range(1, max_retries + 1):
        try:
            request = urllib.request.Request(
                url,
                data=body,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json"
                },
                method="POST"
            )
            with urllib.request.urlopen(request, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if (e.code == 429 or 500 <= e.code < 600) and attempt < max_retries:
                time.sleep(2 ** attempt)
                last_exc = e
                continue
            raise RuntimeError(
                f"Jev API HTTP {e.code}: {e.reason}"
            ) from e
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            if attempt < max_retries:
                time.sleep(2 ** attempt)
                last_exc = e
                continue
            raise RuntimeError(
                f"Jev API connection failed after {max_retries} attempts: {e}"
            ) from last_exc

    raise RuntimeError(
        f"Jev API call failed after {max_retries} retries"
    )


# ---------------------------------------------------------------------------
# Score helpers
# ---------------------------------------------------------------------------

def normalize_score(score):
    """Jev returns 0–4; map to 0–100."""
    return round((float(score) / 4.0) * 100, 1)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    if len(sys.argv) != 2:
        die("Usage: evaluate_job.py input.json")

    # --- 1. Read input ---
    try:
        with open(sys.argv[1], encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        die(f"ERROR: Cannot read input file: {e}")

    validate_input(data)

    job_text = data["job_text"]
    criteria = data["criteria"]
    criteria_ids = [c["id"] for c in criteria]
    dimensions = dimension_criteria(criteria, data.get("profile_context"))
    all_criteria = criteria + dimensions
    questions, proof_questions = build_questions(
        all_criteria, evidence_sentences(job_text), data.get("profile_context"))

    # --- 2. Call Jev in bounded batches; a partial assessment is never emitted ---
    items = list(questions.items())
    batches = []
    for start in range(0, len(items), MAX_QUESTIONS_PER_CALL):
        batch = dict(items[start:start + MAX_QUESTIONS_PER_CALL])
        answer = call_jev(
            job_text, criteria,
            endpoint=data.get("api_endpoint"),
            model=data.get("model"),
            api_key=data.get("api_key"),
            timeout=float(data.get("timeout_seconds") or 120),
            max_retries=int(data.get("max_retries") or MAX_RETRIES),
            questions=batch,
            offer_context=data.get("offer_context"),
        )
        batches.append((answer, list(batch)))
    response = merge_jev_batches(batches)
    validate_response(response, criteria_ids + [d["id"] for d in dimensions], proof_questions)

    # --- 3. Compute scores ---
    results = []
    weighted_total = 0.0
    total_weight = 0.0
    blockers = []
    low_confidence_criteria = []

    for criterion in criteria:
        cid = criterion["id"]
        answer = response["answers"][cid]

        score = normalize_score(answer["score"])
        confidence = answer.get("confidence")

        weight = float(criterion.get("weight", 1))

        weighted_total += score * weight
        total_weight += weight

        required = bool(criterion.get("required", False))
        min_score = float(criterion.get("min_score", 0))
        passed = not required or score >= min_score

        if not passed:
            blockers.append(cid)

        proof_id, choices = proof_questions.get(cid, (None, {}))
        selected = response["answers"][proof_id] if proof_id else {}
        sentence_id = selected.get("choice")
        evidence = ({"sentence_id": sentence_id, "quote": choices[sentence_id],
                     "confidence": selected["confidence"]}
                    if sentence_id and sentence_id != "none" else None)
        results.append({
            "id": cid,
            "name": criterion.get("name", cid),
            "score": score,
            "weight": weight,
            "required": required,
            "min_score": min_score if required else None,
            "passed": passed,
            "confidence": confidence,
            "probabilities": answer.get("probabilities"),
            "evidence": evidence,
        })

    dimension_results = []
    for dimension in dimensions:
        did = dimension["id"]
        answer = response["answers"][did]
        proof_id, options = proof_questions.get(did, (None, {}))
        selected = response["answers"][proof_id] if proof_id else {}
        sid = selected.get("choice")
        proof = ({"sentence_id": sid, "quote": options[sid],
                  "confidence": selected["confidence"]}
                 if sid and sid != "none" else None)
        dimension_results.append({"id": dimension["key"], "name": dimension["name"],
                                  "score": normalize_score(answer["score"]),
                                  "confidence": answer["confidence"], "evidence": proof})

    global_score = (
        weighted_total / total_weight
        if total_weight
        else 0.0
    )

    required_criteria_passed = len(blockers) == 0

    # --- 4. Thresholds from input or defaults ---
    minimum_global_score = data.get(
        "minimum_global_score",
        DEFAULT_MIN_GLOBAL_SCORE
    )
    minimum_confidence = data.get(
        "minimum_confidence",
        DEFAULT_MIN_CONFIDENCE
    )

    jev_approved = required_criteria_passed and (
        global_score >= minimum_global_score
    )

    # Identify low-confidence criteria
    for r in results:
        conf = r.get("confidence")
        if conf is not None and conf < minimum_confidence:
            low_confidence_criteria.append(r["id"])

    # --- 5. Build output ---
    output = {
        "url": data.get("url"),
        "title": data.get("title"),
        "company": data.get("company"),
        "location": data.get("location"),
        "published_at": data.get("published_at"),
        "global_score": round(global_score, 1),
        "minimum_global_score": minimum_global_score,
        "minimum_confidence": minimum_confidence,
        "required_criteria_passed": required_criteria_passed,
        "blocking_criteria": blockers,
        "jev_approved": jev_approved,
        "low_confidence_criteria": low_confidence_criteria,
        "criteria": results,
        "dimensions": dimension_results,
        "evaluation_schema_version": 2,
        "jev_model": response.get("model"),
        "usage": response.get("usage"),
    }

    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()