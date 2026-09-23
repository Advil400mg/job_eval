"""Aggregations for the dashboard: global stats, per-criterion and per-gate views.

Pure functions over already-computed results — no scoring is recomputed here.
"""

from __future__ import annotations

SCORE_BUCKETS = [(0, 40), (40, 55), (55, 68), (68, 80), (80, 101)]


def _score(item: dict):
    return (item.get("jev") or {}).get("global_score")


def _status(item: dict) -> str:
    decision = item.get("decision") or {}
    if decision.get("status"):
        return decision["status"]
    if item.get("status") == "ok":
        return "rejected"
    return item.get("status") or "unknown"


def _average(values: list[float]):
    clean = [v for v in values if isinstance(v, (int, float))]
    return round(sum(clean) / len(clean), 1) if clean else None


def summarize(results: list[dict]) -> dict:
    """Global dashboard payload."""
    scores = [s for s in map(_score, results) if isinstance(s, (int, float))]
    statuses: dict[str, int] = {}
    for item in results:
        statuses[_status(item)] = statuses.get(_status(item), 0) + 1

    cost = 0.0
    tokens_in = 0
    for item in results:
        usage = (item.get("jev") or {}).get("usage") or {}
        cost += usage.get("cost") or 0
        tokens_in += usage.get("input_tokens") or 0

    distribution = []
    for low, high in SCORE_BUCKETS:
        label = f"{low}-{high - 1}" if high <= 100 else f"{low}+"
        distribution.append({"bucket": label,
                             "count": sum(1 for s in scores if low <= s < high)})
    if not distribution:
        distribution = [{"bucket": "aucune", "count": 0}]

    criteria_order: list[str] = []
    criteria: dict[str, dict] = {}
    for item in results:
        for crit in (item.get("jev") or {}).get("criteria") or []:
            cid = crit["id"]
            if cid not in criteria:
                criteria_order.append(cid)
                criteria[cid] = {
                    "id": cid, "name": crit.get("name", cid),
                    "weight": crit.get("weight"), "required": crit.get("required"),
                    "min_score": crit.get("min_score"),
                    "scores": [], "confidences": [],
                    "blocking": 0, "low_confidence": 0, "below_required": 0,
                }
            entry = criteria[cid]
            if isinstance(crit.get("score"), (int, float)):
                entry["scores"].append(crit["score"])
            if isinstance(crit.get("confidence"), (int, float)):
                entry["confidences"].append(crit["confidence"])
            if crit.get("required") and not crit.get("passed"):
                entry["blocking"] += 1
                entry["below_required"] += 1
    min_conf_default = 0.5
    for item in results:
        for cid in (item.get("jev") or {}).get("low_confidence_criteria") or []:
            if cid in criteria:
                criteria[cid]["low_confidence"] += 1

    criteria_rows = []
    for cid in criteria_order:
        entry = criteria[cid]
        count = len(entry["scores"])
        criteria_rows.append({
            "id": cid, "name": entry["name"], "weight": entry["weight"],
            "required": entry["required"], "min_score": entry["min_score"],
            "evaluated": count,
            "avg_score": _average(entry["scores"]),
            "avg_confidence": _average(entry["confidences"]),
            "blocking": entry["blocking"],
            "low_confidence": entry["low_confidence"],
            "blocking_share": round(100 * entry["blocking"] / count, 1) if count else None,
        })
    criteria_rows.sort(key=lambda r: (r["blocking"] or 0, r["avg_score"] or 0), reverse=True)

    gates: dict[str, dict] = {}
    for item in results:
        for gate in item.get("gate_results") or []:
            name = gate["gate"]
            entry = gates.setdefault(name, {"gate": name, "pass": 0, "fail": 0,
                                            "warn": 0, "unknown": 0, "reasons": {}})
            entry[gate["status"]] = entry.get(gate["status"], 0) + 1
            if gate["status"] in ("fail", "warn"):
                entry["reasons"][gate["reason"]] = entry["reasons"].get(gate["reason"], 0) + 1

    ranked = sorted([r for r in results if isinstance(_score(r), (int, float))],
                    key=lambda r: _score(r), reverse=True)
    top = [{
        "title": r.get("title"), "company": r.get("company"), "url": r.get("url"),
        "score": _score(r), "status": _status(r), "location": r.get("location"),
        "published_at": r.get("published_at"),
        "blocking_criteria": (r.get("jev") or {}).get("blocking_criteria") or [],
    } for r in ranked[:5]]

    return {
        "offers": len(results),
        "scored": len(scores),
        "errors": statuses.get("error", 0) + statuses.get("unverified", 0),
        "qualified": statuses.get("qualified", 0),
        "rejected": statuses.get("rejected", 0),
        "jev_excluded": statuses.get("jev_excluded", 0),
        "statuses": statuses,
        "avg_score": _average(scores),
        "best_score": round(max(scores), 1) if scores else None,
        "worst_score": round(min(scores), 1) if scores else None,
        "distribution": distribution,
        "criteria": criteria_rows,
        "gates": sorted(gates.values(), key=lambda g: (-g["fail"], g["gate"])),
        "top_offers": top,
        "jev_cost": round(cost, 6),
        "jev_input_tokens": tokens_in,
    }


def run_summary(run: dict) -> dict:
    """Compact line for the history table."""
    summary = summarize(run.get("results") or [])
    return {
        "id": run.get("id"),
        "created_at": run.get("created_at"),
        "status": run.get("status"),
        "progress": run.get("progress"),
        "total": run.get("total"),
        "offers": summary["offers"],
        "avg_score": summary["avg_score"],
        "best_score": summary["best_score"],
        "qualified": summary["qualified"],
        "rejected": summary["rejected"],
        "jev_excluded": summary["jev_excluded"],
        "errors": summary["errors"],
        "top": summary["top_offers"][:3],
        "gate_failures": sum(g["fail"] for g in summary["gates"]),
        "urls": run.get("urls") or [],
    }