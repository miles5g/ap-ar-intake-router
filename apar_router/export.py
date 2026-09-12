"""Write the scrubbed journal pack (journals, bill control, triage) to disk."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from apar_router.bill_control import BILL_CONTROL_COLUMNS
from apar_router.journal import JOURNAL_COLUMNS, journal_totals
from apar_router.models import BillControlRow, Journal
from apar_router.safety import scan_text


def _money_cell(value) -> str:
    if value == 0:
        return ""
    return str(int(value))


def write_journal_csv(path: Path, journal: Journal) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(JOURNAL_COLUMNS))
        writer.writeheader()
        for line in journal.lines:
            writer.writerow(
                {
                    "GL Code": line.gl_code,
                    "Debit": _money_cell(line.debit),
                    "Credit": _money_cell(line.credit),
                    "Description": line.description,
                }
            )
    scan_text(path.read_text(encoding="utf-8"), source=str(path))


def write_bill_control_csv(path: Path, rows: list[BillControlRow]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(BILL_CONTROL_COLUMNS))
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "Vendor": row.vendor,
                    "Entity": row.entity_name,
                    "Occurrences": row.occurrences,
                    "Typical Amount": str(int(row.typical_amount)),
                    "Due Day Pattern": row.due_day_pattern,
                    "Cadence": row.cadence,
                    "Last Document": row.last_document,
                    "Last Date": row.last_date.isoformat() if row.last_date.year > 1 else "",
                }
            )
    scan_text(path.read_text(encoding="utf-8"), source=str(path))


def write_pack(
    output_dir: Path,
    report: str,
    journals: list[Journal],
    bill_control: list[BillControlRow],
) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    scan_text(report, source="triage report")
    written: list[Path] = []

    report_path = output_dir / "triage_report.md"
    report_path.write_text(report if report.endswith("\n") else report + "\n", encoding="utf-8")
    written.append(report_path)

    journals_dir = output_dir / "journals"
    for journal in journals:
        debit, credit = journal_totals(journal)
        if debit != credit:
            raise ValueError(
                f"{journal.filename} is out of balance: debit {debit} != credit {credit}"
            )
        path = journals_dir / journal.filename
        write_journal_csv(path, journal)
        written.append(path)

    bill_path = output_dir / "bill_control.csv"
    write_bill_control_csv(bill_path, bill_control)
    written.append(bill_path)

    manifest = {
        "synthetic": True,
        "journals_balanced": True,
        "journal_count": len(journals),
        "bill_control_rows": len(bill_control),
        "files": [str(path.relative_to(output_dir)) for path in written]
        + ["manifest.json"],
    }
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    scan_text(manifest_path.read_text(encoding="utf-8"), source=str(manifest_path))
    written.append(manifest_path)
    return written
