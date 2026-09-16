"""Interview-mode stage banners for the synthetic AP/AR CLI demo."""

from __future__ import annotations

import sys
from collections import Counter
from collections.abc import Sequence
from typing import TextIO

from apar_router.models import (
    Classification,
    DocKind,
    ExceptionType,
    Journal,
    Queue,
    Side,
    SourceDocument,
    TriageItem,
)

BOX_WIDTH = 80


def wrap_line(text: str, width: int) -> list[str]:
    words = text.split()
    if not words:
        return [""]
    rows: list[str] = []
    current = words[0]
    for word in words[1:]:
        trial = f"{current} {word}"
        if len(trial) <= width:
            current = trial
        else:
            rows.append(current)
            current = word
    rows.append(current)
    return rows


def render_box(lines: Sequence[str], width: int = BOX_WIDTH) -> str:
    """ASCII box with 2–4 short content lines (wrapping if a line runs long)."""
    inner = width - 2
    body_width = inner - 2
    body: list[str] = []
    for line in lines:
        body.extend(wrap_line(line.strip(), body_width))
    rule = "+" + "-" * inner + "+"
    padded = ["| " + row.ljust(body_width) + " |" for row in body]
    return "\n".join([rule, *padded, rule])


def intro_lines() -> list[str]:
    return [
        "SYNTHETIC DEMO — fake companies, dummy D-#### GLs. Not real books.",
        "This is me walking a batch from invoices in to a journal pack.",
        "Talk track: All fake data. No live books, no employer SOP.",
    ]


def ingest_lines(*, documents: Sequence[SourceDocument], **_: object) -> list[str]:
    remits = sum(1 for doc in documents if doc.kind is DocKind.REMITTANCE)
    invoices = len(documents) - remits
    return [
        "INGEST — fake invoices/credits from a CSV, remittances from JSON.",
        f"That's {len(documents)} docs: {invoices} invoice/credit rows and {remits} remittances.",
        "Talk track: I'm just loading the pile so we can look at it.",
    ]


def classify_lines(
    *,
    classified: Sequence[tuple[SourceDocument, Classification]],
    **_: object,
) -> list[str]:
    ap = sum(1 for _, clf in classified if clf.side is Side.AP)
    ar = len(classified) - ap
    flagged = sum(
        1 for _, clf in classified if clf.exception_type is not ExceptionType.NONE
    )
    return [
        "CLASSIFY — AP vs AR, which company, and did anything look off.",
        f"That's {ap} AP / {ar} AR, {flagged} with a flag (dupes, short-pays, blank entity).",
        "Talk track: I'm tagging the messy ones as I go.",
    ]


def route_lines(*, items: Sequence[TriageItem], **_: object) -> list[str]:
    queues = Counter(item.routing.queue for item in items)
    urgent = queues.get(Queue.URGENT_ESCALATION, 0)
    return [
        "ROUTE — each doc gets a queue and a short reason code.",
        f"That's {urgent} that need a person now, {len(items)} items in {len(queues)} queues.",
        "Talk track: I'm sorting what needs a human vs what can wait.",
    ]


def report_lines(**_: object) -> list[str]:
    return [
        "REPORT — queues, exceptions, entities, the whole list.",
        "Same fake names as the fixtures. Nothing fancy.",
        "Talk track: This is the summary screen.",
    ]


def journals_lines(
    *,
    journals: Sequence[Journal] | None = None,
    **_: object,
) -> list[str]:
    count = len(journals or ())
    return [
        "JOURNALS — dummy-GL CSVs plus a little recurring-bill list.",
        f"That's {count} balanced files under output/journals/.",
        "Talk track: Journals balance — still not a real post.",
    ]


_STAGE_LINES = {
    "ingest": ingest_lines,
    "classify": classify_lines,
    "route": route_lines,
    "report": report_lines,
    "journals": journals_lines,
}


class Walkthrough:
    """Print boxed stage banners and optionally pause for Enter."""

    def __init__(
        self,
        *,
        pause: bool = True,
        stream: TextIO | None = None,
        stdin: TextIO | None = None,
    ) -> None:
        self.pause = pause
        self.stream = stream if stream is not None else sys.stderr
        self.stdin = stdin if stdin is not None else sys.stdin

    def intro(self) -> None:
        self._present(intro_lines())

    def on_stage(self, stage: str, **context: object) -> None:
        builder = _STAGE_LINES.get(stage)
        if builder is None:
            return
        self._present(builder(**context))

    def _present(self, lines: Sequence[str]) -> None:
        self.stream.write("\n" + render_box(lines) + "\n")
        self.stream.flush()
        if not self.pause:
            return
        self.stream.write("Press Enter to continue.\n")
        self.stream.flush()
        self.stdin.readline()
