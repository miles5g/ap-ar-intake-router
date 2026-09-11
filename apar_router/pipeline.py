"""End-to-end ingest → classify → route pipeline."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from apar_router.catalog import load_catalog
from apar_router.classify import classify_documents
from apar_router.ingest import load_documents
from apar_router.models import PipelineResult
from apar_router.report import render_report
from apar_router.route import build_triage

PACKAGE_ROOT = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE_ROOT.parent
DEFAULT_FIXTURES = REPO_ROOT / "fixtures"


def run_pipeline(
    fixtures_dir: Path | None = None,
    as_of: date | None = None,
) -> PipelineResult:
    fixtures = Path(fixtures_dir) if fixtures_dir else DEFAULT_FIXTURES
    catalog = load_catalog(fixtures / "entities.json")
    documents = load_documents(fixtures)
    classified = classify_documents(documents, catalog, as_of or date.today())
    items = build_triage(classified)
    try:
        source = str(fixtures.relative_to(REPO_ROOT))
    except ValueError:
        source = str(fixtures)
    return PipelineResult(
        as_of=as_of or date.today(),
        items=items,
        source_label=f"{source}/ (synthetic)",
    )


def run_and_render(
    fixtures_dir: Path | None = None,
    as_of: date | None = None,
) -> str:
    return render_report(run_pipeline(fixtures_dir=fixtures_dir, as_of=as_of))
