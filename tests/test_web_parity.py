"""Browser pipeline must match the Python pack on the synthetic fixtures."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

from apar_router.export import write_pack
from apar_router.pipeline import DEFAULT_FIXTURES, build_pack, run_pipeline
from apar_router.report import render_report

AS_OF = date(2026, 9, 11)
SAMPLE_FILES = (
    "entities.json",
    "invoices.csv",
    "remittances.json",
    "coa.json",
    "recurring_bills.csv",
)


class WebParityTests(unittest.TestCase):
    def test_readme_leads_with_demo_link(self):
        readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        self.assertTrue(
            readme.startswith(
                "**[Open the demo](https://miles5g.github.io/ap-ar-intake-router/)**\n"
            )
        )

    def test_pages_workflow_publishes_docs(self):
        workflow = (REPO_ROOT / ".github" / "workflows" / "pages.yml").read_text(encoding="utf-8")
        self.assertIn("path: docs", workflow)
        self.assertIn("actions/deploy-pages@v4", workflow)

    def test_demo_page_marks_sample_data(self):
        page = (REPO_ROOT / "docs" / "index.html").read_text(encoding="utf-8")
        self.assertIn("Sample data only", page)
        self.assertNotIn("Powered by AI", page)

    def test_sample_files_match_fixtures(self):
        sample = REPO_ROOT / "docs" / "sample"
        for name in SAMPLE_FILES:
            self.assertEqual(
                (sample / name).read_bytes(),
                (DEFAULT_FIXTURES / name).read_bytes(),
                name,
            )

    def test_js_pack_matches_python(self):
        node = shutil.which("node")
        self.assertIsNotNone(node, "node is required for the web parity check")
        fixed = datetime(2026, 9, 11, 15, 4, tzinfo=timezone.utc)
        result = run_pipeline(DEFAULT_FIXTURES, as_of=AS_OF)
        journals, bill_control = build_pack(result, DEFAULT_FIXTURES)
        report = render_report(
            result,
            generated_at=fixed,
            journals=journals,
            bill_control=bill_control,
            output_dir=REPO_ROOT / "output",
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            python_out = root / "python"
            js_out = root / "js"
            write_pack(python_out, report, journals, bill_control)
            completed = subprocess.run(
                [
                    node,
                    str(REPO_ROOT / "tests" / "js_pack.mjs"),
                    "--fixtures",
                    str(DEFAULT_FIXTURES),
                    "--out",
                    str(js_out),
                    "--as-of",
                    "2026-09-11",
                    "--generated-at",
                    "2026-09-11T15:04:00Z",
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            python_files = {
                path.relative_to(python_out).as_posix(): path.read_bytes()
                for path in python_out.rglob("*")
                if path.is_file()
            }
            js_files = {
                path.relative_to(js_out).as_posix(): path.read_bytes()
                for path in js_out.rglob("*")
                if path.is_file()
            }
            self.assertEqual(sorted(js_files), sorted(python_files))
            for name in sorted(python_files):
                if python_files[name] != js_files[name]:
                    self.fail(
                        name
                        + "\n--- python ---\n"
                        + python_files[name].decode("utf-8", "replace")
                        + "\n--- js ---\n"
                        + js_files[name].decode("utf-8", "replace")
                    )


if __name__ == "__main__":
    unittest.main()
