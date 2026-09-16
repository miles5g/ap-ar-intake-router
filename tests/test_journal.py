"""Journal balance, dummy-GL, and scrub-guard checks."""

from __future__ import annotations

import csv
import json
import re
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from apar_router.bill_control import build_bill_control
from apar_router.catalog import load_catalog
from apar_router.coa import DUMMY_PREFIX, CoaError, load_coa
from apar_router.export import write_pack
from apar_router.journal import JOURNAL_COLUMNS, build_journals, journal_totals, whole_dollars
from apar_router.pipeline import DEFAULT_FIXTURES, run_and_export, run_pipeline
from apar_router.report import format_output_label
from apar_router.safety import FORBIDDEN_TOKENS, SafetyError, scan_text

AS_OF = date(2026, 9, 11)
DESC_RE = re.compile(r"^\d{2}/\d{2}/\d{2} - .+/.+")
CONTROL_RE = re.compile(r"^\d{2}/\d{2}/\d{2} - Accounts (Payable|Receivable)$")


class JournalPackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = run_pipeline(DEFAULT_FIXTURES, as_of=AS_OF)
        cls.coa = load_coa(DEFAULT_FIXTURES / "coa.json")
        cls.catalog = load_catalog(DEFAULT_FIXTURES / "entities.json")
        cls.journals = build_journals(cls.result, cls.coa)
        cls.bill_control = build_bill_control(
            cls.result, cls.catalog, DEFAULT_FIXTURES / "recurring_bills.csv"
        )

    def test_coa_is_dummy_prefixed(self):
        self.assertTrue(self.coa.accounts)
        for account in self.coa.accounts:
            self.assertTrue(account.code.startswith(DUMMY_PREFIX), account.code)

    def test_journals_exist_per_resolved_entity_side(self):
        names = {journal.filename for journal in self.journals}
        self.assertIn("ENT-NWR_AP.csv", names)
        self.assertIn("ENT-NWR_AR.csv", names)
        self.assertIn("ENT-CGH_AP.csv", names)
        self.assertTrue(all(name.endswith(".csv") for name in names))
        self.assertGreaterEqual(len(self.journals), 8)

    def test_each_journal_balances(self):
        for journal in self.journals:
            debit, credit = journal_totals(journal)
            self.assertEqual(debit, credit, journal.filename)
            self.assertGreater(debit, 0, journal.filename)

    def test_whole_dollar_rounding(self):
        self.assertEqual(whole_dollars(Decimal("874.40")), Decimal("874"))
        self.assertEqual(whole_dollars(Decimal("874.50")), Decimal("875"))
        for journal in self.journals:
            for line in journal.lines:
                self.assertEqual(line.debit, line.debit.to_integral_value())
                self.assertEqual(line.credit, line.credit.to_integral_value())

    def test_sign_rule_and_single_control_row(self):
        for journal in self.journals:
            control = self.coa.control_accounts[journal.side.value]
            control_lines = [line for line in journal.lines if line.gl_code == control]
            self.assertEqual(len(control_lines), 1, journal.filename)
            self.assertTrue(CONTROL_RE.match(control_lines[0].description), control_lines[0].description)
            for line in journal.lines:
                if line.gl_code == control:
                    continue
                self.assertTrue(DESC_RE.match(line.description), line.description)
                self.assertTrue(
                    (line.debit > 0 and line.credit == 0)
                    or (line.credit > 0 and line.debit == 0),
                    line,
                )

    def test_credit_memo_is_a_credit(self):
        northwind_ap = next(j for j in self.journals if j.filename == "ENT-NWR_AP.csv")
        credit_lines = [
            line
            for line in northwind_ap.lines
            if "CM-NW-4425" in line.description
        ]
        self.assertEqual(len(credit_lines), 1)
        self.assertEqual(credit_lines[0].debit, 0)
        self.assertEqual(credit_lines[0].credit, Decimal("150"))

    def test_unresolved_entity_is_not_journaled(self):
        for journal in self.journals:
            self.assertNotEqual(journal.entity_id, "")
            self.assertNotIn("UNRESOLVED", journal.filename)

    def test_bill_control_has_fictional_recurring_vendors(self):
        vendors = {row.vendor for row in self.bill_control}
        self.assertIn("Acme Widgets", vendors)
        self.assertIn("Stark Supplies", vendors)
        acme = next(row for row in self.bill_control if row.vendor == "Acme Widgets")
        self.assertIn("15", acme.due_day_pattern)
        stark = next(
            row
            for row in self.bill_control
            if row.vendor == "Stark Supplies" and "Harbor" in row.entity_name
        )
        self.assertIn("1", stark.due_day_pattern)
        self.assertGreaterEqual(stark.occurrences, 3)

    def test_export_writes_balanced_csvs(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            written = write_pack(
                output,
                "# AP/AR Intake Triage Report\n\nsynthetic pack\n",
                self.journals,
                self.bill_control,
            )
            journal_paths = [path for path in written if path.parent.name == "journals"]
            self.assertEqual(len(journal_paths), len(self.journals))
            for path in journal_paths:
                with path.open(newline="", encoding="utf-8") as handle:
                    rows = list(csv.DictReader(handle))
                self.assertEqual(list(rows[0].keys()), list(JOURNAL_COLUMNS))
                debit = sum(Decimal(row["Debit"] or "0") for row in rows)
                credit = sum(Decimal(row["Credit"] or "0") for row in rows)
                self.assertEqual(debit, credit, path.name)
                for row in rows:
                    self.assertTrue(row["GL Code"].startswith(DUMMY_PREFIX))
            bill = (output / "bill_control.csv").read_text(encoding="utf-8")
            self.assertIn("Acme Widgets", bill)
            self.assertIn("Stark Supplies", bill)
            manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
            self.assertTrue(manifest["synthetic"])
            self.assertTrue(manifest["journals_balanced"])

    def test_cli_prints_triage_and_writes_journals(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "apar_router",
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
            self.assertIn("AP/AR Intake Triage Report", completed.stdout)
            self.assertIn("Journal pack", completed.stdout)
            self.assertIn("python3 -m apar_router", completed.stdout)
            self.assertTrue((output / "triage_report.md").is_file())
            self.assertTrue((output / "bill_control.csv").is_file())
            self.assertTrue((output / "journals" / "ENT-NWR_AP.csv").is_file())

    def test_run_and_export_helper(self):
        with tempfile.TemporaryDirectory() as tmp:
            report, written = run_and_export(
                DEFAULT_FIXTURES, as_of=AS_OF, output_dir=Path(tmp)
            )
            self.assertIn("Journal pack", report)
            self.assertTrue(written)

    def test_default_output_label_is_repo_relative(self):
        self.assertEqual(format_output_label(None), "output/journals/")
        self.assertEqual(
            format_output_label(REPO_ROOT / "output", suffix=""),
            "output/",
        )
        self.assertEqual(
            format_output_label(REPO_ROOT / "output"),
            "output/journals/",
        )


class ScrubGuardTests(unittest.TestCase):
    def test_fixtures_have_no_forbidden_tokens(self):
        for path in DEFAULT_FIXTURES.iterdir():
            if path.is_file():
                scan_text(path.read_text(encoding="utf-8"), source=str(path))

    def test_generated_pack_has_no_forbidden_tokens(self):
        result = run_pipeline(DEFAULT_FIXTURES, as_of=AS_OF)
        coa = load_coa(DEFAULT_FIXTURES / "coa.json")
        journals = build_journals(result, coa)
        blob = "\n".join(
            f"{journal.filename} {line.gl_code} {line.description}"
            for journal in journals
            for line in journal.lines
        )
        lowered = blob.lower()
        for token in FORBIDDEN_TOKENS:
            self.assertNotIn(token, lowered)
        self.assertNotIn("@", blob)
        self.assertNotIn("Gursey", blob)

    def test_scan_text_rejects_production_firm(self):
        with self.assertRaises(SafetyError):
            scan_text("please forward to Gursey AP", source="unit-test")

    def test_non_dummy_gl_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "coa.json"
            path.write_text(
                json.dumps(
                    {
                        "accounts": [{"code": "6100-100", "name": "Real looking", "type": "expense"}],
                        "control_accounts": {"AP": "6100-100", "AR": "6100-100"},
                        "vendor_gl": {},
                        "customer_gl": "6100-100",
                        "fallback_expense_gl": "6100-100",
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(CoaError):
                load_coa(path)


if __name__ == "__main__":
    unittest.main()
