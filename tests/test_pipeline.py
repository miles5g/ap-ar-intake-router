"""Smoke and rule checks for the synthetic AP/AR router."""

from __future__ import annotations

import subprocess
import sys
import unittest
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from apar_router.models import ExceptionType, Queue, Side, Urgency
from apar_router.pipeline import DEFAULT_FIXTURES, run_and_render, run_pipeline

AS_OF = date(2026, 9, 11)


def _by_id(result):
    return {item.document.doc_id: item for item in result.items}


class PipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = run_pipeline(DEFAULT_FIXTURES, as_of=AS_OF)
        cls.items = _by_id(cls.result)

    def test_fixture_files_exist(self):
        for name in (
            "entities.json",
            "invoices.csv",
            "remittances.json",
            "coa.json",
            "recurring_bills.csv",
        ):
            self.assertTrue((DEFAULT_FIXTURES / name).is_file(), name)

    def test_ingest_count(self):
        # 18 invoice/credit rows + 7 remittances
        self.assertEqual(len(self.result.items), 25)

    def test_matched_remittance_goes_to_cash_app(self):
        item = self.items["RMT-1001"]
        self.assertEqual(item.classification.side, Side.AR)
        self.assertEqual(item.classification.exception_type, ExceptionType.NONE)
        self.assertEqual(item.routing.queue, Queue.AR_CASH_APPLICATION)
        self.assertEqual(item.routing.reason_code, "RC-CLEAN-AR")

    def test_short_pay_unapplied(self):
        item = self.items["RMT-1003"]
        self.assertEqual(item.classification.exception_type, ExceptionType.SHORT_PAY)
        self.assertEqual(item.routing.queue, Queue.AR_UNAPPLIED_CASH)
        self.assertEqual(item.routing.reason_code, "RC-SHORT-PAY")

    def test_overpay_and_unallocated(self):
        self.assertEqual(self.items["RMT-1005"].classification.exception_type, ExceptionType.OVERPAYMENT)
        self.assertEqual(
            self.items["RMT-1004"].classification.exception_type,
            ExceptionType.UNALLOCATED_REMITTANCE,
        )
        self.assertEqual(
            self.items["RMT-1006"].classification.exception_type,
            ExceptionType.MISSING_REMIT_ADVICE,
        )

    def test_amount_variance_on_remittance(self):
        item = self.items["RMT-1007"]
        self.assertEqual(item.classification.exception_type, ExceptionType.AMOUNT_VARIANCE)
        self.assertEqual(item.routing.reason_code, "RC-AMT-VAR")

    def test_duplicate_invoice_pair(self):
        for doc_id in ("DOC-003", "DOC-004"):
            item = self.items[doc_id]
            self.assertEqual(item.classification.exception_type, ExceptionType.DUPLICATE_INVOICE)
            self.assertEqual(item.routing.queue, Queue.AP_EXCEPTION)
            self.assertEqual(item.routing.reason_code, "RC-DUP-INV")

    def test_missing_po_and_alias_entity(self):
        missing = self.items["DOC-002"]
        self.assertEqual(missing.classification.exception_type, ExceptionType.MISSING_PO)
        self.assertEqual(missing.routing.reason_code, "RC-PO-MISSING")

        alias = self.items["DOC-013"]
        self.assertEqual(alias.classification.entity_name, "Cedar Grove Holdings")
        self.assertEqual(alias.classification.exception_type, ExceptionType.NONE)
        self.assertEqual(alias.routing.queue, Queue.AP_PROCESS)

    def test_blank_and_unknown_entity(self):
        blank = self.items["DOC-009"]
        self.assertEqual(blank.classification.exception_type, ExceptionType.ENTITY_AMBIGUOUS)
        self.assertEqual(blank.routing.queue, Queue.ENTITY_REVIEW)

        unknown = self.items["DOC-018"]
        self.assertEqual(unknown.classification.exception_type, ExceptionType.ENTITY_AMBIGUOUS)
        self.assertEqual(unknown.classification.urgency, Urgency.CRITICAL)
        self.assertEqual(unknown.routing.queue, Queue.URGENT_ESCALATION)
        self.assertEqual(unknown.routing.reason_code, "RC-ESCALATE")

    def test_unknown_vendor_and_past_due_ar(self):
        vendor = self.items["DOC-010"]
        self.assertEqual(vendor.classification.exception_type, ExceptionType.UNKNOWN_COUNTERPARTY)
        self.assertEqual(vendor.routing.queue, Queue.AP_EXCEPTION)

        past_due = self.items["DOC-012"]
        self.assertEqual(past_due.classification.side, Side.AR)
        self.assertEqual(past_due.classification.urgency, Urgency.CRITICAL)
        self.assertEqual(past_due.routing.queue, Queue.URGENT_ESCALATION)

    def test_clean_ap_and_open_ar(self):
        ap = self.items["DOC-007"]
        self.assertEqual(ap.classification.exception_type, ExceptionType.NONE)
        self.assertEqual(ap.routing.queue, Queue.AP_PROCESS)

        credit = self.items["DOC-014"]
        self.assertEqual(credit.document.kind.value, "credit_memo")
        self.assertEqual(credit.classification.exception_type, ExceptionType.NONE)
        self.assertEqual(credit.classification.urgency, Urgency.LOW)
        self.assertEqual(credit.routing.queue, Queue.AP_PROCESS)

        ar = self.items["DOC-008"]
        self.assertEqual(ar.classification.side, Side.AR)
        self.assertEqual(ar.routing.queue, Queue.AR_OPEN_ITEMS)

    def test_every_item_has_reason_and_queue(self):
        for item in self.result.items:
            self.assertTrue(item.routing.reason_code.startswith("RC-"))
            self.assertTrue(item.routing.rationale)
            self.assertIsInstance(item.routing.queue, Queue)

    def test_report_contains_expected_sections(self):
        report = run_and_render(DEFAULT_FIXTURES, as_of=AS_OF)
        for fragment in (
            "# AP/AR Intake Triage Report",
            "Queue summary",
            "Exception mix",
            "By entity",
            "Routed work",
            "Journal pack",
            "Northwind Retail LLC",
            "Cedar Grove Holdings",
            "`URGENT_ESCALATION`",
            "fictional entities",
        ):
            self.assertIn(fragment, report)

    def test_cli_smoke(self):
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "apar_router",
                "--as-of",
                "2026-09-11",
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("AP/AR Intake Triage Report", completed.stdout)
        self.assertIn("RMT-1001", completed.stdout)
        self.assertIn("Journal pack", completed.stdout)
        self.assertNotIn("Gursey", completed.stdout)
        for token in ("kpmg", "deloitte", "pwc"):
            self.assertNotIn(token, completed.stdout.lower())


if __name__ == "__main__":
    unittest.main()
