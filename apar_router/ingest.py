"""Ingest synthetic invoices (CSV) and remittances (JSON)."""

from __future__ import annotations

import csv
import json
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from apar_router.models import DocKind, SourceDocument


def parse_date(value: str) -> date | None:
    text = (value or "").strip()
    if not text:
        return None
    return datetime.strptime(text, "%Y-%m-%d").date()


def parse_money(value: object) -> Decimal:
    try:
        return Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError) as exc:
        raise ValueError(f"invalid amount: {value!r}") from exc


def load_invoices(path: Path) -> list[SourceDocument]:
    docs: list[SourceDocument] = []
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            if not (row.get("doc_id") or "").strip():
                continue
            docs.append(
                SourceDocument(
                    doc_id=row["doc_id"].strip(),
                    kind=DocKind(row["kind"].strip()),
                    entity_hint=row.get("entity_hint", "").strip(),
                    counterparty=row.get("counterparty", "").strip(),
                    invoice_number=row.get("invoice_number", "").strip(),
                    amount=parse_money(row.get("amount", "0")),
                    currency=(row.get("currency") or "USD").strip(),
                    doc_date=parse_date(row.get("doc_date", "") or "") or date.min,
                    due_date=parse_date(row.get("due_date", "") or ""),
                    po_number=row.get("po_number", "").strip(),
                    description=row.get("description", "").strip(),
                )
            )
    return docs


def load_remittances(path: Path) -> list[SourceDocument]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    rows = raw["remittances"] if isinstance(raw, dict) else raw
    docs: list[SourceDocument] = []
    for row in rows:
        payment_date = parse_date(str(row.get("payment_date") or "")) or date.min
        applied = row.get("applied_amount")
        docs.append(
            SourceDocument(
                doc_id=str(row["doc_id"]).strip(),
                kind=DocKind.REMITTANCE,
                entity_hint=str(row.get("entity_hint") or "").strip(),
                counterparty=str(row.get("payer") or "").strip(),
                invoice_number=str(row.get("invoice_ref") or "").strip(),
                amount=parse_money(row.get("amount", "0")),
                currency=str(row.get("currency") or "USD").strip(),
                doc_date=payment_date,
                due_date=None,
                po_number="",
                description=str(row.get("description") or "").strip(),
                payment_ref=str(row.get("payment_ref") or row.get("invoice_ref") or "").strip(),
                applied_invoice=str(row.get("invoice_ref") or "").strip(),
                applied_amount=parse_money(applied) if applied not in (None, "") else None,
            )
        )
    return docs


def load_documents(fixtures_dir: Path) -> list[SourceDocument]:
    invoices = load_invoices(fixtures_dir / "invoices.csv")
    remittances = load_remittances(fixtures_dir / "remittances.json")
    return invoices + remittances
