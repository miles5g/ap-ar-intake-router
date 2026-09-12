"""Synthetic multi-entity AP/AR intake → classify → route → journal pack demo."""

from apar_router.pipeline import run_and_export, run_and_render, run_pipeline

__all__ = ["run_pipeline", "run_and_render", "run_and_export"]
__version__ = "0.2.0"
