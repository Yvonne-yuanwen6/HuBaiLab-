"""Canonical output paths for HuBaiLab (Hu & Bai dedicated repo)."""

from __future__ import annotations

from pathlib import Path

# Project root = parent of src/
PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = PROJECT_ROOT / "output"
ACTIVE_CASE_JSON = OUTPUT_ROOT / "active_case.json"

EXPORT_ROOT = OUTPUT_ROOT / "export"
ABAQUS_JOBS = OUTPUT_ROOT / "jobs"
ABAQUS_POST = OUTPUT_ROOT / "post"
CAD_ROOT = OUTPUT_ROOT / "cad"
# Human-verified STEP files for Abaqus export (place confirmed solids here).
CAD_VERIFIED_ROOT = CAD_ROOT / "verified"
PREVIEWS_ROOT = OUTPUT_ROOT / "previews"
REPORTS_ROOT = OUTPUT_ROOT / "reports"

# Linux workstation (art@172.20.200.93) — mechanical disk mount
HUBAI_REMOTE_HOST = "art@172.20.200.93"
HUBAI_REMOTE_ROOT = "/media/art/file/XiangLang/Lattice/LWY/HuBaiLab"


def export_dir_for_slug(slug: str) -> Path:
    return EXPORT_ROOT / slug


def job_dir_for_slug(slug: str) -> Path:
    return ABAQUS_JOBS / slug


def post_dir_for_slug(slug: str) -> Path:
    return ABAQUS_POST / slug


def ensure_output_dirs() -> None:
    """Create top-level output folders; per-case ``{slug}/`` dirs are created on export."""
    for p in (
        EXPORT_ROOT,
        ABAQUS_JOBS,
        ABAQUS_POST,
        CAD_ROOT,
        CAD_VERIFIED_ROOT,
        PREVIEWS_ROOT,
        REPORTS_ROOT,
    ):
        p.mkdir(parents=True, exist_ok=True)
