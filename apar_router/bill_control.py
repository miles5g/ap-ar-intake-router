"""Lightweight bill-control summary for recurring fictional vendors."""

from __future__ import annotations

import csv
from collections import defaultdict
from datetime import date
from decimal import Decimal
from pathlib import Path
from statistics import median

from apar_router.catalog import resolve_entity
from apar_router.ingest import parse_date, parse_money
from apar_router.journal import whole_dollars
from apar_router.models import (
    BillControlRow,
    Catalog,
    DocKind,
    PipelineResult,
    Side,
)
from apar_router.safety import scan_text

BILL_CONTROL_COLUMNS = (
    "Vendor",
    "Entity",
    "Occurrences",
    "Typical Amount",
    "Due Day Pattern",
    "Cadence",
    "Last Document",
    "Last Date",
)


def due_day_pattern(days: list[int], cadence: str = "monthly") -> str:
    unique = sorted({day for day in days if day})
    if not unique:
        return "Unknown"
    label = cadence.strip() or "monthly"
    if len(unique) == 1:
        day = unique[0]
        suffix = "th" if 11 <= day <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
        return f"{label.title()} on the {day}{suffix}"
    return f"Mixed due days ({', '.join(str(d) for d in unique)})"


def load_recurring_bills(path: Path, catalog: Catalog) -> list[BillControlRow]:
    if not path.is_file():
        return []
    scan_text(path.read_text(encoding="utf-8"), source=str(path))
    grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            vendor = (row.get("vendor") or "").strip()
            if not vendor:
                continue
            hint = (row.get("entity_hint") or "").strip()
            entity = resolve_entity(hint, catalog)
            entity_name = entity.legal_name if entity else (hint or "(blank)")
            grouped[(vendor, entity_name)].append(row)

    summaries: list[BillControlRow] = []
    for (vendor, entity_name), rows in grouped.items():
        rows.sort(key=lambda row: row.get("invoice_date") or "")
        last = rows[-1]
        amounts = [whole_dollars(parse_money(row.get("amount", "0"))) for row in rows]
        days = [int(row["due_day"]) for row in rows if str(row.get("due_day") or "").isdigit()]
        cadence = (last.get("cadence") or "monthly").strip()
        last_date = parse_date(last.get("invoice_date") or "") or date.min
        summaries.append(
            BillControlRow(
                vendor=vendor,
                entity_name=entity_name,
                occurrences=len(rows),
                typical_amount=whole_dollars(Decimal(median(amounts))),
                due_day_pattern=due_day_pattern(days, cadence),
                cadence=cadence,
                last_document=(last.get("document_ref") or "").strip(),
                last_date=last_date,
            )
        )
    return summaries


def _from_intake(result: PipelineResult) -> list[BillControlRow]:
    grouped: dict[tuple[str, str], list] = defaultdict(list)
    for item in result.items:
        if item.document.kind is not DocKind.VENDOR_INVOICE:
            continue
        if item.classification.side is not Side.AP:
            continue
        vendor = item.document.counterparty
        if not vendor:
            continue
        grouped[(vendor, item.classification.entity_name)].append(item)

    rows: list[BillControlRow] = []
    for (vendor, entity_name), items in grouped.items():
        if len(items) < 2:
            continue
        items.sort(key=lambda item: (item.document.doc_date, item.document.doc_id))
        last = items[-1]
        amounts = [whole_dollars(item.document.amount) for item in items]
        days = [item.document.due_date.day for item in items if item.document.due_date]
        rows.append(
            BillControlRow(
                vendor=vendor,
                entity_name=entity_name,
                occurrences=len(items),
                typical_amount=whole_dollars(Decimal(median(amounts))),
                due_day_pattern=due_day_pattern(days),
                cadence="monthly",
                last_document=last.document.invoice_number or last.document.doc_id,
                last_date=last.document.doc_date,
            )
        )
    return rows


def build_bill_control(
    result: PipelineResult,
    catalog: Catalog,
    recurring_path: Path,
) -> list[BillControlRow]:
    # Recurring fixture first (Acme Widgets, Stark Supplies), then batch repeats.
    seen: set[tuple[str, str]] = set()
    merged: list[BillControlRow] = []
    for row in load_recurring_bills(recurring_path, catalog):
        key = (row.vendor, row.entity_name)
        if key in seen:
            continue
        seen.add(key)
        merged.append(row)
    for row in _from_intake(result):
        key = (row.vendor, row.entity_name)
        if key in seen:
            continue
        seen.add(key)
        merged.append(row)
    merged.sort(key=lambda row: (row.vendor, row.entity_name))
    return merged
