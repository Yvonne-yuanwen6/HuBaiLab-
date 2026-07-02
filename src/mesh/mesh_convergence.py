"""Mesh convergence sweep levels for Hu & Bai paper_box CAE tet (Fig.3.3 Q0.5 focus)."""

from __future__ import annotations

from typing import Any

# Each level: CAE seed [mm], rods across diameter, quality preset, optional case suffix tag.
Q05_MESH_CONVERGENCE_LEVELS: tuple[dict[str, Any], ...] = (
    {
        "id": "m0_baseline",
        "label": "baseline 0.6mm r3 contact",
        "cae_seed_mm": 0.6,
        "cae_rods_per_diameter": 3.0,
        "cae_mesh_quality": "lattice_contact",
        "variant_suffix": "mesh_m0_baseline",
    },
    {
        "id": "m1_rods4",
        "label": "0.6mm r4 contact",
        "cae_seed_mm": 0.6,
        "cae_rods_per_diameter": 4.0,
        "cae_mesh_quality": "lattice_contact",
        "variant_suffix": "mesh_m1_rods4",
    },
    {
        "id": "m2_curve_r4",
        "label": "0.6mm r4 lattice_curve",
        "cae_seed_mm": 0.6,
        "cae_rods_per_diameter": 4.0,
        "cae_mesh_quality": "lattice_curve",
        "variant_suffix": "mesh_m2_curve_r4",
    },
    {
        "id": "m3_seed05_r4",
        "label": "0.5mm r4 lattice_curve",
        "cae_seed_mm": 0.5,
        "cae_rods_per_diameter": 4.0,
        "cae_mesh_quality": "lattice_curve",
        "variant_suffix": "mesh_m3_seed05_r4",
    },
    {
        "id": "m4_seed04_r5",
        "label": "0.4mm r5 lattice_curve",
        "cae_seed_mm": 0.4,
        "cae_rods_per_diameter": 5.0,
        "cae_mesh_quality": "lattice_curve",
        "variant_suffix": "mesh_m4_seed04_r5",
    },
)

FIG33_Q05_KEY = "af2q05"


def slug_for_q05_level(
    level: dict[str, Any],
    *,
    base_suffix: str = "cae_tet0p6mm80_5mmin_paperbox",
) -> str:
    """Full case slug for SFBLS Q0.5 mesh convergence variant."""
    tag = level["variant_suffix"]
    return (
        f"hu_bai_sfbls_af2q0p5_L20_4x4x4_solid_cad_f_{base_suffix}_{tag}"
    )
