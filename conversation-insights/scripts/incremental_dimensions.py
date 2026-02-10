#!/usr/bin/env python3
"""Shared dimension contracts for IncrementalMechanismV1 reports."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Tuple

# Ordered from foundational diagnosis to higher-level intervention planning.
_DIMENSION_LAYER_PAIRS: Tuple[Tuple[str, str], ...] = (
    ("incremental-trigger-chains", "L2"),
    ("incremental-first-pass-diagnostics", "L2"),
    ("incremental-coverage-gap", "L2"),
    ("incremental-task-stratification", "L2"),
    ("incremental-root-causes", "L3"),
    ("incremental-change-delta", "L3"),
    ("incremental-interventions", "L3"),
    ("incremental-intervention-impact", "L3"),
    ("incremental-validation-loop", "L3"),
    ("incremental-reuse-assets", "L3"),
    ("incremental-compounding", "L3"),
)

DIMENSION_LAYER_MAP: Dict[str, str] = dict(_DIMENSION_LAYER_PAIRS)
DIMENSION_ORDER_INDEX: Dict[str, int] = {
    dimension: index
    for index, (dimension, _) in enumerate(_DIMENSION_LAYER_PAIRS)
}
SUPPORTED_INCREMENTAL_DIMENSIONS: Tuple[str, ...] = tuple(DIMENSION_LAYER_MAP.keys())


def expected_layer_for_dimension(dimension: str) -> str | None:
    """Return expected layer (L2/L3) for a dimension."""
    return DIMENSION_LAYER_MAP.get(str(dimension or "").strip())


def is_supported_dimension(dimension: str) -> bool:
    """Return whether dimension is supported by current IncrementalMechanismV1."""
    return str(dimension or "").strip() in DIMENSION_LAYER_MAP


def dimension_sort_key(dimension: str) -> Tuple[int, str]:
    """Sort known dimensions by canonical order and unknown last."""
    normalized = str(dimension or "").strip()
    rank = DIMENSION_ORDER_INDEX.get(normalized, len(DIMENSION_ORDER_INDEX))
    return (rank, normalized)


def report_sort_key(report: Dict[str, Any]) -> Tuple[int, str, str, str]:
    """Sort reports by canonical dimension, then date/period/title."""
    dimension = str(report.get("dimension") or "").strip()
    date = str(report.get("date") or "").strip()
    period = str(report.get("period") or "").strip()
    title = str(report.get("title") or "").strip()
    rank = DIMENSION_ORDER_INDEX.get(dimension, len(DIMENSION_ORDER_INDEX))
    return (rank, period, date, title)


def sort_reports(reports: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Return reports sorted by canonical dimension order."""
    return sorted(list(reports), key=report_sort_key)
