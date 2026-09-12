"""End-to-end ingest → classify → route → journal pack pipeline."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from apar_router.bill_control import build_bill_control
from apar_router.catalog import load_catalog
from apar_router.classify import classify_documents
from apar_router.coa import load_coa
from apar_router.export import write_pack
from apar_router.ingest import load_documents
from apar_router.journal import build_journals
from apar_router.models import BillControlRow, Journal, PipelineResult
from apar_router.report import render_report
from apar_router.route import build_triage
from apar_router.safety import scan_text

PACKAGE_ROOT = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE_ROOT.parent
DEFAULT_FIXTURES = REPO_ROOT / "fixtures"
DEFAULT_OUTPUT = REPO_ROOT / "output"


def _source_label(fixtures: Path) -> str:
    try:
        source = str(fixtures.relative_to(REPO_ROOT))
    except ValueError:
        source = str(fixtures)
    return f"{source}/ (synthetic)"


def run_pipeline(
    fixtures_dir: Path | None = None,
    as_of: date | None = None,
) -> PipelineResult:
    fixtures = Path(fixtures_dir) if fixtures_dir else DEFAULT_FIXTURES
    for name in (
        "entities.json",
        "invoices.csv",
        "remittances.json",
        "coa.json",
        "recurring_bills.csv",
    ):
        path = fixtures / name
        if path.is_file():
            scan_text(path.read_text(encoding="utf-8"), source=str(path))
    catalog = load_catalog(fixtures / "entities.json")
    documents = load_documents(fixtures)
    classified = classify_documents(documents, catalog, as_of or date.today())
    items = build_triage(classified)
    return PipelineResult(
        as_of=as_of or date.today(),
        items=items,
        source_label=_source_label(fixtures),
    )


def build_pack(
    result: PipelineResult,
    fixtures_dir: Path | None = None,
) -> tuple[list[Journal], list[BillControlRow]]:
    fixtures = Path(fixtures_dir) if fixtures_dir else DEFAULT_FIXTURES
    catalog = load_catalog(fixtures / "entities.json")
    coa = load_coa(fixtures / "coa.json")
    journals = build_journals(result, coa)
    bill_control = build_bill_control(
        result, catalog, fixtures / "recurring_bills.csv"
    )
    return journals, bill_control


def run_and_render(
    fixtures_dir: Path | None = None,
    as_of: date | None = None,
) -> str:
    result = run_pipeline(fixtures_dir=fixtures_dir, as_of=as_of)
    journals, bill_control = build_pack(result, fixtures_dir=fixtures_dir)
    return render_report(result, journals=journals, bill_control=bill_control)


def run_and_export(
    fixtures_dir: Path | None = None,
    as_of: date | None = None,
    output_dir: Path | None = None,
) -> tuple[str, list[Path]]:
    fixtures = Path(fixtures_dir) if fixtures_dir else DEFAULT_FIXTURES
    output = Path(output_dir) if output_dir else DEFAULT_OUTPUT
    result = run_pipeline(fixtures_dir=fixtures, as_of=as_of)
    journals, bill_control = build_pack(result, fixtures_dir=fixtures)
    report = render_report(
        result,
        journals=journals,
        bill_control=bill_control,
        output_dir=output,
    )
    written = write_pack(output, report, journals, bill_control)
    return report, written
