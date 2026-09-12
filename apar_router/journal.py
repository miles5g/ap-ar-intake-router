"""Build per-entity scrubbed journals from routed AP/AR documents."""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from apar_router.coa import lookup_vendor_gl
from apar_router.models import (
    ChartOfAccounts,
    DocKind,
    ExceptionType,
    Journal,
    JournalLine,
    PipelineResult,
    Side,
    TriageItem,
)

JOURNAL_COLUMNS = ("GL Code", "Debit", "Credit", "Description")
ZERO = Decimal("0")


def whole_dollars(amount: Decimal) -> Decimal:
    """Round to a whole dollar. Demo journals never carry cents."""
    return amount.quantize(Decimal("1"), rounding=ROUND_HALF_UP)


def format_description(when: date, counterparty: str, document_ref: str) -> str:
    vendor = (counterparty or "Unknown").strip()
    ref = (document_ref or "NO-REF").strip()
    return f"{when.strftime('%m/%d/%y')} - {vendor}/{ref}"


def _signed_amount(item: TriageItem) -> Decimal:
    amount = whole_dollars(item.document.amount)
    if item.document.kind is DocKind.CREDIT_MEMO:
        return -amount
    if item.document.kind is DocKind.CUSTOMER_INVOICE:
        return -amount
    return amount


def _activity_gl(item: TriageItem, coa: ChartOfAccounts) -> str:
    if item.classification.side is Side.AR:
        return coa.customer_gl
    return lookup_vendor_gl(item.document.counterparty, coa)


def _control_gl(side: Side, coa: ChartOfAccounts) -> str:
    key = "AP" if side is Side.AP else "AR"
    return coa.control_accounts[key]


def _control_label(side: Side) -> str:
    return "Accounts Payable" if side is Side.AP else "Accounts Receivable"


def _slug(entity_id: str, side: Side) -> str:
    token = entity_id or "UNRESOLVED"
    return f"{token}_{side.value}.csv"


def journalable_items(items: list[TriageItem]) -> list[TriageItem]:
    """Invoice/credit rows with a resolved entity. First of each invoice number wins."""
    seen: set[str] = set()
    selected: list[TriageItem] = []
    for item in items:
        doc = item.document
        if doc.kind is DocKind.REMITTANCE:
            continue
        if item.classification.exception_type is ExceptionType.ENTITY_AMBIGUOUS:
            continue
        if not item.classification.entity_id:
            continue
        if doc.invoice_number:
            if doc.invoice_number in seen:
                continue
            seen.add(doc.invoice_number)
        selected.append(item)
    return selected


def _activity_line(item: TriageItem, coa: ChartOfAccounts) -> JournalLine:
    signed = _signed_amount(item)
    if signed >= ZERO:
        debit, credit = signed, ZERO
    else:
        debit, credit = ZERO, -signed
    ref = item.document.invoice_number or item.document.doc_id
    return JournalLine(
        gl_code=_activity_gl(item, coa),
        debit=debit,
        credit=credit,
        description=format_description(
            item.document.doc_date, item.document.counterparty, ref
        ),
    )


def _balancing_line(
    side: Side,
    net_debit: Decimal,
    as_of: date,
    coa: ChartOfAccounts,
) -> JournalLine | None:
    if net_debit == ZERO:
        return None
    if net_debit > ZERO:
        debit, credit = ZERO, net_debit
    else:
        debit, credit = -net_debit, ZERO
    return JournalLine(
        gl_code=_control_gl(side, coa),
        debit=debit,
        credit=credit,
        description=f"{as_of.strftime('%m/%d/%y')} - {_control_label(side)}",
    )


def build_journals(result: PipelineResult, coa: ChartOfAccounts) -> list[Journal]:
    grouped: dict[tuple[str, str, Side], list[TriageItem]] = defaultdict(list)
    for item in journalable_items(result.items):
        key = (
            item.classification.entity_id,
            item.classification.entity_name,
            item.classification.side,
        )
        grouped[key].append(item)

    journals: list[Journal] = []
    for (entity_id, entity_name, side), bucket in sorted(
        grouped.items(), key=lambda pair: (pair[0][0], pair[0][2].value)
    ):
        bucket.sort(key=lambda item: (item.document.doc_date, item.document.doc_id))
        lines = [_activity_line(item, coa) for item in bucket]
        net = sum((line.debit - line.credit for line in lines), ZERO)
        balancing = _balancing_line(side, net, result.as_of, coa)
        if balancing is not None:
            lines.append(balancing)
        journals.append(
            Journal(
                entity_id=entity_id,
                entity_name=entity_name,
                side=side,
                lines=lines,
                filename=_slug(entity_id, side),
            )
        )
    return journals


def journal_totals(journal: Journal) -> tuple[Decimal, Decimal]:
    debit = sum((line.debit for line in journal.lines), ZERO)
    credit = sum((line.credit for line in journal.lines), ZERO)
    return whole_dollars(debit), whole_dollars(credit)
