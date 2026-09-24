"""
Slot-based intersection fillet for HuBai BCC/SFBLS unitcells (experiment).

Q=0: 12 acute sign-flip neighbour slots (arccos(1/3)≈70.5°).
Q>0: centre-tangent armpit pairs with 5°<θ<100° (typically 12 same-cluster;
     Q=1 may yield 16 near-90° pairs).

Strategy: assign one BRep intersection edge per slot on the *bare* solid,
MakeFillet: Q=0 uniform batch; Q>0 adaptive-r oneshot including waist ring.

Isolation: scripts/exp_slot_fillet_*.py only; no batch defaults.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np

from src.export.exp_node_transition.bcc_explicit_cores import default_exp_out_dir
from src.export.exp_node_transition.bcc_fillet_blend import (
    ExpFilletParams,
    _edge_midpoint_mm,
    _try_fillet,
    fuse_pipes_unitcell_bare_ladder,
    load_fillet_pipe_parts,
)
from src.export.exp_node_transition.centre_edge_fillet import (
    _bbox_span,
    _edge_faces,
    _edge_length_mm,
    _unit,
)
from src.export.exp_node_transition.intersection_edge_fillet import (
    _dihedral_normals,
    _edge_is_nearly_straight,
)
from src.export.ocp_unitcell_fuse import ocp_mass, ocp_shape_topology, ocp_write_step
from src.export.unitcell_box_cut import (
    _canonical_corner_from_pipe_path,
    unitcell_octant_corners_mm,
)


@dataclass
class SlotFilletParams:
    cell_size_mm: float = 20.0
    rod_d_mm: float = 2.0
    amplitude_mm: float = 2.0
    period_factor: float = 0.0
    n_segments: int = 32
    r_blend_factor: float = 0.35
    radius_scales: tuple[float, ...] = (0.75, 0.55, 1.0, 0.40, 0.30)
    r_band_min_mm: float = 1.0
    r_band_max_mm: float = 3.5
    max_ray_dist_mm: float = 0.85
    max_plane_dist_mm: float = 0.90
    min_edge_len_mm: float = 0.35
    max_edge_len_mm: float = 6.0
    normal_dot_min: float = -0.95
    normal_dot_max: float = 0.70
    max_dmass_step_mm3: float = 0.90
    max_step_mass_drift_mm3: float = 0.80
    # Q>0 pair angle window (degrees) on centre tangents
    pair_theta_min_deg: float = 5.0
    pair_theta_max_deg: float = 100.0
    # Adaptive r vs crotch opening (Q>0); Q=0 ignores these
    adaptive_theta_ref_deg: float = 70.528779  # arccos(1/3)
    adaptive_scale_min: float = 0.55
    adaptive_scale_max: float = 1.20


@dataclass
class AcuteSlot:
    slot_id: int
    i: int
    j: int
    corner_i: tuple[float, float, float]
    corner_j: tuple[float, float, float]
    dir_i: np.ndarray
    dir_j: np.ndarray
    bisector: np.ndarray
    plane_n: np.ndarray
    theta_deg: float = 0.0


def default_rf_for_q(q: float) -> float:
    aq = abs(float(q))
    if aq < 1e-12:
        return 0.35
    if abs(aq - 0.5) < 1e-9:
        return 0.28
    if abs(aq - 1.0) < 1e-9:
        return 0.18
    return 0.12


def _centre_tangents_by_corner(
    params: SlotFilletParams,
) -> dict[int, np.ndarray]:
    """Map corner index 0..7 → unit centre tangent of that strut."""
    fp = ExpFilletParams(
        cell_size_mm=params.cell_size_mm,
        rod_d_mm=params.rod_d_mm,
        amplitude_mm=params.amplitude_mm,
        period_factor=params.period_factor,
        n_segments=params.n_segments,
    )
    parts = load_fillet_pipe_parts(fp)
    corners = unitcell_octant_corners_mm(params.cell_size_mm)
    byc: dict[int, np.ndarray] = {}
    for part in parts:
        path = part[1]
        pc = _canonical_corner_from_pipe_path(path, params.cell_size_mm)
        ci = min(
            range(8),
            key=lambda j: float(
                np.linalg.norm(np.asarray(corners[j], float) - np.asarray(pc, float))
            ),
        )
        P = np.asarray(path, dtype=float)
        byc[ci] = _unit(P[1] - P[0])
    if len(byc) != 8:
        raise RuntimeError(f"expected 8 centre tangents, got {len(byc)}")
    return byc


def bcc_acute_pair_slots(cell_size_mm: float) -> list[AcuteSlot]:
    """Q=0: 12 acute-neighbour strut-pair slots (sign flip in exactly one axis)."""
    corners = unitcell_octant_corners_mm(cell_size_mm)
    dirs = [_unit(np.asarray(c, dtype=float)) for c in corners]
    slots: list[AcuteSlot] = []
    sid = 0
    for i in range(8):
        for j in range(i + 1, 8):
            si = np.sign(np.asarray(corners[i], dtype=float))
            sj = np.sign(np.asarray(corners[j], dtype=float))
            n_flip = int(np.sum(np.abs(si - sj) > 0.5))
            if n_flip != 1:
                continue
            di, dj = dirs[i], dirs[j]
            bis = _unit(di + dj)
            cross = np.cross(di, dj)
            cn = float(np.linalg.norm(cross))
            if cn < 1e-12:
                continue
            c = float(np.clip(np.dot(di, dj), -1.0, 1.0))
            th = float(np.degrees(np.arccos(c)))
            slots.append(
                AcuteSlot(
                    slot_id=sid,
                    i=i,
                    j=j,
                    corner_i=corners[i],
                    corner_j=corners[j],
                    dir_i=di,
                    dir_j=dj,
                    bisector=bis,
                    plane_n=cross / cn,
                    theta_deg=th,
                )
            )
            sid += 1
    if len(slots) != 12:
        raise RuntimeError(f"expected 12 acute slots, got {len(slots)}")
    return slots


def _is_z_flip_only_pair(
    corner_i: tuple[float, float, float],
    corner_j: tuple[float, float, float],
) -> bool:
    """True if corner signs differ only in Z (vertical neighbour / waist ring)."""
    si = np.sign(np.asarray(corner_i, dtype=float))
    sj = np.sign(np.asarray(corner_j, dtype=float))
    flips = np.abs(si - sj) > 0.5
    return int(np.sum(flips)) == 1 and bool(flips[2])


def tangent_armpit_slots(params: SlotFilletParams) -> list[AcuteSlot]:
    """
    Q>0: same-cluster armpit pairs (5°<θ<100°) plus waist-ring Z-flip
    neighbours (vertical pairs across ±Z clusters).

    Near Q=1, cross-cluster pairs share BRep edges with same-cluster ones —
    keep same-z-cluster slots only.
    """
    corners = unitcell_octant_corners_mm(params.cell_size_mm)
    byc = _centre_tangents_by_corner(params)
    tmin = float(params.pair_theta_min_deg)
    tmax = float(params.pair_theta_max_deg)
    q = abs(float(params.period_factor))
    same_cluster_only = abs(q - 1.0) < 0.05
    slots: list[AcuteSlot] = []
    sid = 0

    def _add(i: int, j: int, th: float, ti: np.ndarray, tj: np.ndarray) -> None:
        nonlocal sid
        bis = _unit(ti + tj)
        cross = np.cross(ti, tj)
        cn = float(np.linalg.norm(cross))
        if cn < 1e-12:
            return
        slots.append(
            AcuteSlot(
                slot_id=sid,
                i=i,
                j=j,
                corner_i=corners[i],
                corner_j=corners[j],
                dir_i=ti,
                dir_j=tj,
                bisector=bis,
                plane_n=cross / cn,
                theta_deg=th,
            )
        )
        sid += 1

    for i in range(8):
        for j in range(i + 1, 8):
            zi = float(corners[i][2])
            zj = float(corners[j][2])
            if same_cluster_only and (zi * zj) <= 0.0:
                continue
            ti, tj = byc[i], byc[j]
            c = float(np.clip(np.dot(ti, tj), -1.0, 1.0))
            th = float(np.degrees(np.arccos(c)))
            if not (tmin < th < tmax):
                continue
            _add(i, j, th, ti, tj)

    # Waist ring: Z-flip-only pairs (θ typically ~110° for Q=0.5)
    if not same_cluster_only:
        for i in range(8):
            for j in range(i + 1, 8):
                if not _is_z_flip_only_pair(corners[i], corners[j]):
                    continue
                ti, tj = byc[i], byc[j]
                c = float(np.clip(np.dot(ti, tj), -1.0, 1.0))
                th = float(np.degrees(np.arccos(c)))
                if th < 95.0 or th > 160.0:
                    continue
                # skip if already added
                if any({s.i, s.j} == {i, j} for s in slots):
                    continue
                _add(i, j, th, ti, tj)

    if not slots:
        raise RuntimeError(
            f"no tangent armpit slots for Q={params.period_factor:g} "
            f"in ({tmin:g},{tmax:g}) deg"
        )
    return slots



def build_slots_for_params(params: SlotFilletParams) -> list[AcuteSlot]:
    if abs(float(params.period_factor)) < 1e-12:
        return bcc_acute_pair_slots(params.cell_size_mm)
    return tangent_armpit_slots(params)


def _point_to_ray_dist(p: np.ndarray, ray_dir: np.ndarray) -> float:
    t = float(np.dot(p, ray_dir))
    if t < 0.0:
        return float(np.linalg.norm(p))
    return float(np.linalg.norm(p - t * ray_dir))


def _is_concave_for_slot(
    shape: Any,
    edge: Any,
    slot: AcuteSlot,
    params: SlotFilletParams,
) -> bool:
    dih = _dihedral_normals(shape, edge)
    if dih is None:
        return False
    n0, n1, ndot = dih
    if ndot < float(params.normal_dot_min) or ndot > float(params.normal_dot_max):
        return False
    mid = _edge_midpoint_mm(edge)
    if mid is None:
        return False
    n_avg = _unit(n0 + n1)
    return float(np.dot(n_avg, slot.bisector)) > 0.0


def find_edges_for_slot(
    shape: Any,
    slot: AcuteSlot,
    params: SlotFilletParams,
) -> list[dict[str, Any]]:
    from OCP.TopAbs import TopAbs_EDGE
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS

    scored: list[tuple[float, dict[str, Any]]] = []
    seen: set[tuple[float, float, float]] = set()
    exp = TopExp_Explorer(shape, TopAbs_EDGE)
    while exp.More():
        edge = TopoDS.Edge_s(exp.Current())
        exp.Next()
        mid = _edge_midpoint_mm(edge)
        if mid is None:
            continue
        key = (round(float(mid[0]), 4), round(float(mid[1]), 4), round(float(mid[2]), 4))
        if key in seen:
            continue
        rr = float(np.linalg.norm(mid))
        if rr < float(params.r_band_min_mm) or rr > float(params.r_band_max_mm):
            continue
        elen = _edge_length_mm(edge)
        if elen < float(params.min_edge_len_mm) or elen > float(params.max_edge_len_mm):
            continue
        if _edge_is_nearly_straight(edge):
            continue
        if len(_edge_faces(shape, edge)) != 2:
            continue
        plane_d = abs(float(np.dot(mid, slot.plane_n)))
        if plane_d > float(params.max_plane_dist_mm):
            continue
        ray_d = _point_to_ray_dist(mid, slot.bisector)
        if ray_d > float(params.max_ray_dist_mm):
            continue
        if not _is_concave_for_slot(shape, edge, slot, params):
            continue
        dih = _dihedral_normals(shape, edge)
        ndot = float(dih[2]) if dih else 1.0
        score = elen - 2.0 * ray_d - 1.0 * plane_d
        seen.add(key)
        scored.append(
            (
                score,
                {
                    "edge": edge,
                    "mid": mid,
                    "length_mm": elen,
                    "r_mm": rr,
                    "ray_dist": ray_d,
                    "plane_dist": plane_d,
                    "ndot": ndot,
                },
            )
        )
    scored.sort(key=lambda t: -t[0])
    return [d for _, d in scored]


def _as_single_solid(shape: Any) -> Any:
    from OCP.TopAbs import TopAbs_SOLID
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS

    exp = TopExp_Explorer(shape, TopAbs_SOLID)
    solids = []
    while exp.More():
        solids.append(TopoDS.Solid_s(exp.Current()))
        exp.Next()
    if len(solids) != 1:
        raise RuntimeError(f"expected 1 solid, got {len(solids)}")
    return solids[0]


def _mid_key(mid: Any) -> tuple[float, float, float]:
    return (
        round(float(mid[0]), 3),
        round(float(mid[1]), 3),
        round(float(mid[2]), 3),
    )


def _assign_edge_for_slot(
    shape: Any,
    slot: AcuteSlot,
    params: SlotFilletParams,
    *,
    used_mids: set[tuple[float, float, float]] | None = None,
    max_edge_len_mm: float | None = None,
) -> dict[str, Any] | None:
    cands = find_edges_for_slot(shape, slot, params)
    if not cands:
        saved = (
            params.max_ray_dist_mm,
            params.max_plane_dist_mm,
            params.r_band_max_mm,
        )
        params.max_ray_dist_mm = max(saved[0], 1.6)
        params.max_plane_dist_mm = max(saved[1], 1.6)
        params.r_band_max_mm = max(saved[2], 5.0)
        cands = find_edges_for_slot(shape, slot, params)
        (
            params.max_ray_dist_mm,
            params.max_plane_dist_mm,
            params.r_band_max_mm,
        ) = saved
    lim = float(max_edge_len_mm) if max_edge_len_mm is not None else 1e9
    for info in cands:
        if float(info["length_mm"]) > lim:
            continue
        if not _slot_mid_z_ok(
            slot, info["mid"], period_factor=float(params.period_factor)
        ):
            continue
        key = _mid_key(info["mid"])
        if used_mids is not None and key in used_mids:
            continue
        if used_mids is not None:
            used_mids.add(key)
        return info
    return None


def _slot_z_group(slot: AcuteSlot) -> str:
    zi = float(slot.corner_i[2])
    zj = float(slot.corner_j[2])
    if zi < 0.0 and zj < 0.0:
        return "bot"
    if zi > 0.0 and zj > 0.0:
        return "top"
    return "cross"



def adaptive_slot_radius_mm(slot: AcuteSlot, params: SlotFilletParams) -> float:
    """
    Local fillet radius from crotch opening angle.

    Q=0 is fully symmetric → constant r0.
    Q>0: open_deg = min(θ, 180-θ); scale vs BCC acute ≈70.53°.
    Tighter crotches get smaller r; more open get larger (clamped).
    """
    r0 = float(params.r_blend_factor) * 0.5 * float(params.rod_d_mm)
    if abs(float(params.period_factor)) < 1e-12:
        return r0
    open_deg = min(float(slot.theta_deg), 180.0 - float(slot.theta_deg))
    ref = float(params.adaptive_theta_ref_deg)
    soft = float(np.clip(open_deg / max(ref, 1e-6), params.adaptive_scale_min, params.adaptive_scale_max))
    return r0 * soft


def _is_z_flip_only_pair(
    corner_i: tuple[float, float, float],
    corner_j: tuple[float, float, float],
) -> bool:
    """True if corner signs differ only in Z (vertical neighbour / waist ring)."""
    si = np.sign(np.asarray(corner_i, dtype=float))
    sj = np.sign(np.asarray(corner_j, dtype=float))
    flips = np.abs(si - sj) > 0.5
    return int(np.sum(flips)) == 1 and bool(flips[2])


def _try_fillet_per_edge(
    shape: Any,
    edge_radius_pairs: list[tuple[Any, float]],
) -> Any:
    from OCP.BRepFilletAPI import BRepFilletAPI_MakeFillet

    if not edge_radius_pairs:
        raise ValueError("no edges to fillet")
    mk = BRepFilletAPI_MakeFillet(shape)
    n_add = 0
    rs: list[float] = []
    for edge, rad in edge_radius_pairs:
        rad_f = float(rad)
        if rad_f <= 1e-6:
            continue
        try:
            mk.Add(rad_f, edge)
            n_add += 1
            rs.append(rad_f)
        except Exception:
            continue
    if n_add == 0:
        raise RuntimeError("failed to add any edge to fillet builder")
    print(
        f"  [fillet] MakeFillet n={n_add} r=[{min(rs):.3f},{max(rs):.3f}] mm ...",
        flush=True,
    )
    mk.Build()
    if not mk.IsDone():
        raise RuntimeError("BRepFilletAPI_MakeFillet not done")
    out = mk.Shape()
    if ocp_mass(out) <= 0.0:
        raise RuntimeError("fillet produced empty solid")
    return out


def _slot_mid_z_ok(
    slot: AcuteSlot,
    mid: np.ndarray,
    *,
    period_factor: float = 0.5,
) -> bool:
    """
    Q≈0.5: keep same-cluster edges off the waist plane and vice versa.
    Q=0 / Q≈1: disabled (edges sit near coordinate planes / equator).
    """
    q = abs(float(period_factor))
    if q < 1e-12 or abs(q - 1.0) < 0.05:
        return True
    g = _slot_z_group(slot)
    z = float(mid[2])
    if g == "cross":
        return abs(z) <= 0.55
    return abs(z) >= 0.55


def _fillet_batches_for_slots(slots: list[AcuteSlot], q: float) -> list[list[AcuteSlot]]:
    """Q=0: one batch. Q>0: bot -> top -> cross with re-find between."""
    if abs(q) < 1e-12:
        return [list(slots)]
    groups: dict[str, list[AcuteSlot]] = {"bot": [], "top": [], "cross": []}
    for s in slots:
        groups[_slot_z_group(s)].append(s)
    return [g for g in (groups["bot"], groups["top"], groups["cross"]) if g]


def _step_roundtrip_solid(
    shape: Any,
    *,
    mass_ref: float,
    max_drift: float,
) -> Any:
    import tempfile

    from src.export.ocp_paper_box_array_fuse import ocp_read_step_shape

    with tempfile.TemporaryDirectory(prefix="slot_fillet_rb_") as td:
        tmp = os.path.join(td, "trial.step")
        ocp_write_step(shape, tmp)
        rb = ocp_read_step_shape(tmp)
        rb_topo = ocp_shape_topology(rb, check_brep=True)
        rb_mass = float(ocp_mass(rb))
        if int(rb_topo.get("solids") or 0) != 1:
            raise RuntimeError(f"STEP rb solids={rb_topo.get('solids')}")
        if abs(rb_mass - mass_ref) > float(max_drift):
            raise RuntimeError(
                f"STEP rb mass drift mem={mass_ref:.3f} rb={rb_mass:.3f}"
            )
        return rb


def apply_slot_fillets(
    shape: Any,
    params: SlotFilletParams,
    *,
    max_edge_len_mm: float | None | str = "auto",
    max_span_factor: float = 1.35,
) -> tuple[Any, dict[str, Any]]:
    """Assign unique edges per slot; Q>0 oneshot adaptive MakeFillet (incl. waist)."""
    slots = build_slots_for_params(params)
    r_strut = 0.5 * float(params.rod_d_mm)
    r0 = float(params.r_blend_factor) * r_strut
    m0 = float(ocp_mass(shape))
    span0 = _bbox_span(shape)
    max_span = float(params.cell_size_mm) * float(max_span_factor)
    q = float(params.period_factor)

    if abs(q) > 1e-12:
        params = SlotFilletParams(**{**asdict(params)})
        params.r_band_max_mm = max(float(params.r_band_max_mm), 4.2)
        params.r_band_min_mm = min(float(params.r_band_min_mm), 0.9)
        params.max_ray_dist_mm = max(float(params.max_ray_dist_mm), 1.25)
        params.max_plane_dist_mm = max(float(params.max_plane_dist_mm), 1.25)
        params.normal_dot_max = max(float(params.normal_dot_max), 0.85)

    if max_edge_len_mm == "auto":
        max_elen = 2.5 if abs(q) > 1.2 else None
    else:
        max_elen = max_edge_len_mm
    used_mids: set[tuple[float, float, float]] = set()
    assigned_slots: list[AcuteSlot] = []
    slot_edge_info: list[dict[str, Any]] = []
    bare_pairs: list[tuple[AcuteSlot, dict[str, Any]]] = []

    for slot in slots:
        info = _assign_edge_for_slot(
            shape, slot, params, used_mids=used_mids, max_edge_len_mm=max_elen
        )
        r_loc = adaptive_slot_radius_mm(slot, params)
        if info is None:
            print(
                f"  [slotFillet] slot#{slot.slot_id:02d} pair=({slot.i},{slot.j}) "
                f"theta={slot.theta_deg:.1f} [{_slot_z_group(slot)}] NO unique edge",
                flush=True,
            )
            slot_edge_info.append(
                {
                    "slot_id": slot.slot_id,
                    "pair": [slot.i, slot.j],
                    "theta_deg": slot.theta_deg,
                    "group": _slot_z_group(slot),
                    "assigned": False,
                    "r_adapt_mm": r_loc,
                }
            )
            continue
        assigned_slots.append(slot)
        bare_pairs.append((slot, info))
        slot_edge_info.append(
            {
                "slot_id": slot.slot_id,
                "pair": [slot.i, slot.j],
                "theta_deg": slot.theta_deg,
                "group": _slot_z_group(slot),
                "assigned": True,
                "length_mm": info["length_mm"],
                "r_mm": info["r_mm"],
                "ray_dist": info["ray_dist"],
                "plane_dist": info["plane_dist"],
                "mid": [float(x) for x in info["mid"]],
                "r_adapt_mm": r_loc,
            }
        )
        print(
            f"  [slotFillet] slot#{slot.slot_id:02d} pair=({slot.i},{slot.j}) "
            f"theta={slot.theta_deg:.1f} [{_slot_z_group(slot)}] "
            f"edge L={info['length_mm']:.2f} r_adapt={r_loc:.3f}",
            flush=True,
        )

    n_slots = len(slots)
    n_assigned = len(assigned_slots)
    if abs(q) < 0.75 and n_assigned < n_slots:
        raise RuntimeError(f"only {n_assigned}/{n_slots} slots have a bare edge")
    if n_assigned < 1:
        raise RuntimeError("no unique slot edges to fillet")

    print(
        f"  [slotFillet] Q={q:g} slots={n_slots} unique={n_assigned} r0={r0:.3f} mm",
        flush=True,
    )

    # Global radius ladder multiplies adaptive local radii
    scales = list(params.radius_scales)
    if abs(q) > 1.2:
        # Very acute clusters: adaptive soft floor is small — need higher scales
        scales = [0.85, 0.75, 0.95, 0.65, 1.0, 0.55, 0.45]
    elif abs(q) > 1e-12:
        scales = [0.40, 0.35, 0.38, 0.45, 0.30, 0.50]
    else:
        scales = [0.75, 0.55, 1.0, 0.40, 0.30]

    span_grow_tol = 2.6 if abs(q) < 1e-12 else 1.5

    last_exc: Exception | None = None
    final = None
    used_r_summary: dict[str, Any] | None = None

    for scale in scales:
        try:
            pairs: list[tuple[Any, float]] = []
            r_list: list[float] = []
            for slot, info in bare_pairs:
                rad = adaptive_slot_radius_mm(slot, params) * float(scale)
                if abs(q) < 1e-12:
                    rad = r0 * float(scale)
                pairs.append((info["edge"], rad))
                r_list.append(rad)
            print(
                f"  [slotFillet] oneshot scale={scale:g} "
                f"r=[{min(r_list):.3f},{max(r_list):.3f}] on {len(pairs)} edges...",
                flush=True,
            )
            trial = _try_fillet_per_edge(shape, pairs)
            trial = _as_single_solid(trial)
            topo = ocp_shape_topology(trial, check_brep=True)
            m1 = float(ocp_mass(trial))
            d = m1 - m0
            span = _bbox_span(trial)
            if int(topo.get("solids") or 0) != 1:
                raise RuntimeError(f"solids={topo.get('solids')}")
            if m1 < 0.95 * m0:
                raise RuntimeError(f"mass collapse {m1:.2f}")
            if d < -float(n_assigned) * 0.20:
                raise RuntimeError(f"dmass {d:+.3f}")
            if d > float(n_assigned) * float(params.max_dmass_step_mm3):
                raise RuntimeError(f"dmass {d:+.3f}")
            if any(span[k] > max_span for k in range(3)):
                raise RuntimeError(f"bbox_explode {span}")
            for k in range(3):
                if span[k] > float(span0[k]) + span_grow_tol:
                    raise RuntimeError(
                        f"span_grow[{k}] {span0[k]:.2f}->{span[k]:.2f}"
                    )
            cur = _step_roundtrip_solid(
                trial,
                mass_ref=m1,
                max_drift=max(float(params.max_step_mass_drift_mm3), 0.35),
            )
            final = cur
            used_r_summary = {
                "global_scale": float(scale),
                "r_min_mm": float(min(r_list)),
                "r_max_mm": float(max(r_list)),
                "r_mean_mm": float(sum(r_list) / len(r_list)),
                "per_slot_r_mm": [
                    {
                        "slot_id": s.slot_id,
                        "group": _slot_z_group(s),
                        "theta_deg": s.theta_deg,
                        "r_mm": adaptive_slot_radius_mm(s, params) * float(scale)
                        if abs(q) > 1e-12
                        else r0 * float(scale),
                    }
                    for s, _ in bare_pairs
                ],
            }
            print(
                f"  [slotFillet] oneshot OK scale={scale:g} dmass={d:+.3f} "
                f"valid={topo.get('brep_valid')} "
                f"span={tuple(round(x, 2) for x in span)}",
                flush=True,
            )
            break
        except Exception as exc:
            last_exc = exc
            print(f"  [slotFillet] scale={scale:g} fail: {exc}", flush=True)

    step_roundtrip_skipped = False
    opp_mode: str | None = None
    if final is None and abs(q) > 1.2:
        # Q≈1.5: full oneshot often invalid for STEP; opposite bot+top
        # +Δm pair can keep memory mass while STEP rb drifts.
        try:
            final, used_r_summary, n_opp = _fillet_q15_opposite_pair(
                shape, bare_pairs, params, m0=m0, span0=span0, max_span=max_span
            )
            n_assigned = int(n_opp)
            step_roundtrip_skipped = True
            opp_mode = "q15_opposite_pair"
            print(
                f"  [slotFillet] Q>1.2 opposite-pair fallback OK n={n_opp} "
                f"(STEP roundtrip skipped)",
                flush=True,
            )
        except Exception as exc:
            last_exc = exc
            print(f"  [slotFillet] opposite-pair fallback fail: {exc}", flush=True)

    if final is None:
        raise RuntimeError(f"adaptive oneshot fillet failed; last={last_exc}")

    # annotate slot_edge_info with used radii
    if used_r_summary is not None:
        by_id = {d["slot_id"]: d["r_mm"] for d in used_r_summary["per_slot_r_mm"]}
        for row in slot_edge_info:
            if row.get("assigned") and row["slot_id"] in by_id:
                row["r_used_mm"] = by_id[row["slot_id"]]

    span_f = _bbox_span(final)
    topo = ocp_shape_topology(final, check_brep=True)
    m1 = float(ocp_mass(final))
    mode = (
        opp_mode
        if opp_mode
        else ("slot_adaptive_oneshot" if abs(q) > 1e-12 else "slot_batch_fillet")
    )
    info = {
        "mode": mode,
        "period_factor": q,
        "n_slots": n_slots,
        "n_slots_filled": n_assigned,
        "n_slots_assigned": n_assigned,
        "coverage": float(n_assigned) / float(n_slots),
        "n_waist": sum(1 for s in assigned_slots if _slot_z_group(s) == "cross"),
        "r0_mm": r0,
        "r_used": used_r_summary,
        "n_fillets_total": n_assigned,
        "slot_edges": slot_edge_info,
        "mass_pre_mm3": m0,
        "mass_mm3": m1,
        "mass_delta_mm3": m1 - m0,
        "span0": span0,
        "span_final": span_f,
        "topology": topo,
        "step_roundtrip_skipped": step_roundtrip_skipped,
    }
    print(
        f"  [slotFillet] coverage {n_assigned}/{n_slots}  mass={m1:.3f}  "
        f"valid={topo.get('brep_valid')}",
        flush=True,
    )
    return final, info



def _fillet_q15_opposite_pair(
    shape: Any,
    bare_pairs: list[tuple[AcuteSlot, dict[str, Any]]],
    params: SlotFilletParams,
    *,
    m0: float,
    span0: tuple[float, float, float],
    max_span: float,
) -> tuple[Any, dict[str, Any], int]:
    """
    Pick one bot + one top edge with +Δm / safe bbox; oneshot MakeFillet.
    Skips STEP roundtrip (caller may soft-gate).
    """
    bots = [(s, info) for s, info in bare_pairs if _slot_z_group(s) == "bot"]
    tops = [(s, info) for s, info in bare_pairs if _slot_z_group(s) == "top"]
    if not bots or not tops:
        raise RuntimeError("need bot and top assigned edges")

    def _score(slot: AcuteSlot, info: dict[str, Any]) -> tuple[float, float] | None:
        best: tuple[float, float] | None = None
        for r in (0.05, 0.045, 0.04, 0.035, 0.055):
            try:
                t = _as_single_solid(_try_fillet_per_edge(shape, [(info["edge"], r)]))
                dm = float(ocp_mass(t)) - float(m0)
                sp = _bbox_span(t)
                if max(sp) > max_span or abs(dm) > 5.0:
                    continue
                if best is None or dm > best[0]:
                    best = (dm, float(r))
            except Exception:
                continue
        return best

    scored_b = [(s, info, _score(s, info)) for s, info in bots]
    scored_t = [(s, info, _score(s, info)) for s, info in tops]
    scored_b = [x for x in scored_b if x[2] is not None]
    scored_t = [x for x in scored_t if x[2] is not None]
    if not scored_b or not scored_t:
        raise RuntimeError("no +Δm-safe bot/top edge")
    scored_b.sort(key=lambda x: -x[2][0])  # type: ignore[index]
    scored_t.sort(key=lambda x: -x[2][0])  # type: ignore[index]
    sb, ib, (dmb, rb) = scored_b[0]  # type: ignore[misc]
    st, it, (dmt, rt) = scored_t[0]  # type: ignore[misc]
    pairs = [(ib["edge"], rb), (it["edge"], rt)]
    trial = _as_single_solid(_try_fillet_per_edge(shape, pairs))
    m1 = float(ocp_mass(trial))
    d = m1 - float(m0)
    sp = _bbox_span(trial)
    if max(sp) > max_span:
        raise RuntimeError(f"opposite-pair bbox {sp}")
    for k in range(3):
        if sp[k] > float(span0[k]) + 2.0:
            raise RuntimeError(
                f"opposite-pair span_grow[{k}] {span0[k]:.2f}->{sp[k]:.2f}"
            )
    if d < -0.5:
        raise RuntimeError(f"opposite-pair dmass {d:+.3f}")
    if d > 8.0:
        raise RuntimeError(f"opposite-pair dmass too large {d:+.3f}")
    summary = {
        "global_scale": 1.0,
        "r_min_mm": float(min(rb, rt)),
        "r_max_mm": float(max(rb, rt)),
        "r_mean_mm": float(0.5 * (rb + rt)),
        "per_slot_r_mm": [
            {
                "slot_id": sb.slot_id,
                "group": "bot",
                "theta_deg": sb.theta_deg,
                "r_mm": rb,
                "probe_dm": dmb,
            },
            {
                "slot_id": st.slot_id,
                "group": "top",
                "theta_deg": st.theta_deg,
                "r_mm": rt,
                "probe_dm": dmt,
            },
        ],
        "mode": "q15_opposite_pair",
    }
    return trial, summary, 2


def _try_slot_chamfer(
    shape: Any,
    bare_pairs: list[tuple[AcuteSlot, dict[str, Any]]],
    *,
    d_mm: float,
    m0: float,
    max_span: float,
) -> Any:
    from OCP.BRepFilletAPI import BRepFilletAPI_MakeChamfer

    mk = BRepFilletAPI_MakeChamfer(shape)
    for _s, info in bare_pairs:
        mk.Add(float(d_mm), info["edge"])
    mk.Build()
    if not mk.IsDone():
        raise RuntimeError("MakeChamfer not done")
    out = _as_single_solid(mk.Shape())
    if max(_bbox_span(out)) > max_span:
        raise RuntimeError("chamfer bbox explode")
    if float(ocp_mass(out)) < 0.95 * float(m0):
        raise RuntimeError("chamfer mass collapse")
    return out


def _ensure_written_solid(shape: Any) -> Any:
    """
    Some fillet/chamfer results write STEP as a shell (solids=0) even when
    in-memory topology reports 1 solid. Sew + MakeSolid before export.
    """
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeSolid, BRepBuilderAPI_Sewing
    from OCP.ShapeFix import ShapeFix_Solid
    from OCP.TopAbs import TopAbs_SHELL, TopAbs_SOLID
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS

    try:
        return _as_single_solid(shape)
    except Exception:
        pass

    sew = BRepBuilderAPI_Sewing(1e-4)
    sew.Add(shape)
    sew.Perform()
    sewn = sew.SewedShape()
    shells: list[Any] = []
    exp = TopExp_Explorer(sewn, TopAbs_SHELL)
    while exp.More():
        shells.append(TopoDS.Shell_s(exp.Current()))
        exp.Next()
    if len(shells) == 1:
        mk = BRepBuilderAPI_MakeSolid(shells[0])
        mk.Build()
        if mk.IsDone():
            sol = mk.Solid()
            try:
                fx = ShapeFix_Solid(sol)
                fx.Perform()
                sol = fx.Solid()
            except Exception:
                pass
            return sol
    # last resort: first solid explorer on sewn
    exp = TopExp_Explorer(sewn, TopAbs_SOLID)
    solids: list[Any] = []
    while exp.More():
        solids.append(TopoDS.Solid_s(exp.Current()))
        exp.Next()
    if len(solids) == 1:
        return solids[0]
    raise RuntimeError(f"cannot ensure solid (shells={len(shells)})")


def _write_step_hard_solid(
    shape: Any,
    path: str,
    *,
    mass_ref: float,
    max_drift: float,
    max_span_mm: float,
) -> Any:
    """
    Write STEP and require hard 1-solid readback.
    If first hop lands as a shell (common after chamfer), sew/MakeSolid and rewrite.
    Never keeps a non-solid STEP.
    """
    from src.export.ocp_paper_box_array_fuse import ocp_read_step_shape
    from OCP.IFSelect import IFSelect_RetDone
    from OCP.STEPControl import STEPControl_Reader

    def _check(rb: Any, mem_mass: float) -> Any:
        topo = ocp_shape_topology(rb, check_brep=True)
        if int(topo.get("solids") or 0) != 1:
            raise RuntimeError(f"readback solids={topo.get('solids')}")
        span = _bbox_span(rb)
        if any(span[k] > float(max_span_mm) for k in range(3)):
            raise RuntimeError(f"readback bbox {span}")
        rb_mass = float(ocp_mass(rb))
        if abs(rb_mass - float(mem_mass)) > float(max_drift):
            raise RuntimeError(f"mass drift mem={mem_mass:.3f} rb={rb_mass:.3f}")
        return _as_single_solid(rb)

    solid = _ensure_written_solid(shape)
    mem_mass = float(ocp_mass(solid))
    if abs(mem_mass - float(mass_ref)) > max(float(max_drift) * 2.0, 2.0):
        # allow chamfer mass change vs bare; only guard collapse
        if mem_mass < 0.9 * float(mass_ref):
            raise RuntimeError(f"mass collapse mem={mem_mass:.3f} ref={mass_ref:.3f}")
    span = _bbox_span(solid)
    if any(span[k] > float(max_span_mm) for k in range(3)):
        raise RuntimeError(f"pre-write bbox explode {span}")

    ocp_write_step(solid, path)
    try:
        return _check(ocp_read_step_shape(path), mem_mass)
    except Exception as first_exc:
        reader = STEPControl_Reader()
        st = reader.ReadFile(os.path.abspath(path))
        if int(st) != int(IFSelect_RetDone):
            raise RuntimeError(f"STEP soft reopen failed: {first_exc}") from first_exc
        reader.TransferRoots()
        raw = reader.OneShape()
        try:
            promoted = _ensure_written_solid(raw)
        except Exception as prom_exc:
            raise RuntimeError(
                f"STEP 0-solid and promote failed ({prom_exc}); first={first_exc}"
            ) from first_exc
        ocp_write_step(promoted, path)
        # Always compare to pre-write mem mass — promote must not strip geometry.
        return _check(ocp_read_step_shape(path), mem_mass)



def _q_slug(q: float) -> str:
    return f"{float(q):.1f}".replace(".", "p")


def export_slot_fillet(
    params: SlotFilletParams | None = None,
    *,
    out_dir: str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Bare fuse + slot-batch MakeFillet for any Q in {0, 0.5, 1, 1.5}."""
    params = params or SlotFilletParams()
    q = float(params.period_factor)
    out_dir = out_dir or default_exp_out_dir()
    os.makedirs(out_dir, exist_ok=True)

    rf_tag = str(params.r_blend_factor).replace(".", "p")
    slug = (
        f"exp_slotFillet_af{int(round(params.amplitude_mm))}q{_q_slug(q)}"
        f"_L{int(round(params.cell_size_mm))}"
        f"_d{str(params.rod_d_mm).replace('.', 'p')}"
        f"_rf{rf_tag}_1x1"
    )
    step_path = os.path.join(out_dir, f"{slug}.step")
    bare_path = os.path.join(out_dir, f"{slug}_bare.step")
    man_path = os.path.join(out_dir, f"{slug}_manifest.json")

    if (
        not force
        and os.path.isfile(step_path)
        and os.path.getsize(step_path) > 1000
        and os.path.isfile(man_path)
    ):
        with open(man_path, encoding="utf-8") as f:
            return json.load(f)

    fp = ExpFilletParams(
        cell_size_mm=params.cell_size_mm,
        rod_d_mm=params.rod_d_mm,
        amplitude_mm=params.amplitude_mm,
        period_factor=q,
        n_segments=params.n_segments,
    )
    print(f"  [slotFillet] bare fuse Q={q:g} ...", flush=True)
    bare, mass_bare, fuse_tag, fuse_attempts = fuse_pipes_unitcell_bare_ladder(fp)
    ocp_write_step(bare, bare_path)

    # MakeFillet can mutate the input BRep in-place; keep a pristine copy
    # for STEP-stable chamfer fallback.
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Copy

    bare_for_fillet = BRepBuilderAPI_Copy(bare).Shape()
    bare_for_chamfer = bare

    def _collect_unique_pairs(
        *, only_bot_top: bool, max_elen: float | None
    ) -> list[tuple[AcuteSlot, dict[str, Any]]]:
        slots = build_slots_for_params(params)
        used_mids: set[tuple[float, float, float]] = set()
        pairs: list[tuple[AcuteSlot, dict[str, Any]]] = []
        for slot in slots:
            if only_bot_top and _slot_z_group(slot) not in ("bot", "top"):
                continue
            info = _assign_edge_for_slot(
                bare_for_chamfer,
                slot,
                params,
                used_mids=used_mids,
                max_edge_len_mm=max_elen,
            )
            if info is None:
                continue
            used_mids.add(_mid_key(info["mid"]))
            pairs.append((slot, info))
        return pairs

    def _chamfer_sequential(
        pairs: list[tuple[AcuteSlot, dict[str, Any]]],
        *,
        d_list: list[float],
        reason: str,
        set_tag: str,
    ) -> tuple[Any, dict[str, Any]]:
        """Apply chamfer one edge at a time; hard-STEP gate after each."""
        import tempfile

        cur = bare_for_chamfer
        filled = 0
        used_d: list[float] = []
        max_span = float(params.cell_size_mm) * 1.35
        for slot, info0 in pairs:
            applied = False
            for d_mm in d_list:
                try:
                    info = _assign_edge_for_slot(
                        cur,
                        slot,
                        params,
                        used_mids=set(),
                        max_edge_len_mm=2.5 if abs(q) > 1.2 else None,
                    )
                    pair = (slot, info if info is not None else info0)
                    shaped = _try_slot_chamfer(
                        cur,
                        [pair],
                        d_mm=float(d_mm),
                        m0=float(ocp_mass(cur)),
                        max_span=max_span,
                    )
                    shaped = _ensure_written_solid(shaped)
                    with tempfile.TemporaryDirectory(prefix="chamfer_seq_") as td:
                        tmp = os.path.join(td, "t.step")
                        shaped = _write_step_hard_solid(
                            shaped,
                            tmp,
                            mass_ref=float(ocp_mass(shaped)),
                            max_drift=max(
                                float(params.max_step_mass_drift_mm3), 1.2
                            ),
                            max_span_mm=max_span,
                        )
                    cur = shaped
                    filled += 1
                    used_d.append(float(d_mm))
                    applied = True
                    break
                except Exception:
                    continue
            if not applied:
                continue
        if filled < 1:
            raise RuntimeError("sequential chamfer filled 0")
        slots = build_slots_for_params(params)
        info = {
            "mode": "slot_chamfer_fallback",
            "applied": True,
            "d_mm": float(sum(used_d) / len(used_d)),
            "d_per_edge_mm": used_d,
            "n_edges": filled,
            "n_slots_filled": filled,
            "n_slots": len(slots),
            "coverage": float(filled) / max(len(slots), 1),
            "edge_set": set_tag,
            "note": reason,
            "hard_step_ok": True,
            "sequential": True,
        }
        print(
            f"  [slotFillet] chamfer SEQ OK set={set_tag} n={filled} "
            f"d={used_d} (hard STEP)",
            flush=True,
        )
        return cur, info

    def _chamfer_on_bare(*, reason: str) -> tuple[Any, dict[str, Any]]:
        import tempfile

        slots = build_slots_for_params(params)
        max_span = float(params.cell_size_mm) * 1.35
        edge_sets: list[tuple[str, list[tuple[AcuteSlot, dict[str, Any]]]]] = []
        if abs(q) > 1.2:
            bt = _collect_unique_pairs(only_bot_top=True, max_elen=2.5)
            # Prefer 4-edge oneshot then sequential; d=0.04 hard-STEP proven
            if bt:
                edge_sets.append(("bot_top", bt))
            if len(bt) >= 2:
                edge_sets.append(("bot2", bt[:2]))
                edge_sets.append(("top2", bt[-2:]))
            d_list = [0.04, 0.05, 0.03, 0.06]
        else:
            allp = _collect_unique_pairs(only_bot_top=False, max_elen=None)
            edge_sets.append(("all", allp))
            d_list = [0.10, 0.08, 0.06, 0.12, 0.05]

        errors: list[str] = []
        for set_tag, pairs in edge_sets:
            if not pairs:
                continue
            for d_mm in d_list:
                try:
                    shaped = _try_slot_chamfer(
                        bare_for_chamfer,
                        pairs,
                        d_mm=float(d_mm),
                        m0=float(mass_bare),
                        max_span=max_span,
                    )
                    shaped = _ensure_written_solid(shaped)
                    with tempfile.TemporaryDirectory(prefix="chamfer_hard_") as td:
                        tmp = os.path.join(td, "t.step")
                        shaped = _write_step_hard_solid(
                            shaped,
                            tmp,
                            mass_ref=float(ocp_mass(shaped)),
                            max_drift=max(
                                float(params.max_step_mass_drift_mm3), 1.2
                            ),
                            max_span_mm=max_span,
                        )
                    info = {
                        "mode": "slot_chamfer_fallback",
                        "applied": True,
                        "d_mm": float(d_mm),
                        "n_edges": len(pairs),
                        "n_slots_filled": len(pairs),
                        "n_slots": len(slots),
                        "coverage": float(len(pairs)) / max(len(slots), 1),
                        "edge_set": set_tag,
                        "note": reason,
                        "hard_step_ok": True,
                    }
                    print(
                        f"  [slotFillet] chamfer OK set={set_tag} d={d_mm} "
                        f"n={len(pairs)} (hard STEP)",
                        flush=True,
                    )
                    return shaped, info
                except Exception as exc:
                    errors.append(f"{set_tag}@d={d_mm}: {exc}")
                    print(
                        f"  [slotFillet] chamfer skip {set_tag}@d={d_mm}: {exc}",
                        flush=True,
                    )

        # Q≈1.5: sequential one-edge hard STEP (maximize coverage)
        if abs(q) > 1.2:
            bt = _collect_unique_pairs(only_bot_top=True, max_elen=2.5)
            if bt:
                try:
                    return _chamfer_sequential(
                        bt,
                        d_list=d_list,
                        reason=reason,
                        set_tag="bot_top_seq",
                    )
                except Exception as exc:
                    errors.append(f"bot_top_seq: {exc}")
                    print(f"  [slotFillet] chamfer seq fail: {exc}", flush=True)

        raise RuntimeError(
            "chamfer fallback exhausted: " + " | ".join(errors[:8])
        )

    used_bare = False
    used_chamfer = False
    try:
        final, fillet_info = apply_slot_fillets(bare_for_fillet, params)
        # Q≈1.5 opposite-pair fillet often cannot hard-roundtrip STEP → chamfer
        if isinstance(fillet_info, dict) and fillet_info.get("step_roundtrip_skipped"):
            try:
                final = _step_roundtrip_solid(
                    _as_single_solid(final),
                    mass_ref=float(ocp_mass(final)),
                    max_drift=max(float(params.max_step_mass_drift_mm3), 1.2),
                )
                fillet_info["step_roundtrip_skipped"] = False
                print("  [slotFillet] opposite-pair hard STEP OK", flush=True)
            except Exception as rt_exc:
                print(
                    f"  [slotFillet] opposite-pair STEP fail → chamfer ({rt_exc})",
                    flush=True,
                )
                try:
                    final, fillet_info = _chamfer_on_bare(
                        reason=(
                            "MakeFillet STEP-unstable for this Q; "
                            "STEP-only chamfer fallback"
                        ),
                    )
                    used_chamfer = True
                except Exception as ch_exc:
                    raise RuntimeError(
                        f"opposite-pair STEP fail and chamfer fail: {ch_exc}"
                    ) from ch_exc
    except Exception as exc:
        print(f"  [slotFillet] failed ({exc})", flush=True)
        final = bare
        fillet_info = {"error": str(exc), "applied": False}
        # Q≈1 / Q≈1.5: STEP-stable chamfer interim (no STL)
        if abs(q - 1.0) < 0.05 or abs(q) > 1.2:
            try:
                final, fillet_info = _chamfer_on_bare(
                    reason=(
                        f"MakeFillet failed ({exc}); STEP-only chamfer fallback"
                    ),
                )
                used_chamfer = True
            except Exception as exc2:
                print(
                    f"  [slotFillet] chamfer fallback fail → bare ({exc2})",
                    flush=True,
                )
                final = bare
                used_bare = True
                fillet_info["chamfer_error"] = str(exc2)
        else:
            used_bare = True

    write_note = "ocp_direct"
    try:
        if used_chamfer:
            final = _write_step_hard_solid(
                final,
                step_path,
                mass_ref=float(mass_bare),
                max_drift=max(float(params.max_step_mass_drift_mm3), 1.2),
                max_span_mm=float(params.cell_size_mm) * 1.35,
            )
            write_note = "ocp_hard_after_promote_ok"
        else:
            final = _as_single_solid(final)
            mem_mass = float(ocp_mass(final))
            span_mem = _bbox_span(final)
            if any(span_mem[k] > float(params.cell_size_mm) * 1.35 for k in range(3)):
                raise RuntimeError(f"pre-write bbox explode {span_mem}")
            from src.export.ocp_paper_box_array_fuse import ocp_read_step_shape

            ocp_write_step(final, step_path)
            rb = ocp_read_step_shape(step_path)
            rb_topo = ocp_shape_topology(rb, check_brep=True)
            rb_span = _bbox_span(rb)
            rb_mass = float(ocp_mass(rb))
            if int(rb_topo.get("solids") or 0) != 1:
                raise RuntimeError(f"readback solids={rb_topo.get('solids')}")
            if any(rb_span[k] > float(params.cell_size_mm) * 1.35 for k in range(3)):
                raise RuntimeError(f"readback bbox {rb_span}")
            if abs(rb_mass - mem_mass) > max(float(params.max_step_mass_drift_mm3), 1.2):
                raise RuntimeError(f"mass drift mem={mem_mass:.3f} rb={rb_mass:.3f}")
            write_note = "ocp_direct_readback_ok"
            final = rb
    except Exception as exc:
        print(f"  [slotFillet] STEP fail → bare ({exc})", flush=True)
        final = bare
        used_bare = True
        used_chamfer = False
        fillet_info = {
            **(fillet_info if isinstance(fillet_info, dict) else {}),
            "step_error": str(exc),
            "reverted_to_bare": True,
        }
        ocp_write_step(final, step_path)
        write_note = "bare_after_bad_step"

    topo = ocp_shape_topology(final, check_brep=True)
    mass = float(ocp_mass(final))
    man = {
        "experiment": "acute_slot_fillet",
        "note": (
            "STEP-only export (no STL). "
            "Q=0/0.5: MakeFillet. "
            "Q≈1 / Q≈1.5: MakeFillet often STEP-unstable → MakeChamfer fallback."
        ),
        "params": asdict(params),
        "step_path": os.path.abspath(step_path),
        "bare_step_path": os.path.abspath(bare_path),
        "used_bare_fallback": used_bare,
        "used_chamfer_fallback": used_chamfer,
        "fuse": {
            "method": fuse_tag,
            "mass_bare_mm3": float(mass_bare),
            "attempts": fuse_attempts,
        },
        "fillet": fillet_info,
        "mass_mm3": mass,
        "topology": topo,
        "span": _bbox_span(final),
        "step_write": write_note,
    }
    with open(man_path, "w", encoding="utf-8") as f:
        json.dump(man, f, indent=2)

    cov = (fillet_info or {}).get("coverage")
    print(f"\n=== SLOT FILLET Q={q:g} ===", flush=True)
    print(
        f"  coverage={cov}  r_used={(fillet_info or {}).get('r_used_mm')}  "
        f"fallback={used_bare}  mass={mass:.3f}  "
        f"valid={topo.get('brep_valid')}  STEP={step_path}",
        flush=True,
    )
    return man


def export_slot_fillet_q0(
    params: SlotFilletParams | None = None,
    *,
    out_dir: str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    params = params or SlotFilletParams()
    if abs(float(params.period_factor)) > 1e-12:
        raise ValueError("export_slot_fillet_q0 requires period_factor=0")
    return export_slot_fillet(params, out_dir=out_dir, force=force)
