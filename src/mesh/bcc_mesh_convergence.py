"""BCC paper_box CAE tet mesh-size sweep (quasi-static validation like Fig.2.10)."""

from __future__ import annotations

from typing import Any

# Seed-only h-refinement (mm). Quality / rods fixed so curves isolate mesh size.
BCC_MESH_SEED_LEVELS: tuple[dict[str, Any], ...] = (
    {
        "id": "s06",
        "label": "0.6",
        "cae_seed_mm": 0.6,
        "cae_rods_per_diameter": 3.0,
        "cae_mesh_quality": "lattice_contact",
        "variant_suffix": "meshval_s06",
        "reuse_baseline": True,
    },
    {
        "id": "s07",
        "label": "0.7",
        "cae_seed_mm": 0.7,
        "cae_rods_per_diameter": 3.0,
        "cae_mesh_quality": "lattice_contact",
        "variant_suffix": "meshval_s07",
        "reuse_baseline": False,
    },
    {
        "id": "s08",
        "label": "0.8",
        "cae_seed_mm": 0.8,
        "cae_rods_per_diameter": 3.0,
        "cae_mesh_quality": "lattice_contact",
        "variant_suffix": "meshval_s08",
        "reuse_baseline": False,
    },
    {
        "id": "s09",
        "label": "0.9",
        "cae_seed_mm": 0.9,
        "cae_rods_per_diameter": 3.0,
        "cae_mesh_quality": "lattice_contact",
        "variant_suffix": "meshval_s09",
        "reuse_baseline": False,
    },
    {
        "id": "s10",
        "label": "1.0",
        "cae_seed_mm": 1.0,
        "cae_rods_per_diameter": 3.0,
        "cae_mesh_quality": "lattice_contact",
        "variant_suffix": "meshval_s10",
        "reuse_baseline": False,
    },
    {
        "id": "s11",
        "label": "1.1",
        "cae_seed_mm": 1.1,
        "cae_rods_per_diameter": 3.0,
        "cae_mesh_quality": "lattice_contact",
        "variant_suffix": "meshval_s11",
        "reuse_baseline": False,
    },
)

BCC_BASELINE_SLUG = (
    "hu_bai_bcc_af2q0_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox"
)
BCC_BASE_SUFFIX = "cae_tet0p6mm80_5mmin_paperbox"


def slug_for_bcc_level(
    level: dict[str, Any],
    *,
    base_suffix: str = BCC_BASE_SUFFIX,
) -> str:
    if level.get("reuse_baseline"):
        return BCC_BASELINE_SLUG
    tag = level["variant_suffix"]
    return f"hu_bai_bcc_af2q0_L20_4x4x4_solid_cad_f_{base_suffix}_{tag}"
