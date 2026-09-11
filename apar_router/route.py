"""Route classified documents to queues with reason codes."""

from __future__ import annotations

from apar_router.models import (
    Classification,
    DocKind,
    ExceptionType,
    Queue,
    Routing,
    Side,
    SourceDocument,
    TriageItem,
    Urgency,
)

REASON_CODES = {
    ExceptionType.NONE: {
        Side.AP: ("RC-CLEAN-AP", "Clean AP document — standard process queue."),
        Side.AR: ("RC-CLEAN-AR", "Clean AR document — standard open-item / cash-app path."),
    },
    ExceptionType.DUPLICATE_INVOICE: (
        "RC-DUP-INV",
        "Possible duplicate invoice number in the same intake batch.",
    ),
    ExceptionType.MISSING_PO: (
        "RC-PO-MISSING",
        "AP invoice exceeds the PO threshold and has no purchase order.",
    ),
    ExceptionType.AMOUNT_VARIANCE: (
        "RC-AMT-VAR",
        "Remittance total and applied amount disagree.",
    ),
    ExceptionType.UNKNOWN_COUNTERPARTY: (
        "RC-UNKNOWN-CPTY",
        "Counterparty is not on the synthetic vendor/customer master.",
    ),
    ExceptionType.ENTITY_AMBIGUOUS: (
        "RC-ENTITY-AMBIG",
        "Could not resolve the document to a known legal entity.",
    ),
    ExceptionType.UNALLOCATED_REMITTANCE: (
        "RC-REMIT-UNALLOC",
        "Cash received with an invoice reference that does not match an open item.",
    ),
    ExceptionType.SHORT_PAY: (
        "RC-SHORT-PAY",
        "Customer remittance is short of the open invoice amount.",
    ),
    ExceptionType.OVERPAYMENT: (
        "RC-OVERPAY",
        "Customer remittance exceeds the open invoice amount.",
    ),
    ExceptionType.PAST_DUE: (
        "RC-PAST-DUE",
        "Document is past due as of the triage date.",
    ),
    ExceptionType.MISSING_REMIT_ADVICE: (
        "RC-REMIT-NO-ADVICE",
        "Remittance arrived without invoice-level application detail.",
    ),
}


def _reason(classification: Classification) -> tuple[str, str]:
    mapping = REASON_CODES[classification.exception_type]
    if isinstance(mapping, dict):
        return mapping[classification.side]
    return mapping


def _queue(doc: SourceDocument, classification: Classification) -> Queue:
    if classification.urgency is Urgency.CRITICAL:
        return Queue.URGENT_ESCALATION
    if classification.exception_type is ExceptionType.ENTITY_AMBIGUOUS:
        return Queue.ENTITY_REVIEW

    if classification.side is Side.AP:
        if classification.exception_type is ExceptionType.NONE:
            return Queue.AP_PROCESS
        return Queue.AP_EXCEPTION

    # AR
    if doc.kind is DocKind.REMITTANCE:
        if classification.exception_type is ExceptionType.NONE:
            return Queue.AR_CASH_APPLICATION
        return Queue.AR_UNAPPLIED_CASH

    if classification.exception_type is ExceptionType.PAST_DUE:
        return Queue.AR_COLLECTIONS
    if classification.exception_type is ExceptionType.NONE:
        return Queue.AR_OPEN_ITEMS
    return Queue.AR_COLLECTIONS


def route_item(doc: SourceDocument, classification: Classification) -> Routing:
    queue = _queue(doc, classification)
    code, rationale = _reason(classification)
    if queue is Queue.URGENT_ESCALATION and classification.exception_type is not ExceptionType.NONE:
        code = "RC-ESCALATE"
        rationale = f"Critical urgency — {rationale}"
    return Routing(queue=queue, reason_code=code, rationale=rationale)


def build_triage(
    classified: list[tuple[SourceDocument, Classification]],
) -> list[TriageItem]:
    return [
        TriageItem(document=doc, classification=clf, routing=route_item(doc, clf))
        for doc, clf in classified
    ]
