"""CLI: python3 -m apar_router"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from apar_router.export import write_pack
from apar_router.pipeline import (
    DEFAULT_FIXTURES,
    DEFAULT_OUTPUT,
    build_pack,
    run_and_export,
    run_pipeline,
)
from apar_router.report import format_output_label, render_report
from apar_router.walkthrough import Walkthrough


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python3 -m apar_router",
        description=(
            "Ingest synthetic multi-entity invoices/remittances, classify them, "
            "route to queues, print a markdown triage report, and write a "
            "scrubbed journal pack under output/."
        ),
    )
    parser.add_argument(
        "--fixtures",
        type=Path,
        default=DEFAULT_FIXTURES,
        help="Directory with entities.json, invoices.csv, remittances.json, coa.json",
    )
    parser.add_argument(
        "--as-of",
        dest="as_of",
        default="2026-09-11",
        help="Triage as-of date (YYYY-MM-DD). Default: 2026-09-11",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Directory for the journal pack (default: output/).",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Optional extra path to copy the markdown report (still printed to stdout).",
    )
    parser.add_argument(
        "-w",
        "--walkthrough",
        action="store_true",
        help=(
            "Walkthrough demo: boxed stage banners between ingest → classify → "
            "route → report → journals (pauses for Enter unless --no-pause)."
        ),
    )
    parser.add_argument(
        "--no-pause",
        action="store_true",
        help="With --walkthrough, skip Enter pauses (CI / non-interactive).",
    )
    return parser


def _write_stdout_report(report: str, extra: Path | None) -> None:
    sys.stdout.write(report)
    if not report.endswith("\n"):
        sys.stdout.write("\n")
    sys.stdout.flush()
    if extra:
        extra.parent.mkdir(parents=True, exist_ok=True)
        extra.write_text(
            report if report.endswith("\n") else report + "\n", encoding="utf-8"
        )


def _note_pack(written: list[Path], output_dir: Path) -> None:
    journal_count = sum(1 for path in written if path.parent.name == "journals")
    sys.stderr.write(
        "Wrote "
        f"{len(written)} pack files ({journal_count} journals) under "
        f"{format_output_label(output_dir, suffix='')}\n"
    )


def _run_walkthrough(args: argparse.Namespace, as_of: date) -> tuple[str, list[Path]]:
    guide = Walkthrough(
        pause=not args.no_pause,
        stream=sys.stderr,
        stdin=sys.stdin,
    )
    guide.intro()
    result = run_pipeline(
        fixtures_dir=args.fixtures,
        as_of=as_of,
        on_stage=guide.on_stage,
    )
    journals, bill_control = build_pack(result, fixtures_dir=args.fixtures)
    report = render_report(
        result,
        journals=journals,
        bill_control=bill_control,
        output_dir=args.output_dir,
    )
    guide.on_stage("report", result=result, journals=journals)
    _write_stdout_report(report, args.output)
    guide.on_stage(
        "journals",
        journals=journals,
        output_dir=args.output_dir,
    )
    written = write_pack(args.output_dir, report, journals, bill_control)
    return report, written


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    as_of = date.fromisoformat(args.as_of)
    if args.walkthrough:
        _, written = _run_walkthrough(args, as_of)
    else:
        report, written = run_and_export(
            fixtures_dir=args.fixtures,
            as_of=as_of,
            output_dir=args.output_dir,
        )
        _write_stdout_report(report, args.output)
    _note_pack(written, args.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
