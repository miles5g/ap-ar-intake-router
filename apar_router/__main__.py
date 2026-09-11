"""CLI: python -m apar_router"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from apar_router.pipeline import DEFAULT_FIXTURES, run_and_render


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m apar_router",
        description=(
            "Ingest synthetic multi-entity invoices/remittances, classify them, "
            "route to queues, and print a markdown triage report."
        ),
    )
    parser.add_argument(
        "--fixtures",
        type=Path,
        default=DEFAULT_FIXTURES,
        help="Directory with entities.json, invoices.csv, remittances.json",
    )
    parser.add_argument(
        "--as-of",
        dest="as_of",
        default="2026-09-11",
        help="Triage as-of date (YYYY-MM-DD). Default: 2026-09-11",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Optional path to write the markdown report (still printed to stdout).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    as_of = date.fromisoformat(args.as_of)
    report = run_and_render(fixtures_dir=args.fixtures, as_of=as_of)
    sys.stdout.write(report)
    if not report.endswith("\n"):
        sys.stdout.write("\n")
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(report if report.endswith("\n") else report + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
