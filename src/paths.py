"""Canonical output paths for HuBaiLab (Hu & Bai dedicated repo)."""

from __future__ import annotations

import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

# Project root = parent of src/ (override: HU_BAI_PROJECT_ROOT)
_DEFAULT_ROOT = Path(__file__).resolve().parents[1]
_PROJECT_ROOT_ENV = os.environ.get("HU_BAI_PROJECT_ROOT", "").strip()
PROJECT_ROOT = Path(_PROJECT_ROOT_ENV).resolve() if _PROJECT_ROOT_ENV else _DEFAULT_ROOT

# Local caches live under D:\HuBaiLab\.cache by default (override: HU_BAI_CACHE_ROOT)
_CACHE_ROOT_ENV = os.environ.get("HU_BAI_CACHE_ROOT", "").strip()
CACHE_ROOT = Path(_CACHE_ROOT_ENV).resolve() if _CACHE_ROOT_ENV else PROJECT_ROOT / ".cache"
TEMP_ROOT = CACHE_ROOT / "temp"
PIP_CACHE_ROOT = CACHE_ROOT / "pip"
NPM_CACHE_ROOT = CACHE_ROOT / "npm"

OUTPUT_ROOT = PROJECT_ROOT / "output"
ACTIVE_CASE_JSON = OUTPUT_ROOT / "active_case.json"

EXPORT_ROOT = OUTPUT_ROOT / "export"
ABAQUS_JOBS = OUTPUT_ROOT / "jobs"
ABAQUS_POST = OUTPUT_ROOT / "post"
TRASH_ROOT = OUTPUT_ROOT / "trash"
CAD_ROOT = OUTPUT_ROOT / "cad"
# Human-verified STEP files for Abaqus export (place confirmed solids here).
CAD_VERIFIED_ROOT = CAD_ROOT / "verified"
PREVIEWS_ROOT = OUTPUT_ROOT / "previews"
REPORTS_ROOT = OUTPUT_ROOT / "reports"

# Linux workstation (art@172.20.200.93) — mechanical disk mount
HUBAI_REMOTE_HOST = "art@172.20.200.93"
HUBAI_REMOTE_ROOT = "/media/art/file/XiangLang/Lattice/LWY/HuBaiLab"

# COMSOL Multiphysics 5.6 (art server)
COMSOL_DEFAULT_BIN = "/home/art/APP/comsol56/multiphysics/bin/comsol"
COMSOL_JOBS_ROOT = OUTPUT_ROOT / "comsol_jobs"
COMSOL_BATCH_PREFS_DIR = PROJECT_ROOT / "config" / "comsol_batch"


def export_dir_for_slug(slug: str) -> Path:
    return EXPORT_ROOT / slug


def job_dir_for_slug(slug: str) -> Path:
    return ABAQUS_JOBS / slug


def post_dir_for_slug(slug: str) -> Path:
    return ABAQUS_POST / slug


def ensure_cache_dirs() -> None:
    """Create local cache folders (temp / pip / npm) under project .cache on D:."""
    for p in (CACHE_ROOT, TEMP_ROOT, PIP_CACHE_ROOT, NPM_CACHE_ROOT):
        p.mkdir(parents=True, exist_ok=True)


def apply_local_cache_env(*, force: bool = False) -> None:
    """Point TEMP/TMP/PIP cache at project ``.cache`` (off C: when ``local_config.ps1`` is sourced)."""
    ensure_cache_dirs()
    temp = str(TEMP_ROOT)
    use_force = force or os.environ.get("HU_BAI_FORCE_LOCAL_CACHE") == "1"
    for key in ("TEMP", "TMP", "TMPDIR"):
        if use_force or not os.environ.get(key):
            os.environ[key] = temp
    if use_force or not os.environ.get("PIP_CACHE_DIR"):
        os.environ["PIP_CACHE_DIR"] = str(PIP_CACHE_ROOT)
    if use_force or not os.environ.get("NPM_CONFIG_CACHE"):
        os.environ["NPM_CONFIG_CACHE"] = str(NPM_CACHE_ROOT)


def hubai_temp_dir(*, prefix: str = "hubai_") -> str:
    """Create a temp directory under ``.cache/temp`` instead of ``C:\\Users\\...\\Temp``."""
    ensure_cache_dirs()
    return tempfile.mkdtemp(prefix=prefix, dir=str(TEMP_ROOT))


@contextmanager
def hubai_temp_directory(*, prefix: str = "hubai_") -> Iterator[str]:
    """Like ``tempfile.TemporaryDirectory`` but uses project ``.cache/temp``."""
    ensure_cache_dirs()
    with tempfile.TemporaryDirectory(prefix=prefix, dir=str(TEMP_ROOT)) as tmp:
        yield tmp


def ensure_output_dirs() -> None:
    """Create top-level output folders; per-case ``{slug}/`` dirs are created on export."""
    ensure_cache_dirs()
    for p in (
        EXPORT_ROOT,
        ABAQUS_JOBS,
        ABAQUS_POST,
        TRASH_ROOT,
        COMSOL_JOBS_ROOT,
        CAD_ROOT,
        CAD_VERIFIED_ROOT,
        PREVIEWS_ROOT,
        REPORTS_ROOT,
    ):
        p.mkdir(parents=True, exist_ok=True)


apply_local_cache_env()
