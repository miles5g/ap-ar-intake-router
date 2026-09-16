"""Render a markdown triage report from routed items."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from apar_router.journal import journal_totals
from apar_router.models import (
    QUEUE_ORDER,
    BillControlRow,
    Journal,
    PipelineResult,
    Queue,
    TriageItem,
    Urgency,
)

_REPO_ROOT = Path(__file__).resolve().parent.parent


def format_output_label(output_dir: Path | None, *, suffix: str = "journals/") -> str:
    """Repo-relative label so the live demo matches README `output/`."""
    if output_dir is None:
        base = "output"
    else:
        path = Path(output_dir).resolve()
        try:
            base = path.relative_to(_REPO_ROOT).as_posix()
        except ValueError:
            try:
                base = path.relative_to(Path.cwd().resolve()).as_posix()
            except ValueError:
                base = str(path)
    base = base.rstrip("/")
    if suffix:
        return f"{base}/{suffix.lstrip('/')}"
    return f"{base}/"


def _money(amount: Decimal) -> str:
    return f"${amount:,.2f}"


def _hot_count(items: list[TriageItem]) -> int:
    return sum(
        1
        for item in items
        if item.classification.urgency in {Urgency.CRITICAL, Urgency.HIGH}
    )


def render_report(
    result: PipelineResult,
    generated_at: datetime | None = None,
    journals: list[Journal] | None = None,
    bill_control: list[BillControlRow] | None = None,
    output_dir: Path | None = None,
) -> str:
    generated = generated_at or datetime.now(timezone.utc)
    items = result.items
    total = sum((item.document.amount for item in items), Decimal("0.00"))

    by_queue: dict[Queue, list[TriageItem]] = defaultdict(list)
    for item in items:
        by_queue[item.routing.queue].append(item)

    by_exception: dict[str, list[TriageItem]] = defaultdict(list)
    for item in items:
        by_exception[item.classification.exception_type.value].append(item)

    by_entity: dict[str, list[TriageItem]] = defaultdict(list)
    for item in items:
        by_entity[item.classification.entity_name].append(item)

    lines: list[str] = [
        "# AP/AR Intake Triage Report",
        "",
        f"**Generated:** {generated.strftime('%Y-%m-%d %H:%M UTC')}",
        f"**As-of date:** {result.as_of.isoformat()}",
        f"**Source:** {result.source_label}",
        f"**Documents:** {len(items)} ingested · {len(items)} routed · {_money(total)} face value",
        "",
        "> Portfolio demo — fictional entities and amounts only. Not production software.",
        "",
        "## Queue summary",
        "",
        "| Queue | Count | Face value | Critical/High |",
        "| --- | ---: | ---: | ---: |",
    ]

    for queue in QUEUE_ORDER:
        bucket = by_queue.get(queue) or []
        if not bucket:
            continue
        face = sum((item.document.amount for item in bucket), Decimal("0.00"))
        lines.append(
            f"| `{queue.value}` | {len(bucket)} | {_money(face)} | {_hot_count(bucket)} |"
        )

    lines.extend(
        [
            "",
            "## Exception mix",
            "",
            "| Exception | Count | Face value |",
            "| --- | ---: | ---: |",
        ]
    )
    for name, bucket in sorted(by_exception.items(), key=lambda pair: (-len(pair[1]), pair[0])):
        face = sum((item.document.amount for item in bucket), Decimal("0.00"))
        lines.append(f"| `{name}` | {len(bucket)} | {_money(face)} |")

    lines.extend(
        [
            "",
            "## By entity",
            "",
            "| Entity | Docs | AP | AR | Exceptions |",
            "| --- | ---: | ---: | ---: | ---: |",
        ]
    )
    for name, bucket in sorted(by_entity.items()):
        ap = sum(1 for item in bucket if item.classification.side.value == "AP")
        ar = len(bucket) - ap
        exceptions = sum(
            1 for item in bucket if item.classification.exception_type.value != "NONE"
        )
        lines.append(f"| {name} | {len(bucket)} | {ap} | {ar} | {exceptions} |")

    if journals:
        pack_label = format_output_label(output_dir)
        lines.extend(
            [
                "",
                "## Journal pack",
                "",
                f"Scrubbed dummy-GL journals ({len(journals)}) written under `{pack_label}`.",
                "Whole dollars only. Each file is one entity + AP or AR side, with a single "
                "payable/receivable balancing row.",
                "",
                "| Journal | Entity | Side | Lines | Debit | Credit | Balanced |",
                "| --- | --- | --- | ---: | ---: | ---: | --- |",
            ]
        )
        for journal in journals:
            debit, credit = journal_totals(journal)
            lines.append(
                f"| `{journal.filename}` | {journal.entity_name} | {journal.side.value} | "
                f"{len(journal.lines)} | {_money(debit)} | {_money(credit)} | "
                f"{'yes' if debit == credit else 'NO'} |"
            )
        if bill_control:
            lines.extend(
                [
                    "",
                    "Bill control (recurring fictional vendors, including Acme Widgets and "
                    "Stark Supplies) is in `bill_control.csv`.",
                ]
            )

    lines.extend(["", "## Routed work", ""])

    for queue in QUEUE_ORDER:
        bucket = by_queue.get(queue) or []
        if not bucket:
            continue
        bucket = sorted(
            bucket,
            key=lambda item: (
                0 if item.classification.urgency is Urgency.CRITICAL else 1,
                0 if item.classification.urgency is Urgency.HIGH else 1,
                -item.document.amount,
                item.document.doc_id,
            ),
        )
        lines.append(f"### `{queue.value}`")
        lines.append("")
        lines.append(
            "| Doc | Side | Entity | Counterparty | Amount | Urgency | Exception | Reason | Why |"
        )
        lines.append("| --- | --- | --- | --- | ---: | --- | --- | --- | --- |")
        for item in bucket:
            doc = item.document
            clf = item.classification
            why = item.routing.rationale.replace("|", "/")
            lines.append(
                "| "
                + " | ".join(
                    [
                        f"`{doc.doc_id}`",
                        clf.side.value,
                        clf.entity_name,
                        doc.counterparty or "—",
                        _money(doc.amount),
                        clf.urgency.value,
                        f"`{clf.exception_type.value}`",
                        f"`{item.routing.reason_code}`",
                        why,
                    ]
                )
                + " |"
            )
        lines.append("")

    lines.extend(
        [
            "---",
            "",
            "Generated by `python3 -m apar_router`. Synthetic fixtures and dummy GLs only.",
            "",
        ]
    )
    return "\n".join(lines)
