"""Refuse fixtures or generated text that look like production leakage."""

from __future__ import annotations

import json
from typing import Any

# Real-firm / production tells this demo must never emit.
FORBIDDEN_TOKENS = (
    "gursey",
    "kpmg",
    "deloitte",
    "ey.com",
    "pwc",
    "pricewaterhouse",
    "ernst & young",
    "grant thornton",
    "@gmail.com",
    "@yahoo.com",
    "@outlook.com",
    "@hotmail.com",
)


class SafetyError(ValueError):
    """Raised when synthetic-only guarantees would be violated."""


def scan_text(text: str, *, source: str) -> None:
    lowered = text.lower()
    hits = [token for token in FORBIDDEN_TOKENS if token in lowered]
    if hits:
        raise SafetyError(
            f"{source} contains forbidden production tokens: {', '.join(hits)}. "
            "This demo is synthetic-only."
        )


def scan_payload(payload: Any, *, source: str) -> None:
    scan_text(json.dumps(payload, default=str), source=source)
