"""Domain types for the synthetic AP/AR intake router."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Optional


class DocKind(str, Enum):
    VENDOR_INVOICE = "vendor_invoice"
    CUSTOMER_INVOICE = "customer_invoice"
    CREDIT_MEMO = "credit_memo"
    REMITTANCE = "remittance"


class Side(str, Enum):
    AP = "AP"
    AR = "AR"


class Urgency(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    NORMAL = "NORMAL"
    LOW = "LOW"


class ExceptionType(str, Enum):
    NONE = "NONE"
    DUPLICATE_INVOICE = "DUPLICATE_INVOICE"
    MISSING_PO = "MISSING_PO"
    AMOUNT_VARIANCE = "AMOUNT_VARIANCE"
    UNKNOWN_COUNTERPARTY = "UNKNOWN_COUNTERPARTY"
    ENTITY_AMBIGUOUS = "ENTITY_AMBIGUOUS"
    UNALLOCATED_REMITTANCE = "UNALLOCATED_REMITTANCE"
    SHORT_PAY = "SHORT_PAY"
    OVERPAYMENT = "OVERPAYMENT"
    PAST_DUE = "PAST_DUE"
    MISSING_REMIT_ADVICE = "MISSING_REMIT_ADVICE"


class Queue(str, Enum):
    URGENT_ESCALATION = "URGENT_ESCALATION"
    ENTITY_REVIEW = "ENTITY_REVIEW"
    AP_EXCEPTION = "AP_EXCEPTION"
    AP_PROCESS = "AP_PROCESS"
    AR_UNAPPLIED_CASH = "AR_UNAPPLIED_CASH"
    AR_CASH_APPLICATION = "AR_CASH_APPLICATION"
    AR_COLLECTIONS = "AR_COLLECTIONS"
    AR_OPEN_ITEMS = "AR_OPEN_ITEMS"


# Display order for the triage report (hottest work first).
QUEUE_ORDER = (
    Queue.URGENT_ESCALATION,
    Queue.ENTITY_REVIEW,
    Queue.AP_EXCEPTION,
    Queue.AR_UNAPPLIED_CASH,
    Queue.AR_COLLECTIONS,
    Queue.AP_PROCESS,
    Queue.AR_CASH_APPLICATION,
    Queue.AR_OPEN_ITEMS,
)

# Highest-signal exception wins when several apply.
EXCEPTION_PRIORITY = (
    ExceptionType.ENTITY_AMBIGUOUS,
    ExceptionType.DUPLICATE_INVOICE,
    ExceptionType.UNKNOWN_COUNTERPARTY,
    ExceptionType.UNALLOCATED_REMITTANCE,
    ExceptionType.MISSING_REMIT_ADVICE,
    ExceptionType.SHORT_PAY,
    ExceptionType.OVERPAYMENT,
    ExceptionType.AMOUNT_VARIANCE,
    ExceptionType.MISSING_PO,
    ExceptionType.PAST_DUE,
    ExceptionType.NONE,
)

URGENCY_RANK = {
    Urgency.CRITICAL: 3,
    Urgency.HIGH: 2,
    Urgency.NORMAL: 1,
    Urgency.LOW: 0,
}


@dataclass(frozen=True)
class Entity:
    id: str
    legal_name: str
    aliases: tuple[str, ...]
    role: str


@dataclass(frozen=True)
class Catalog:
    entities: tuple[Entity, ...]
    vendors: frozenset[str]
    customers: frozenset[str]


@dataclass
class SourceDocument:
    doc_id: str
    kind: DocKind
    entity_hint: str
    counterparty: str
    invoice_number: str
    amount: Decimal
    currency: str
    doc_date: date
    due_date: Optional[date]
    po_number: str
    description: str
    payment_ref: str = ""
    applied_invoice: str = ""
    applied_amount: Optional[Decimal] = None


@dataclass
class Classification:
    side: Side
    entity_id: str
    entity_name: str
    urgency: Urgency
    exception_type: ExceptionType
    flags: list[ExceptionType] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass
class Routing:
    queue: Queue
    reason_code: str
    rationale: str


@dataclass
class TriageItem:
    document: SourceDocument
    classification: Classification
    routing: Routing


@dataclass
class PipelineResult:
    as_of: date
    items: list[TriageItem]
    source_label: str
