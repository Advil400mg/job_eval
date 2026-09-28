"""Contract tests for TypeSafe Jev's score and typed evidence selection."""
from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import evaluate_job


class JevContractTests(unittest.TestCase):
    def setUp(self):
        self.text = ("CDI junior à Paris. Vous analysez des alertes dans Elastic SIEM "
                     "et automatisez des contrôles en Python. Un mentor accompagne "
                     "les nouvelles recrues chaque semaine.")
        self.criteria = [{"id": "technical_fit", "name": "Technique",
                          "description": "Missions techniques cyber avec Python et SIEM",
                          "weight": 2, "required": True, "min_score": 55}]

    def test_choices_are_source_substrings_with_none_option(self):
        sentences = evaluate_job.evidence_sentences(self.text)
        questions, proofs = evaluate_job.build_questions(self.criteria, sentences)
        proof_id, options = proofs["technical_fit"]
        self.assertEqual(questions[proof_id]["type"], "choice")
        self.assertEqual(questions["technical_fit"]["type"], "score")
        self.assertIsNone(options["none"])
        for quote in sentences.values():
            self.assertIn(quote, self.text)
        for quote in options.values():
            if quote:
                self.assertIn(quote, self.text)

    def test_unlisted_or_missing_proof_is_rejected(self):
        questions, proofs = evaluate_job.build_questions(
            self.criteria, evaluate_job.evidence_sentences(self.text))
        proof_id, _ = proofs["technical_fit"]
        response = {"answers": {
            "technical_fit": {"score": 3, "confidence": 0.8},
            proof_id: {"choice": "invented", "confidence": 0.8},
        }}
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            evaluate_job.validate_response(response, ["technical_fit"], proofs)
        del response["answers"][proof_id]
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            evaluate_job.validate_response(response, ["technical_fit"], proofs)

    def test_unverified_context_is_rejected(self):
        payload = {"url": "https://example.test/role", "title": "Junior analyst",
                   "company": "Demo", "job_text": self.text, "criteria": self.criteria,
                   "offer_context": {"contract": {"value": "permanent",
                                                  "evidence": "not in job text"}}}
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            evaluate_job.validate_input(payload)

    def test_second_batch_failure_never_emits_partial_result(self):
        criteria = [{**self.criteria[0], "id": f"criterion_{i}"} for i in range(7)]
        payload = {"url": "https://example.test/role", "title": "Junior analyst",
                   "company": "Demo", "job_text": self.text, "criteria": criteria}
        calls = 0

        def fake_call(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("provider unavailable")
            return {"answers": {qid: ({"score": 3, "confidence": 0.9}
                                      if q["type"] == "score" else {"choice": "none", "confidence": 0.9})
                                for qid, q in kwargs["questions"].items()},
                    "model": "test", "usage": {"cost": 0}}

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "input.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            output = io.StringIO()
            with mock.patch.object(sys, "argv", ["evaluate_job.py", str(path)]), \
                 mock.patch.object(evaluate_job, "call_jev", side_effect=fake_call), \
                 contextlib.redirect_stdout(output), self.assertRaisesRegex(RuntimeError, "provider unavailable"):
                evaluate_job.main()
        self.assertEqual(calls, 2)
        self.assertEqual(output.getvalue(), "")

    def test_score_and_verbatim_quote_survive_end_to_end(self):
        sentences = evaluate_job.evidence_sentences(self.text)
        all_criteria = self.criteria + evaluate_job.dimension_criteria(self.criteria)
        _, proofs = evaluate_job.build_questions(all_criteria, sentences)
        proof_id, options = proofs["technical_fit"]
        sentence_id = next(sid for sid, quote in options.items()
                           if quote and "Elastic SIEM" in quote)
        response = {"model": "test", "answers": {
            criterion["id"]: {"score": 4, "confidence": 0.9}
            for criterion in all_criteria
        }, "usage": {"cost": 0}}
        for criterion in all_criteria:
            pid, _ = proofs[criterion["id"]]
            response["answers"][pid] = {"choice": sentence_id if pid == proof_id else "none",
                                         "confidence": 0.8}
        payload = {"url": "https://example.test/role", "title": "Junior analyst",
                   "company": "Demo", "job_text": self.text, "criteria": self.criteria,
                   "minimum_global_score": 68, "minimum_confidence": 0.5}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "input.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            output = io.StringIO()
            with mock.patch.object(sys, "argv", ["evaluate_job.py", str(path)]), \
                 mock.patch.object(evaluate_job, "call_jev", return_value=response), \
                 contextlib.redirect_stdout(output):
                evaluate_job.main()
        result = json.loads(output.getvalue())
        self.assertTrue(result["jev_approved"])
        self.assertEqual(len(result["dimensions"]), len(evaluate_job.STANDARD_DIMENSIONS))
        self.assertEqual(result["criteria"][0]["evidence"]["quote"], options[sentence_id])
        self.assertIn(result["criteria"][0]["evidence"]["quote"], self.text)


if __name__ == "__main__":
    unittest.main()
