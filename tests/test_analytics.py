"""Offline tests for the dashboard aggregations (stdlib only).

Run:  python3 tests/test_analytics.py
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import analytics  # noqa: E402


def offer(title, score=None, status="rejected", criteria=None, gates=None,
          low_conf=None, usage=None, published="2026-09-10"):
    payload = {
        "url": f"https://example.test/{title.replace(' ', '-')}",
        "title": title, "company": "ACME", "location": "Paris",
        "published_at": published, "gate_results": gates or [],
        "decision": {"status": status} if status else {},
    }
    if score is not None:
        payload["jev"] = {
            "global_score": score, "minimum_global_score": 68,
            "blocking_criteria": [c["id"] for c in (criteria or []) if c["required"] and not c["passed"]],
            "low_confidence_criteria": low_conf or [],
            "criteria": criteria or [], "usage": usage or {},
        }
    return payload


CRIT_JUNIOR = {"id": "junior_fit", "name": "Compatibilité junior", "score": 40.0, "weight": 5,
               "required": True, "min_score": 70, "passed": False, "confidence": 0.3}
CRIT_DOMAIN = {"id": "technical_domain_fit", "name": "Domaine", "score": 80.0, "weight": 5,
               "required": True, "min_score": 60, "passed": True, "confidence": 0.7}


class Summarize(unittest.TestCase):
    def setUp(self):
        self.results = [
            offer("A", score=72.0, status="qualified",
                  criteria=[CRIT_JUNIOR, CRIT_DOMAIN], low_conf=["junior_fit"],
                  usage={"cost": 0.0002, "input_tokens": 5000}),
            offer("B", score=40.0, criteria=[CRIT_JUNIOR, CRIT_DOMAIN]),
            offer("C", status="error"),
        ]
        self.stats = analytics.summarize(self.results)

    def test_counts(self):
        self.assertEqual(self.stats["offers"], 3)
        self.assertEqual(self.stats["scored"], 2)
        self.assertEqual(self.stats["qualified"], 1)
        self.assertEqual(self.stats["rejected"], 1)
        self.assertEqual(self.stats["errors"], 1)

    def test_scores_and_cost(self):
        self.assertEqual(self.stats["avg_score"], 56.0)
        self.assertEqual(self.stats["best_score"], 72.0)
        self.assertAlmostEqual(self.stats["jev_cost"], 0.0002, places=6)
        self.assertEqual(self.stats["jev_input_tokens"], 5000)

    def test_distribution_covers_every_scored_offer(self):
        self.assertEqual(sum(b["count"] for b in self.stats["distribution"]), 2)

    def test_criteria_aggregates(self):
        rows = {c["id"]: c for c in self.stats["criteria"]}
        self.assertEqual(rows["junior_fit"]["evaluated"], 2)
        self.assertEqual(rows["junior_fit"]["avg_score"], 40.0)
        self.assertEqual(rows["junior_fit"]["blocking"], 2)
        self.assertEqual(rows["junior_fit"]["blocking_share"], 100.0)
        self.assertEqual(rows["junior_fit"]["low_confidence"], 1)
        self.assertEqual(rows["technical_domain_fit"]["blocking"], 0)

    def test_blocking_criteria_sorted_first(self):
        self.assertEqual(self.stats["criteria"][0]["id"], "junior_fit")

    def test_top_offers_sorted_by_score(self):
        self.assertEqual([o["title"] for o in self.stats["top_offers"]], ["A", "B"])

    def test_gate_counters(self):
        results = [offer("D", score=50.0, gates=[
            {"gate": "freshness", "status": "fail", "reason": "vieille", "hard": True},
            {"gate": "contract_type", "status": "pass", "reason": "CDI", "hard": True},
        ])]
        stats = analytics.summarize(results)
        gates = {g["gate"]: g for g in stats["gates"]}
        self.assertEqual(gates["freshness"]["fail"], 1)
        self.assertEqual(gates["contract_type"]["pass"], 1)
        self.assertIn("vieille", gates["freshness"]["reasons"])


class RunSummary(unittest.TestCase):
    def test_summary_shape(self):
        run = {"id": "abc", "created_at": "2026-09-22T10:00:00", "status": "done",
               "progress": 2, "total": 2, "urls": ["https://a", "https://b"],
               "results": [offer("A", score=80.0, status="qualified"),
                           offer("B", score=30.0)]}
        summary = analytics.run_summary(run)
        self.assertEqual(summary["offers"], 2)
        self.assertEqual(summary["best_score"], 80.0)
        self.assertEqual(summary["avg_score"], 55.0)
        self.assertEqual(summary["qualified"], 1)
        self.assertEqual(summary["top"][0]["title"], "A")

    def test_empty_run(self):
        summary = analytics.run_summary({"id": "x", "results": []})
        self.assertEqual(summary["offers"], 0)
        self.assertIsNone(summary["avg_score"])


if __name__ == "__main__":
    unittest.main(verbosity=2)