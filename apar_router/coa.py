"""Load the dummy chart of accounts."""

from __future__ import annotations

import json
from pathlib import Path

from apar_router.catalog import normalize_name
from apar_router.models import ChartOfAccounts, GlAccount
from apar_router.safety import scan_payload


DUMMY_PREFIX = "D-"


class CoaError(ValueError):
    """Raised when the dummy COA is missing or not dummy-prefixed."""


def load_coa(path: Path) -> ChartOfAccounts:
    raw = json.loads(path.read_text(encoding="utf-8"))
    scan_payload(raw, source=str(path))
    accounts = tuple(
        GlAccount(
            code=str(row["code"]).strip(),
            name=str(row["name"]).strip(),
            type=str(row.get("type") or "expense").strip(),
        )
        for row in raw["accounts"]
    )
    if not accounts:
        raise CoaError(f"{path} has no accounts")
    for account in accounts:
        if not account.code.startswith(DUMMY_PREFIX):
            raise CoaError(
                f"GL {account.code!r} is not dummy-prefixed ({DUMMY_PREFIX}). "
                "This demo only ships fictional GLs."
            )
    control = {str(k): str(v) for k, v in (raw.get("control_accounts") or {}).items()}
    vendor_gl = {str(k): str(v) for k, v in (raw.get("vendor_gl") or {}).items()}
    customer_gl = str(raw.get("customer_gl") or "D-4000")
    fallback = str(raw.get("fallback_expense_gl") or "D-6600")
    known = {account.code for account in accounts}
    for code in (*control.values(), *vendor_gl.values(), customer_gl, fallback):
        if code not in known:
            raise CoaError(f"COA maps to unknown dummy GL {code!r}")
    return ChartOfAccounts(
        accounts=accounts,
        control_accounts=control,
        vendor_gl=vendor_gl,
        customer_gl=customer_gl,
        fallback_expense_gl=fallback,
    )


def lookup_vendor_gl(counterparty: str, coa: ChartOfAccounts) -> str:
    needle = normalize_name(counterparty)
    for name, code in coa.vendor_gl.items():
        if normalize_name(name) == needle:
            return code
    return coa.fallback_expense_gl
