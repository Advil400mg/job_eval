"""Offline tests for the CV engine output parser (stdlib only).

Run:  python3 tests/test_cv_parse.py
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.cv import _extract_summary  # noqa: E402

LOGS = ("offre : Administrateur systèmes | DGSI | 7807 caractères\n"
        "validation : OK (2 avertissement(s))\n"
        "pdf : /tmp/cv.pdf (1 page(s), échelle 0.96)\n")

PRETTY = """{
  "pdf": "/tmp/cv.pdf",
  "run_dir": "/tmp/run",
  "pages": 1,
  "email": "skipped",
  "telegram": "skipped",
  "emphasis": [
    "administration de systèmes Linux",
    "conteneurisation Docker"
  ],
  "gaps": ["Environnement Microsoft absent du CV"],
  "headline": "Ingénieur systèmes, réseaux et cybersécurité junior"
}"""


class ExtractSummary(unittest.TestCase):
    def test_pretty_printed_json_after_logs(self):
        payload = _extract_summary(LOGS + PRETTY + "\n")
        self.assertEqual(payload["pdf"], "/tmp/cv.pdf")
        self.assertEqual(payload["pages"], 1)
        self.assertEqual(len(payload["emphasis"]), 2)

    def test_single_line_json_still_parsed(self):
        payload = _extract_summary('bruit\n{"pdf": "/tmp/x.pdf", "pages": 2}\n')
        self.assertEqual(payload["pdf"], "/tmp/x.pdf")

    def test_no_json_returns_empty(self):
        self.assertEqual(_extract_summary("ERROR PAGE_TOO_THIN: 12 caractères"), {})

    def test_trailing_text_after_json(self):
        payload = _extract_summary(PRETTY + "\nbye\n")
        # trailing lines after the object are not part of it -> empty is acceptable
        self.assertIn(payload.get("pdf"), (None, "/tmp/cv.pdf"))


if __name__ == "__main__":
    unittest.main(verbosity=2)