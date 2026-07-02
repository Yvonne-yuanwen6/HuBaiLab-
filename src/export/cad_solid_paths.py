"""Resolve CAD solid paths (STEP / X_T) for Abaqus export."""

from __future__ import annotations

import os

from src.paths import CAD_VERIFIED_ROOT


def hu_bai_lattice_slug(
    *,
    variant_name: str,
    cell_size_mm: float,
    nx: int,
    ny: int,
    nz: int,
) -> str:
    """Canonical lattice CAD basename, e.g. ``hu_bai_sfbls_af2q0p5_L20_4x4x4``."""
    return (
        f"hu_bai_{variant_name.lower()}_L{int(round(cell_size_mm))}_{int(nx)}x{int(ny)}x{int(nz)}"
    )


def verified_solid_step_filenames(slug_base: str) -> tuple[str, ...]:
    """Preferred STEP filenames under ``output/cad/verified/``."""
    return (
        f"{slug_base}_paper_box_array.step",
        f"{slug_base}_paper_box_array.STEP",
        f"{slug_base}_solid_array.step",
        f"{slug_base}_solid_array.STEP",
        f"{slug_base}_solid_merged.step",
        f"{slug_base}_solid_merged.STEP",
        f"{slug_base}_solid_layered.step",
        f"{slug_base}_solid.step",
    )


def _legacy_bcc_slug(*, cell_size_mm: float, nx: int, ny: int, nz: int) -> str:
    return f"hu_bai_bcc_af2q0_L{int(round(cell_size_mm))}_{int(nx)}x{int(ny)}x{int(nz)}"


def _is_under_verified(path: str) -> bool:
    verified = os.path.abspath(str(CAD_VERIFIED_ROOT))
    target = os.path.abspath(path)
    try:
        common = os.path.commonpath([verified, target])
    except ValueError:
        return False
    return common == verified


def require_verified_cad_path(path: str) -> str:
    """Return ``path`` if it exists and lives under ``output/cad/verified/``."""
    path = os.path.abspath(path)
    if not os.path.isfile(path):
        raise FileNotFoundError(path)
    if not _is_under_verified(path):
        raise ValueError(
            f"Simulation CAD must be under {CAD_VERIFIED_ROOT}: {path}\n"
            "Copy the human-verified STEP into output/cad/verified/ and re-run."
        )
    return path


def resolve_verified_solid_step(
    *,
    variant_name: str,
    cell_size_mm: float,
    nx: int,
    ny: int,
    nz: int,
    cad_path: str | None = None,
) -> str:
    """
    Resolve the STEP file used for Abaqus solid export.

    All simulation runs must read from ``output/cad/verified/``. When
    ``cad_path`` is omitted, search verified names for this lattice slug.
    When ``cad_path`` is given, it must still reside under verified/.
    """
    if cad_path:
        return require_verified_cad_path(cad_path)

    verified_dir = os.path.abspath(str(CAD_VERIFIED_ROOT))
    slug = hu_bai_lattice_slug(
        variant_name=variant_name,
        cell_size_mm=cell_size_mm,
        nx=nx,
        ny=ny,
        nz=nz,
    )
    slug_candidates = (slug, _legacy_bcc_slug(cell_size_mm=cell_size_mm, nx=nx, ny=ny, nz=nz))

    tried: list[str] = []
    for base in slug_candidates:
        for name in verified_solid_step_filenames(base):
            candidate = os.path.join(verified_dir, name)
            tried.append(candidate)
            if os.path.isfile(candidate):
                return candidate

    expected = verified_solid_step_filenames(slug)
    tried_text = "\n  ".join(tried[: len(expected)] + tried[len(expected) : len(expected) * 2])
    raise FileNotFoundError(
        f"No verified CAD STEP for {slug} under {verified_dir}.\n"
        f"Place a confirmed file such as:\n"
        f"  {os.path.join(verified_dir, expected[0])}\n"
        f"Searched:\n  {tried_text}"
    )


def resolve_step_and_xt(cad_path: str) -> tuple[str, str | None]:
    """
    Return (step_path, xt_path_or_none).

    Mesher uses STEP; X_T is kept for manifest / manual Abaqus import.
    """
    cad_path = require_verified_cad_path(cad_path)

    ext = os.path.splitext(cad_path)[1].lower()
    if ext in (".step", ".stp"):
        xt = os.path.splitext(cad_path)[0] + ".x_t"
        return cad_path, xt if os.path.isfile(xt) else None
    if ext == ".x_t":
        step = os.path.splitext(cad_path)[0] + ".step"
        if not os.path.isfile(step):
            raise FileNotFoundError(
                f"No sibling STEP for {cad_path}. Export fused STEP first "
                "(run_hu_bai_bcc_sw_export.py --cells N)."
            )
        return require_verified_cad_path(step), cad_path
    raise ValueError(f"Unsupported CAD extension: {cad_path}")
