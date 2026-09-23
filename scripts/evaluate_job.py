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


OPENROUTER_URL = "https://openrouter.ai/api/alpha/decisions"
MODEL = "typesafe/jev-1.13"
MAX_RETRIES = 3
RETRYABLE_STATUSES = (429, 500, 502, 503, 504)
DEFAULT_MIN_GLOBAL_SCORE = 68
DEFAULT_MIN_CONFIDENCE = 0.5


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def die(msg):
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


def validate_response(response, criteria_ids):
    """Validate the Jev API response structure."""
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


# ---------------------------------------------------------------------------
# API call with retries (transient errors only)
# ---------------------------------------------------------------------------

def call_jev(job_text, criteria, endpoint=None, model=None, api_key=None,
             timeout=120, max_retries=MAX_RETRIES):
    api_key = api_key or os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY is missing")

    questions = {}
    for criterion in criteria:
        cid = criterion["id"]
        questions[cid] = {
            "type": "score",
            "instructions": (
                f"Evaluate how well this job offer satisfies this criterion: "
                f"{criterion['description']}. "
                f"Use only evidence explicitly contained in the job offer. "
                f"Do not assume that missing information satisfies the criterion."
            ),
            "criteria": [
                f"The offer clearly conflicts with: {criterion['description']}",
                f"The offer mostly fails to satisfy: {criterion['description']}",
                f"The offer partially satisfies: {criterion['description']}",
                f"The offer mostly satisfies: {criterion['description']}",
                f"The offer clearly and strongly satisfies: {criterion['description']}",
            ]
        }

    payload = {
        "model": model or MODEL,
        "state": {
            "document_type": "job_offer",
            "job_offer": job_text
        },
        "questions": questions
    }

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
            if e.code in RETRYABLE_STATUSES and attempt < max_retries:
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

    # --- 2. Call Jev ---
    response = call_jev(
        job_text, criteria,
        endpoint=data.get("api_endpoint"),
        model=data.get("model"),
        api_key=data.get("api_key"),
        timeout=float(data.get("timeout_seconds") or 120),
        max_retries=int(data.get("max_retries") or MAX_RETRIES),
    )
    validate_response(response, criteria_ids)

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
        })

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
        "jev_model": response.get("model"),
        "usage": response.get("usage"),
    }

    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()