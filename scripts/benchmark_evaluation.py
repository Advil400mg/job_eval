#!/usr/bin/env python3
"""Benchmark the JEV evaluation pipeline against the synthetic corpus.

Offline mode validates the corpus and measures deterministic gates only. It
never invents a Jev answer or reports simulated verdict accuracy. Live mode
calls the configured Jev evaluator and is intentionally opt-in (paid API).
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import sys
import tempfile
import time
from collections import Counter
from datetime import date, timedelta, timezone, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import gates, pipeline  # noqa: E402

DEFAULT_CORPUS = ROOT / "tests" / "corpus" / "v1"
CLASSES = ("compatible", "incompatible", "ambiguous")


def load_corpus(path: Path) -> tuple[dict, list[dict]]:
    profile_path = path / "profile.json"
    if not profile_path.exists():
        # Holdouts deliberately reuse the frozen v1 synthetic candidate profile.
        profile_path = DEFAULT_CORPUS / "profile.json"
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    cases = [json.loads(item.read_text(encoding="utf-8"))
             for item in sorted((path / "cases").glob("*.json"))]
    validate_corpus(profile, cases, require_v1=path.resolve() == DEFAULT_CORPUS.resolve())
    return profile, cases


def validate_corpus(profile: dict, cases: list[dict], require_v1: bool = True) -> None:
    if not isinstance(profile.get("criteria"), list) or not profile["criteria"]:
        raise ValueError("Le profil du corpus doit contenir des critères")
    if not cases:
        raise ValueError("Le corpus doit contenir au moins un cas")
    if require_v1 and len(cases) != 30:
        raise ValueError(f"Le corpus v1 doit contenir 30 cas, reçu {len(cases)}")
    identifiers: set[str] = set()
    distribution = Counter()
    for case in cases:
        identifier = case.get("id")
        expected = case.get("expected_class")
        offer = case.get("offer") or {}
        if not isinstance(identifier, str) or not identifier:
            raise ValueError("Chaque cas doit avoir un id")
        if identifier in identifiers:
            raise ValueError(f"Cas dupliqué : {identifier}")
        identifiers.add(identifier)
        if expected not in CLASSES:
            raise ValueError(f"Classe invalide pour {identifier}: {expected}")
        expected_gates = case.get("expected", {}).get("gates", {})
        if not isinstance(expected_gates, dict) or any(
            name not in {"contract_type", "experience", "freshness", "availability"}
            or status not in {"pass", "fail", "warn", "unknown"}
            for name, status in expected_gates.items()
        ):
            raise ValueError(f"Portes annotées invalides pour {identifier}")
        if expected != "incompatible" and "fail" in expected_gates.values():
            raise ValueError(f"{identifier}: une porte bloquante contredit la classe {expected}")
        distribution[expected] += 1
        for field in ("url", "title", "company", "location", "job_text"):
            if not isinstance(offer.get(field), str) or not offer[field].strip():
                raise ValueError(f"{identifier}: offer.{field} est requis")
        if len(offer["job_text"].strip()) < 200:
            raise ValueError(f"{identifier}: texte trop court")
        expected_data = case.get("expected", {})
        evidence = (expected_data.get("facts") or {}).get("evidence", [])
        quotes = expected_data.get("evidence_contains", [])
        if (not isinstance(evidence, list) or not isinstance(quotes, list)
                or any(not isinstance(quote, str) or not quote
                       or quote not in offer["job_text"] for quote in evidence + quotes)):
            raise ValueError(f"{identifier}: preuve absente du texte de l'annonce")
    if require_v1:
        expected_distribution = Counter({name: 10 for name in CLASSES})
        if distribution != expected_distribution:
            raise ValueError(f"Distribution invalide : {dict(distribution)}")


def metadata(case: dict) -> dict:
    offer = case["offer"]
    published = date.today() - timedelta(days=int(offer.get("published_days_ago", 5)))
    return {
        "title": offer["title"],
        "company": offer["company"],
        "location": offer["location"],
        "published_at": published.isoformat(),
    }


def classify(record: dict) -> str:
    if record.get("status") != "ok":
        return "error"
    evaluation = record.get("evaluation") or {}
    decision = record.get("decision") or {}
    if evaluation.get("review_required") or decision.get("review_required"):
        return "ambiguous"
    gates_result = record.get("gate_results") or []
    hard_fail = any(item.get("hard") and item.get("status") == "fail" for item in gates_result)
    if hard_fail:
        return "incompatible"
    if decision.get("status") == "rejected" and "review_required" in decision:
        return "incompatible"
    if decision.get("unknowns") or decision.get("warnings"):
        return "ambiguous"
    if decision.get("status") == "qualified":
        return "compatible"
    return "incompatible"


def offline_record(case: dict, profile: dict) -> dict:
    """Only run deterministic code; never infer Jev's answer from the answer key."""
    offer = {**case["offer"], **metadata(case)}
    return {"gate_results": gates.run_gates(offer, profile)}


def gate_metrics(rows: list[dict], cases_by_id: dict[str, dict]) -> dict:
    checked = correct = 0
    by_gate: dict[str, dict[str, int]] = {}
    for row in rows:
        expected = cases_by_id[row["id"]]["expected"].get("gates", {})
        actual = {gate["gate"]: gate["status"] for gate in row["gate_results"] or []}
        for name, status in expected.items():
            checked += 1
            correct += actual.get(name) == status
            entry = by_gate.setdefault(name, {"checked": 0, "correct": 0})
            entry["checked"] += 1
            entry["correct"] += actual.get(name) == status
    return {"checked": checked, "correct": correct,
            "accuracy": round(correct / checked, 4) if checked else None,
            "by_gate": by_gate}


def live_record(case: dict, profile: dict) -> dict:
    offer = case["offer"]
    return pipeline.evaluate_text(
        offer["url"], offer["job_text"], profile, metadata=metadata(case),
    )


def calculate_metrics(rows: list[dict]) -> dict:
    total = len(rows)
    exact = sum(row["expected"] == row["predicted"] for row in rows)
    by_class = {}
    for name in CLASSES:
        selected = [row for row in rows if row["expected"] == name]
        correct = sum(row["predicted"] == name for row in selected)
        by_class[name] = {
            "total": len(selected), "correct": correct,
            "recall": round(correct / len(selected), 4) if selected else None,
        }
    false_positives = sum(
        row["predicted"] == "compatible" and row["expected"] != "compatible"
        for row in rows
    )
    return {
        "total": total,
        "correct": exact,
        "accuracy": round(exact / total, 4) if total else None,
        "false_positives": false_positives,
        "false_positive_rate": round(false_positives / total, 4) if total else None,
        "by_class": by_class,
        "prediction_distribution": dict(Counter(row["predicted"] for row in rows)),
    }


def atomic_write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("offline", "live"), default="offline")
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--critical-only", action="store_true")
    parser.add_argument("--repetitions", type=int, default=1)
    parser.add_argument("--workers", type=int, default=1)
    args = parser.parse_args()
    if not 1 <= args.repetitions <= 5:
        parser.error("--repetitions doit être compris entre 1 et 5")
    if not 1 <= args.workers <= 8:
        parser.error("--workers doit être compris entre 1 et 8")

    profile, cases = load_corpus(args.corpus)
    if args.critical_only:
        cases = [case for case in cases if case.get("difficulty") == "hard"]
    started = time.monotonic()
    jobs = [(repetition, case) for repetition in range(1, args.repetitions + 1)
            for case in cases]

    def execute(job: tuple[int, dict]) -> dict:
        repetition, case = job
        record = offline_record(case, profile) if args.mode == "offline" else live_record(case, profile)
        row = {
            "id": case["id"], "repetition": repetition,
            "expected": case["expected_class"],
            "predicted": classify(record) if args.mode == "live" else None,
            "status": record.get("status") if args.mode == "live" else "deterministic",
            "stage": record.get("stage"), "error": record.get("error"),
            "decision": record.get("decision"), "jev": record.get("jev"),
            "gate_results": record.get("gate_results"),
            "facts": record.get("facts"), "evaluation": record.get("evaluation"),
        }
        if args.mode == "live":
            print(f"{case['id']}: {row['expected']} -> {row['predicted']}", file=sys.stderr)
        return row

    if args.workers == 1:
        rows = [execute(job) for job in jobs]
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
            rows = list(pool.map(execute, jobs))

    metrics: dict[str, object] = {"gates": gate_metrics(rows, {case["id"]: case for case in cases})}
    if args.mode == "live":
        metrics["verdicts"] = calculate_metrics(rows)
        metrics["failures"] = sum(row["status"] != "ok" for row in rows)
        metrics["cost_usd"] = round(sum(
            ((row.get("jev") or {}).get("usage") or {}).get("cost") or 0
            for row in rows
        ), 6)
        metrics["unstable_cases"] = sorted({
            case_id for case_id in {row["id"] for row in rows}
            if len({row["predicted"] for row in rows if row["id"] == case_id}) > 1
        })
    report = {
        "benchmark_schema_version": 1,
        "corpus_version": "v1", "mode": args.mode,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "duration_seconds": round(time.monotonic() - started, 3),
        "repetitions": args.repetitions,
        "metrics": metrics, "cases": rows,
    }
    if args.output:
        atomic_write(args.output, report)
    print(json.dumps(report["metrics"], ensure_ascii=False, indent=2))
    return 0 if args.mode == "offline" or all(row["status"] == "ok" for row in rows) else 2


if __name__ == "__main__":
    raise SystemExit(main())
