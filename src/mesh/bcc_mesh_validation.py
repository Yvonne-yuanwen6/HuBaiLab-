"""BCC paper_box mesh-size / quasi-static pre-validation (Fig.2.10-style)."""

from __future__ import annotations

from typing import Any

BASE_SUFFIX = "cae_tet0p6mm80_5mmin_paperbox"
BASELINE_SLUG = f"hu_bai_bcc_af2q0_L20_4x4x4_solid_cad_f_{BASE_SUFFIX}"

# Mesh-size sweep (align with literature Table 2.1 denser set).
# 0.6 reuses completed baseline; others remesh under lattice_contact.
BCC_MESH_SEED_LEVELS: tuple[dict[str, Any], ...] = (
    {
        "id": "s06",
        "label": "0.6",
        "cae_seed_mm": 0.6,
        "cae_rods_per_diameter": 3.0,
        "cae_mesh_quality": "lattice_contact",
        "variant_suffix": "",
        "reuse_baseline": True,
    },
    {
        "id": "s07",
        "label": "0.7",
        "cae_seed_mm": 0.7,
        "cae_rods_per_diameter": 3.0,
        "cae_mesh_quality": "lattice_contact",
        "variant_suffix": "meshseed_07",
        "reuse_baseline": False,
    },
    {
        "id": "s08",
        "label": "0.8",
        "cae_seed_mm": 0.8,
        "cae_rods_per_diameter": 3.0,
        "cae_mesh_quality": "lattice_contact",
        "variant_suffix": "meshseed_08",
        "reuse_baseline": False,
    },
    {
        "id": "s09",
        "label": "0.9",
        "cae_seed_mm": 0.9,
        "cae_rods_per_diameter": 2.5,
        "cae_mesh_quality": "lattice_contact",
        "variant_suffix": "meshseed_09",
        "reuse_baseline": False,
    },
    {
        "id": "s10",
        "label": "1.0",
        "cae_seed_mm": 1.0,
        "cae_rods_per_diameter": 2.5,
        "cae_mesh_quality": "lattice_contact",
        "variant_suffix": "meshseed_10",
        "reuse_baseline": False,
    },
    {
        "id": "s11",
        "label": "1.1",
        "cae_seed_mm": 1.1,
        "cae_rods_per_diameter": 2.0,
        "cae_mesh_quality": "lattice_contact",
        "variant_suffix": "meshseed_11",
        "reuse_baseline": False,
    },
    {
        "id": "s12",
        "label": "1.2",
        "cae_seed_mm": 1.2,
        "cae_rods_per_diameter": 2.0,
        "cae_mesh_quality": "lattice_contact",
        "variant_suffix": "meshseed_12",
        "reuse_baseline": False,
    },
)


def slug_for_bcc_level(level: dict[str, Any]) -> str:
    if level.get("reuse_baseline"):
        return BASELINE_SLUG
    tag = level["variant_suffix"]
    return f"hu_bai_bcc_af2q0_L20_4x4x4_solid_cad_f_{BASE_SUFFIX}_{tag}"
