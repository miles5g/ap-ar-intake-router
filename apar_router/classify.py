"""Rule-based classification for synthetic AP/AR documents."""

from __future__ import annotations

from collections import Counter
from datetime import date
from decimal import Decimal

from apar_router.catalog import known_counterparty, resolve_entity
from apar_router.models import (
    EXCEPTION_PRIORITY,
    URGENCY_RANK,
    Catalog,
    Classification,
    DocKind,
    ExceptionType,
    Side,
    SourceDocument,
    Urgency,
)

PO_REQUIRED_ABOVE = Decimal("500.00")
CRITICAL_AMOUNT = Decimal("25000.00")
HIGH_AMOUNT = Decimal("10000.00")


def _side(doc: SourceDocument, catalog: Catalog) -> Side:
    if doc.kind is DocKind.REMITTANCE:
        return Side.AR
    if doc.kind is DocKind.CUSTOMER_INVOICE:
        return Side.AR
    if doc.kind is DocKind.VENDOR_INVOICE:
        return Side.AP
    # Credit memo: infer from counterparty master, default AP.
    if known_counterparty(doc.counterparty, catalog):
        needle = doc.counterparty
        if any(
            _norm_eq(needle, name) for name in catalog.customers
        ):
            return Side.AR
    return Side.AP


def _norm_eq(left: str, right: str) -> bool:
    from apar_router.catalog import normalize_name

    return normalize_name(left) == normalize_name(right)


def _days_past_due(doc: SourceDocument, as_of: date) -> int | None:
    if doc.kind is DocKind.REMITTANCE or doc.due_date is None:
        return None
    return (as_of - doc.due_date).days


def _duplicate_numbers(docs: list[SourceDocument]) -> set[str]:
    counts = Counter(
        doc.invoice_number
        for doc in docs
        if doc.kind is not DocKind.REMITTANCE and doc.invoice_number
    )
    return {number for number, count in counts.items() if count > 1}


def _open_invoices(docs: list[SourceDocument]) -> dict[str, SourceDocument]:
    mapping: dict[str, SourceDocument] = {}
    for doc in docs:
        if doc.kind is DocKind.REMITTANCE or not doc.invoice_number:
            continue
        mapping.setdefault(doc.invoice_number, doc)
    return mapping


def _collect_flags(
    doc: SourceDocument,
    catalog: Catalog,
    as_of: date,
    duplicates: set[str],
    open_invoices: dict[str, SourceDocument],
) -> tuple[list[ExceptionType], list[str], str, str]:
    flags: list[ExceptionType] = []
    notes: list[str] = []

    entity = resolve_entity(doc.entity_hint, catalog)
    if entity is None:
        flags.append(ExceptionType.ENTITY_AMBIGUOUS)
        notes.append(
            "Entity hint did not resolve to a known legal entity; park for review."
        )
        entity_id = ""
        entity_name = doc.entity_hint or "(blank)"
    else:
        entity_id = entity.id
        entity_name = entity.legal_name

    if not known_counterparty(doc.counterparty, catalog):
        flags.append(ExceptionType.UNKNOWN_COUNTERPARTY)
        notes.append(f"Counterparty {doc.counterparty!r} is not on the vendor/customer master.")

    if doc.kind is not DocKind.REMITTANCE and doc.invoice_number in duplicates:
        flags.append(ExceptionType.DUPLICATE_INVOICE)
        notes.append(f"Invoice number {doc.invoice_number} appears more than once in the intake batch.")

    if (
        doc.kind is DocKind.VENDOR_INVOICE
        and doc.amount >= PO_REQUIRED_ABOVE
        and not doc.po_number
    ):
        flags.append(ExceptionType.MISSING_PO)
        notes.append(f"AP invoice {doc.amount} USD is above ${PO_REQUIRED_ABOVE} and has no PO.")

    if doc.kind is DocKind.REMITTANCE:
        invoice_ref = doc.applied_invoice or doc.invoice_number
        if not invoice_ref:
            flags.append(ExceptionType.MISSING_REMIT_ADVICE)
            notes.append("Remittance has no invoice reference to apply against.")
        else:
            matched = open_invoices.get(invoice_ref)
            if matched is None:
                flags.append(ExceptionType.UNALLOCATED_REMITTANCE)
                notes.append(f"No open invoice {invoice_ref} in this batch to apply cash against.")
            else:
                target = doc.applied_amount if doc.applied_amount is not None else doc.amount
                if doc.applied_amount is not None and doc.applied_amount != doc.amount:
                    flags.append(ExceptionType.AMOUNT_VARIANCE)
                    notes.append(
                        f"Remittance total {doc.amount} does not equal applied amount {doc.applied_amount}."
                    )
                elif target < matched.amount:
                    flags.append(ExceptionType.SHORT_PAY)
                    notes.append(f"Short pay: applied {target} against invoice {matched.amount}.")
                elif target > matched.amount:
                    flags.append(ExceptionType.OVERPAYMENT)
                    notes.append(f"Overpay: applied {target} against invoice {matched.amount}.")
                else:
                    notes.append(f"Cash matches open invoice {invoice_ref} at {matched.amount}.")

    days = _days_past_due(doc, as_of)
    if days is not None and days > 0:
        flags.append(ExceptionType.PAST_DUE)
        notes.append(f"Due date {doc.due_date.isoformat()} is {days} day(s) past as-of {as_of.isoformat()}.")

    if not flags:
        flags.append(ExceptionType.NONE)
        if not notes:
            notes.append("No intake exceptions; ready for the standard queue.")

    return flags, notes, entity_id, entity_name


def _primary_exception(flags: list[ExceptionType]) -> ExceptionType:
    rank = {item: index for index, item in enumerate(EXCEPTION_PRIORITY)}
    return sorted(flags, key=lambda flag: rank[flag])[0]


def _urgency(
    doc: SourceDocument,
    exception: ExceptionType,
    as_of: date,
) -> Urgency:
    days = _days_past_due(doc, as_of)
    if days is not None and days > 30:
        return Urgency.CRITICAL
    if exception is ExceptionType.DUPLICATE_INVOICE and doc.amount >= HIGH_AMOUNT:
        return Urgency.CRITICAL
    if exception is ExceptionType.ENTITY_AMBIGUOUS and doc.amount >= HIGH_AMOUNT:
        return Urgency.CRITICAL
    if doc.amount >= CRITICAL_AMOUNT and exception is not ExceptionType.NONE:
        return Urgency.CRITICAL

    if days is not None and days > 0:
        return Urgency.HIGH
    if days is not None and days >= -3 and exception is not ExceptionType.NONE:
        return Urgency.HIGH
    if exception in {
        ExceptionType.SHORT_PAY,
        ExceptionType.OVERPAYMENT,
        ExceptionType.AMOUNT_VARIANCE,
        ExceptionType.UNKNOWN_COUNTERPARTY,
        ExceptionType.UNALLOCATED_REMITTANCE,
        ExceptionType.MISSING_REMIT_ADVICE,
        ExceptionType.ENTITY_AMBIGUOUS,
        ExceptionType.DUPLICATE_INVOICE,
    }:
        return Urgency.HIGH
    if exception is ExceptionType.MISSING_PO and doc.amount >= HIGH_AMOUNT:
        return Urgency.HIGH

    if doc.kind is DocKind.CREDIT_MEMO:
        return Urgency.LOW
    if days is not None and days < -45:
        return Urgency.LOW
    return Urgency.NORMAL


def classify_documents(
    docs: list[SourceDocument],
    catalog: Catalog,
    as_of: date,
) -> list[tuple[SourceDocument, Classification]]:
    duplicates = _duplicate_numbers(docs)
    open_invoices = _open_invoices(docs)
    classified: list[tuple[SourceDocument, Classification]] = []
    for doc in docs:
        flags, notes, entity_id, entity_name = _collect_flags(
            doc, catalog, as_of, duplicates, open_invoices
        )
        exception = _primary_exception(flags)
        classified.append(
            (
                doc,
                Classification(
                    side=_side(doc, catalog),
                    entity_id=entity_id,
                    entity_name=entity_name,
                    urgency=_urgency(doc, exception, as_of),
                    exception_type=exception,
                    flags=flags,
                    notes=notes,
                ),
            )
        )
    return classified


def max_urgency(*values: Urgency) -> Urgency:
    return max(values, key=lambda item: URGENCY_RANK[item])
