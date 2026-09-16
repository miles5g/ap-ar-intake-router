"""Interview walkthrough banners and --no-pause CLI checks."""

from __future__ import annotations

import io
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from apar_router.pipeline import DEFAULT_FIXTURES, run_pipeline
from apar_router.safety import FORBIDDEN_TOKENS, scan_text
from apar_router.walkthrough import (
    Walkthrough,
    classify_lines,
    ingest_lines,
    intro_lines,
    journals_lines,
    render_box,
    report_lines,
    route_lines,
)

AS_OF = date(2026, 9, 11)
STAGE_MARKERS = ("SYNTHETIC DEMO", "INGEST", "CLASSIFY", "ROUTE", "REPORT", "JOURNALS")


class BoxTests(unittest.TestCase):
    def test_render_box_wraps_content(self):
        text = render_box(["INGEST — hello", "Talk track: keep it short."])
        self.assertIn("INGEST — hello", text)
        self.assertTrue(text.startswith("+"))
        self.assertTrue(text.endswith("+"))
        self.assertEqual(text.count("\n"), 3)

    def test_rendered_stage_boxes_stay_two_to_four_lines(self):
        result = run_pipeline(DEFAULT_FIXTURES, as_of=AS_OF)
        documents = [item.document for item in result.items]
        classified = [(item.document, item.classification) for item in result.items]
        boxes = [
            render_box(intro_lines()),
            render_box(ingest_lines(documents=documents)),
            render_box(classify_lines(classified=classified)),
            render_box(route_lines(items=result.items)),
            render_box(report_lines()),
            render_box(journals_lines(journals=[])),
        ]
        for box in boxes:
            content_rows = [row for row in box.splitlines() if row.startswith("|")]
            self.assertGreaterEqual(len(content_rows), 2, box)
            self.assertLessEqual(len(content_rows), 4, box)

    def test_stage_copy_is_short_and_synthetic(self):
        result = run_pipeline(DEFAULT_FIXTURES, as_of=AS_OF)
        documents = [item.document for item in result.items]
        classified = [(item.document, item.classification) for item in result.items]
        blobs = [
            intro_lines(),
            ingest_lines(documents=documents),
            classify_lines(classified=classified),
            route_lines(items=result.items),
            report_lines(),
            journals_lines(journals=[]),
        ]
        for lines in blobs:
            self.assertGreaterEqual(len(lines), 2, lines)
            self.assertLessEqual(len(lines), 4, lines)
            joined = "\n".join(lines)
            self.assertIn("Talk track:", joined)
            scan_text(joined, source="walkthrough copy")
            lowered = joined.lower()
            for token in FORBIDDEN_TOKENS:
                self.assertNotIn(token, lowered)
            for phrase in (
                "shapes are boring",
                "hottest work",
                "controller-style",
                "deterministic",
                "recruiter-safe",
                "exception pile",
                "scrubbed pack",
            ):
                self.assertNotIn(phrase, lowered, phrase)


class WalkthroughPresenterTests(unittest.TestCase):
    def test_no_pause_skips_enter_prompt(self):
        stderr = io.StringIO()
        stdin = io.StringIO("")
        guide = Walkthrough(pause=False, stream=stderr, stdin=stdin)
        guide.intro()
        out = stderr.getvalue()
        self.assertIn("SYNTHETIC DEMO", out)
        self.assertIn("Talk track:", out)
        self.assertNotIn("Press Enter", out)
        self.assertEqual(stdin.read(), "")

    def test_pause_waits_for_enter(self):
        stderr = io.StringIO()
        stdin = io.StringIO("\n")
        guide = Walkthrough(pause=True, stream=stderr, stdin=stdin)
        guide.intro()
        self.assertIn("Press Enter to continue.", stderr.getvalue())
        self.assertEqual(stdin.read(), "")


class WalkthroughCliTests(unittest.TestCase):
    def test_parser_accepts_short_and_long_flags(self):
        from apar_router.__main__ import build_parser

        parser = build_parser()
        args = parser.parse_args(["-w", "--no-pause"])
        self.assertTrue(args.walkthrough)
        self.assertTrue(args.no_pause)
        default = parser.parse_args([])
        self.assertFalse(default.walkthrough)
        self.assertFalse(default.no_pause)

    def test_walkthrough_no_pause(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "apar_router",
                    "--walkthrough",
                    "--no-pause",
                    "--as-of",
                    "2026-09-11",
                    "--output-dir",
                    str(output),
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            banners = completed.stderr
            for marker in STAGE_MARKERS:
                self.assertIn(marker, banners, marker)
            self.assertIn("Talk track:", banners)
            self.assertIn("All fake data.", banners)
            self.assertIn("I'm sorting what needs a human vs what can wait.", banners)
            self.assertIn("This is the summary screen.", banners)
            self.assertIn("Journals balance — still not a real post.", banners)
            self.assertIn("no employer sop", banners.lower())
            self.assertNotIn("Press Enter", banners)
            self.assertIn("AP/AR Intake Triage Report", completed.stdout)
            self.assertIn("Journal pack", completed.stdout)
            for token in ("Gursey", "kpmg", "deloitte", "pwc"):
                self.assertNotIn(token.lower(), (completed.stdout + banners).lower())
            self.assertTrue((output / "journals" / "ENT-NWR_AP.csv").is_file())

    def test_default_mode_has_no_banners(self):
        with tempfile.TemporaryDirectory() as tmp:
            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "apar_router",
                    "--as-of",
                    "2026-09-11",
                    "--output-dir",
                    tmp,
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        combined = completed.stdout + completed.stderr
        self.assertIn("AP/AR Intake Triage Report", completed.stdout)
        self.assertNotIn("SYNTHETIC DEMO", combined)
        self.assertNotIn("Talk track:", combined)
        self.assertNotIn("Press Enter", combined)


if __name__ == "__main__":
    unittest.main()
