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
        "SYNTHETIC DEMO — fictional entities, dummy D-#### GLs. Not production.",
        "You're seeing a portfolio AP/AR router: fixtures in, queues + journals out.",
        "Talk track: Recruiter-safe pattern. No live books, no employer SOP.",
    ]


def ingest_lines(*, documents: Sequence[SourceDocument], **_: object) -> list[str]:
    remits = sum(1 for doc in documents if doc.kind is DocKind.REMITTANCE)
    invoices = len(documents) - remits
    return [
        "INGEST — synthetic CSV invoices/credits + JSON remittances.",
        f"You're seeing {len(documents)} docs: {invoices} invoice/credit rows + {remits} remittances.",
        "Talk track: Normalize intake first; classify once the shapes are boring.",
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
        "CLASSIFY — AP vs AR, entity, urgency, one winning exception per doc.",
        f"You're seeing {ap} AP / {ar} AR, {flagged} flagged (dupes, short-pays, blank entity).",
        "Talk track: Deterministic rules you can defend — not a model.",
    ]


def route_lines(*, items: Sequence[TriageItem], **_: object) -> list[str]:
    queues = Counter(item.routing.queue for item in items)
    urgent = queues.get(Queue.URGENT_ESCALATION, 0)
    return [
        "ROUTE — queue + RC-* reason code, hottest work first.",
        f"You're seeing {urgent} urgent escalations, {len(queues)} queues, {len(items)} routed items.",
        "Talk track: Show the exception pile; clean AP/AR can wait in process queues.",
    ]


def report_lines(**_: object) -> list[str]:
    return [
        "REPORT — markdown: queues, exceptions, entities, routed work.",
        "You're seeing a controller-style packet — still fully synthetic names.",
        "Talk track: If they only read one screen, this is the screen.",
    ]


def journals_lines(
    *,
    journals: Sequence[Journal] | None = None,
    **_: object,
) -> list[str]:
    count = len(journals or ())
    return [
        "JOURNALS — dummy-GL CSVs + bill-control for recurring fictional vendors.",
        f"You're seeing {count} balanced packs under output/journals/ (whole dollars).",
        "Talk track: Intake that emits a scrubbed pack — not an ERP post.",
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
