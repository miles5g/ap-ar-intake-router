"""Load the fictional entity / counterparty catalog."""

from __future__ import annotations

import json
import re
from pathlib import Path

from apar_router.models import Catalog, Entity

_PUNCT = re.compile(r"[^\w\s]")
_SPACE = re.compile(r"\s+")


def normalize_name(value: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace."""
    cleaned = _PUNCT.sub(" ", (value or "").lower())
    return _SPACE.sub(" ", cleaned).strip()


def load_catalog(path: Path) -> Catalog:
    raw = json.loads(path.read_text(encoding="utf-8"))
    entities = tuple(
        Entity(
            id=row["id"],
            legal_name=row["legal_name"],
            aliases=tuple(row.get("aliases") or ()),
            role=row.get("role", "operating"),
        )
        for row in raw["entities"]
    )
    return Catalog(
        entities=entities,
        vendors=frozenset(raw.get("vendors") or ()),
        customers=frozenset(raw.get("customers") or ()),
    )


def resolve_entity(hint: str, catalog: Catalog) -> Entity | None:
    needle = normalize_name(hint)
    if not needle:
        return None
    for entity in catalog.entities:
        candidates = (entity.legal_name, entity.id, *entity.aliases)
        if any(normalize_name(c) == needle for c in candidates if c):
            return entity
        if any(needle in normalize_name(c) and len(needle) >= 4 for c in candidates if c):
            return entity
    return None


def known_counterparty(name: str, catalog: Catalog) -> bool:
    needle = normalize_name(name)
    pool = catalog.vendors | catalog.customers
    return any(normalize_name(item) == needle for item in pool)
