"""
Adaptive junction fillet planning (experiment-only, does not touch batch main path).

Confirmed policy (2026-09):
  - Concave fillet relative to the *final connected solid*
  - Q=0: INTERIOR_CELL at body centre (8-way star, ~70°)
  - Q>0 (esp. Q=1.5): centre is Z-spine + ±Z 4-rod clusters (~11–15°),
    NOT a BCC-like single 8-way node — default: no large centre fillet
  - PERIODIC_SHARED: fuse array first, then fillet
  - BOUNDARY_FREE: skip by default
  - On fillet failure: reduce r automatically; record in manifest
  - Bare pipe fuse first; hub only if q_gt0_hub_factor>0 and bare fails
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any

import numpy as np


class NodeClass(str, Enum):
    INTERIOR_CELL = "INTERIOR_CELL"
    INTERIOR_SPINE = "INTERIOR_SPINE"
    INTERIOR_CLUSTER = "INTERIOR_CLUSTER"
    PERIODIC_SHARED = "PERIODIC_SHARED"
    BOUNDARY_FREE = "BOUNDARY_FREE"


@dataclass(frozen=True)
class AdaptiveNodeSpec:
    node_id: str
    xyz_mm: tuple[float, float, float]
    node_class: NodeClass
    valence: int
    r_min_strut_mm: float
    theta_min_deg: float | None = None
    clear_mm: float | None = None
    skip_fillet: bool = False


@dataclass
class AdaptiveFilletConfig:
    """Per-run adaptive knobs (experiment)."""

    k_blend: float = 0.50
    k_clear: float = 0.25
    k_angle: float = 0.35
    # Extra cap when strut mutual angle is acute (Q>0 clusters ~12°)
    k_blend_acute: float = 0.12
    acute_theta_deg: float = 25.0
    edge_select_factor: float = 1.5
    radius_fallback_scales: tuple[float, ...] = (1.0, 0.8, 0.6, 0.45, 0.3)
    skip_boundary_free: bool = True
    q_gt0_hub_factor: float = 0.0
    min_shared_multiplicity: int = 2
    # Q>0: do not apply large OCC fillet at centre by default (spine+clusters).
    fillet_q_gt0_interior: bool = False
    # If True and fillet_q_gt0_interior: only cluster nodes (never spine).
    fillet_q_gt0_clusters_only: bool = True
    # Cluster centres along ±Z as fraction of L (Q=1.5 Af=2: ~3 mm on L=20).
    q_gt0_cluster_z_frac: float = 0.15


def adaptive_r_blend_mm(spec: AdaptiveNodeSpec, cfg: AdaptiveFilletConfig) -> float:
    """Local fillet radius from strut size, clearance, and optional angle."""
    if spec.skip_fillet:
        return 0.0
    r = float(spec.r_min_strut_mm)
    candidates = [float(cfg.k_blend) * r]
    if spec.clear_mm is not None and spec.clear_mm > 0.0:
        candidates.append(float(cfg.k_clear) * float(spec.clear_mm))
    if spec.theta_min_deg is not None:
        th = np.deg2rad(float(spec.theta_min_deg))
        bound = float(cfg.k_angle) * r / max(np.sin(0.5 * th), 0.15)
        candidates.append(bound)
        if float(spec.theta_min_deg) < float(cfg.acute_theta_deg):
            candidates.append(float(cfg.k_blend_acute) * r)
    return float(max(0.0, min(candidates)))


def radius_ladder_mm(r0: float, cfg: AdaptiveFilletConfig) -> list[float]:
    if r0 <= 1e-9:
        return []
    out: list[float] = []
    for s in cfg.radius_fallback_scales:
        rr = float(r0) * float(s)
        if rr > 1e-4:
            out.append(rr)
    return out


def bcc_unitcell_interior_nodes(
    *,
    cell_size_mm: float,
    strut_radius_mm: float,
) -> list[AdaptiveNodeSpec]:
    """Q=0-like: single body-centre INTERIOR_CELL (8-way ~70° star)."""
    theta = float(np.degrees(np.arccos(1.0 / 3.0)))
    clear = 0.5 * float(cell_size_mm)
    return [
        AdaptiveNodeSpec(
            node_id="cell_centre",
            xyz_mm=(0.0, 0.0, 0.0),
            node_class=NodeClass.INTERIOR_CELL,
            valence=8,
            r_min_strut_mm=float(strut_radius_mm),
            theta_min_deg=theta,
            clear_mm=clear,
        )
    ]


def sfbls_qgt0_interior_nodes(
    *,
    cell_size_mm: float,
    strut_radius_mm: float,
    period_factor: float,
    cfg: AdaptiveFilletConfig,
) -> list[AdaptiveNodeSpec]:
    """
    Q>0 centre topology: Z-spine + ±Z 4-rod clusters (Q=1.5 Af=2 verified).

    Spine: skip fillet by default (near-parallel ±Z corridors).
    Clusters: acute ~12° pockets — only filleted when explicitly enabled.
    """
    L = float(cell_size_mm)
    r = float(strut_radius_mm)
    z_c = float(cfg.q_gt0_cluster_z_frac) * L
    theta_cluster = 12.0
    clear_cluster = 0.35 * L
    _ = period_factor  # reserved for Q-dependent z_c calibration
    return [
        AdaptiveNodeSpec(
            node_id="spine_centre",
            xyz_mm=(0.0, 0.0, 0.0),
            node_class=NodeClass.INTERIOR_SPINE,
            valence=8,
            r_min_strut_mm=r,
            theta_min_deg=180.0,
            clear_mm=0.5 * L,
            skip_fillet=True,
        ),
        AdaptiveNodeSpec(
            node_id="cluster_pos_z",
            xyz_mm=(0.0, 0.0, z_c),
            node_class=NodeClass.INTERIOR_CLUSTER,
            valence=4,
            r_min_strut_mm=r,
            theta_min_deg=theta_cluster,
            clear_mm=clear_cluster,
            skip_fillet=False,
        ),
        AdaptiveNodeSpec(
            node_id="cluster_neg_z",
            xyz_mm=(0.0, 0.0, -z_c),
            node_class=NodeClass.INTERIOR_CLUSTER,
            valence=4,
            r_min_strut_mm=r,
            theta_min_deg=theta_cluster,
            clear_mm=clear_cluster,
            skip_fillet=False,
        ),
    ]


def plan_unitcell_interior_nodes(
    *,
    cell_size_mm: float,
    strut_radius_mm: float,
    period_factor: float,
    cfg: AdaptiveFilletConfig,
) -> list[AdaptiveNodeSpec]:
    """Pick Q=0 star vs Q>0 spine+clusters planner."""
    if abs(float(period_factor)) < 1e-12:
        return bcc_unitcell_interior_nodes(
            cell_size_mm=cell_size_mm, strut_radius_mm=strut_radius_mm
        )
    return sfbls_qgt0_interior_nodes(
        cell_size_mm=cell_size_mm,
        strut_radius_mm=strut_radius_mm,
        period_factor=float(period_factor),
        cfg=cfg,
    )


def filter_fillet_targets(
    specs: list[AdaptiveNodeSpec],
    *,
    period_factor: float,
    cfg: AdaptiveFilletConfig,
) -> list[AdaptiveNodeSpec]:
    """Apply config gates: which planned nodes actually get MakeFillet."""
    out: list[AdaptiveNodeSpec] = []
    q = abs(float(period_factor))
    for s in specs:
        if cfg.skip_boundary_free and s.node_class == NodeClass.BOUNDARY_FREE:
            continue
        if s.skip_fillet:
            continue
        if q > 1e-12 and not cfg.fillet_q_gt0_interior:
            continue
        if (
            q > 1e-12
            and cfg.fillet_q_gt0_interior
            and cfg.fillet_q_gt0_clusters_only
            and s.node_class == NodeClass.INTERIOR_SPINE
        ):
            continue
        if s.node_class == NodeClass.INTERIOR_SPINE:
            continue
        out.append(s)
    return out


def bcc_array_shared_corner_nodes(
    *,
    cell_size_mm: float,
    strut_radius_mm: float,
    nx: int,
    ny: int,
    nz: int,
    min_multiplicity: int = 2,
) -> list[AdaptiveNodeSpec]:
    """Classify shared cube corners after a pitch=L array (origin seed + offsets)."""
    from src.export.exp_node_transition.bcc_fillet_blend import shared_corner_nodes_world_mm

    pts = shared_corner_nodes_world_mm(
        cell_size_mm=cell_size_mm,
        nx=nx,
        ny=ny,
        nz=nz,
        min_multiplicity=min_multiplicity,
    )
    theta = float(np.degrees(np.arccos(1.0 / 3.0)))
    clear = 0.5 * float(cell_size_mm)
    specs: list[AdaptiveNodeSpec] = []
    for i, p in enumerate(pts):
        specs.append(
            AdaptiveNodeSpec(
                node_id=f"shared_corner_{i}",
                xyz_mm=(float(p[0]), float(p[1]), float(p[2])),
                node_class=NodeClass.PERIODIC_SHARED,
                valence=8,
                r_min_strut_mm=float(strut_radius_mm),
                theta_min_deg=theta,
                clear_mm=clear,
            )
        )
    return specs


def plan_summary(specs: list[AdaptiveNodeSpec], cfg: AdaptiveFilletConfig) -> dict[str, Any]:
    rows = []
    for s in specs:
        r0 = adaptive_r_blend_mm(s, cfg)
        rows.append(
            {
                **asdict(s),
                "node_class": s.node_class.value,
                "r_blend_mm": r0,
                "r_ladder_mm": radius_ladder_mm(r0, cfg),
            }
        )
    return {
        "config": asdict(cfg),
        "nodes": rows,
        "counts": {
            c.value: sum(1 for s in specs if s.node_class == c) for c in NodeClass
        },
    }
