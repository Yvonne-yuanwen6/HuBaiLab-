"""Canonical output paths for LatticeLab (export / Abaqus jobs / post / CAD).

Per-case paths are built by ``src.naming.case_paths_for_slug`` from a geometry slug.
See ``output/README.md`` and ``output/active_case.json`` after export.
"""

from __future__ import annotations

from pathlib import Path

# Project root = parent of src/
PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = PROJECT_ROOT / "output"
ACTIVE_CASE_JSON = OUTPUT_ROOT / "active_case.json"

# --- export / abaqus: per-case paths via src.naming (top_down|bottom_up/...) ---
EXPORT_ROOT = OUTPUT_ROOT / "export"
ABAQUS_ROOT = OUTPUT_ROOT / "abaqus"
ABAQUS_JOBS = ABAQUS_ROOT / "jobs"
ABAQUS_POST = ABAQUS_ROOT / "post"

# --- CAD / 文档 ---
CAD_ROOT = OUTPUT_ROOT / "cad" / "solidworks"
REPORTS_ROOT = OUTPUT_ROOT / "reports"


def ensure_output_dirs() -> None:
    """Create top-level output folders; per-case ``{slug}/`` dirs are created on export."""
    for p in (
        EXPORT_ROOT,
        ABAQUS_JOBS,
        ABAQUS_POST,
        CAD_ROOT,
        REPORTS_ROOT,
    ):
        p.mkdir(parents=True, exist_ok=True)
