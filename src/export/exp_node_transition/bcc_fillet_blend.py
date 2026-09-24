"""Experimental scheme A: concave junction blend via OCC edge fillet (no node spheres).

Isolated from paper_box batch defaults. Build fused pipes → select hub/corner
edges → ``BRepFilletAPI_MakeFillet``.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np

from src.export.export_sw import _collect_solid_primitives
from src.export.exp_node_transition.bcc_explicit_cores import (
    default_exp_out_dir,
    export_exp_bcc_zslab_2x2x1,
)
from src.export.ocp_unitcell_fuse import (
    _box_from_bounds,
    export_q1_ocp_glue_unitcell,
    ocp_common,
    ocp_fuse_pair,
    ocp_heal_fused_solid,
    ocp_mass,
    ocp_pipe_along_points,
    ocp_shape_topology,
    ocp_write_step_via_gmsh_brep_heal,
)
from src.export.ocp_paper_box_array_fuse import ocp_read_step_shape
from src.export.unitcell_box_cut import (
    unitcell_box_bounds_mm,
    unitcell_octant_corners_mm,
)
from src.generator.hu_bai_bcc import HuBaiLatticeGenerator


@dataclass(frozen=True)
class ExpFilletParams:
    cell_size_mm: float = 20.0
    rod_d_mm: float = 2.0
    amplitude_mm: float = 2.0
    period_factor: float = 0.0
    n_segments: int = 24
    # Fillet radius as multiple of strut radius R
    r_blend_factor: float = 0.45
    # Select edges whose midpoint lies within this multiple of R from a node
    edge_select_factor: float = 2.8
    # Unit-cell stage: only centre (corners filleted after array fuse)
    fillet_centre: bool = True
    fillet_corners: bool = False
    fuse_fuzzy_mm: float = 0.02
    # Try these factors (descending) if the requested radius fails
    r_blend_fallback_factors: tuple[float, ...] = (0.45, 0.35, 0.25, 0.15)
    # After 2×2×1 fuse: fillet shared corners (multiplicity ≥ 2)
    array_fillet_shared_corners: bool = True
    array_nx: int = 2
    array_ny: int = 2
    array_nz: int = 1



def _strut_radius(params: ExpFilletParams) -> float:
    return 0.5 * float(params.rod_d_mm)


def load_fillet_pipe_parts(params: ExpFilletParams) -> list[tuple[str, tuple, float]]:
    gen = HuBaiLatticeGenerator(
        cell_size=float(params.cell_size_mm),
        rod_diameter=float(params.rod_d_mm),
        amplitude=float(params.amplitude_mm),
        period_factor=float(params.period_factor),
        n_segments=max(3, int(params.n_segments)),
    )
    gen.build_unitcell()
    nodes, beams, polylines = gen.get_data(copy=True)
    _, pipes_only = _collect_solid_primitives(
        nodes,
        beams,
        polylines=polylines,
        junction_spheres=False,
        trim_for_junctions=False,
        polyline_sweep="pipe",
    )
    pipe_parts = [p for p in pipes_only if p[0] == "pipe"]
    if len(pipe_parts) != 8:
        raise RuntimeError(f"expected 8 pipe parts, got {len(pipe_parts)}")
    return pipe_parts


def _fuse_pipes_unitcell(params: ExpFilletParams) -> tuple[Any, float, str]:
    """Build a single-solid pipe unit cell (no spheres) for fillet.

    Prefers OCP octant + centre_stub + GlueShift (stable for Q=0). Falls back
    through a bare-pipe recipe ladder (incl. both_end_extension for Q>0).
    """
    solid, mass, method, _attempts = fuse_pipes_unitcell_bare_ladder(params)
    return solid, mass, method


def fuse_pipes_unitcell_bare_ladder(
    params: ExpFilletParams,
) -> tuple[Any, float, str, list[dict[str, Any]]]:
    """
    No-sphere pipe unit cell via recipe ladder (experiment / adaptive path A).

    Q=1.5 Af=2: ``centre_stub`` fuse is empty; ``both_end_extension`` works.
    Returns (shape, mass, method_tag, attempt_log).
    """
    parts = load_fillet_pipe_parts(params)
    import tempfile

    q = abs(float(params.period_factor))
    fuzzy0 = max(0.02, float(params.fuse_fuzzy_mm))

    # Order: proven Q=0 first; Q>0 puts both_end_extension early.
    recipes: list[tuple[str, str, float]] = [
        ("centre_stub", "sequential_glue_shift", fuzzy0),
        ("centre_stub", "sequential_glue_full", max(fuzzy0, 0.05)),
        ("both_end_extension", "sequential_glue_shift", fuzzy0),
        ("both_end_extension", "sequential_glue_full", max(fuzzy0, 0.08)),
        ("both_end_extension", "batch_glue_shift", fuzzy0),
        ("centre_stub_corner_ext", "sequential_glue_shift", fuzzy0),
    ]
    if q > 1e-12:
        # Prefer path-extension (no geometric sphere) before centre_stub.
        recipes = [
            ("both_end_extension", "sequential_glue_shift", fuzzy0),
            ("both_end_extension", "sequential_glue_full", max(fuzzy0, 0.08)),
            ("both_end_extension", "batch_glue_shift", fuzzy0),
            ("centre_stub", "sequential_glue_shift", fuzzy0),
            ("centre_stub", "sequential_glue_full", max(fuzzy0, 0.05)),
            ("centre_stub_corner_ext", "sequential_glue_shift", fuzzy0),
        ]

    attempts: list[dict[str, Any]] = []
    tmp_dir = tempfile.mkdtemp(prefix="exp_bare_seed_")
    last_exc: Exception | None = None
    for pipe_mode, strategy, fuzzy in recipes:
        tmp_step = os.path.join(tmp_dir, f"{pipe_mode}_{strategy}.step")
        tag = f"ocp_{pipe_mode}_{strategy}"
        try:
            print(
                f"  [bare] try {pipe_mode} + {strategy} fuzzy={fuzzy:g} ...",
                flush=True,
            )
            rep = export_q1_ocp_glue_unitcell(
                parts,
                tmp_step,
                cell_size_mm=float(params.cell_size_mm),
                strategy=strategy,  # type: ignore[arg-type]
                fuzzy_mm=float(fuzzy),
                pipe_mode=pipe_mode,  # type: ignore[arg-type]
            )
            mass = float(rep.get("merged_mass_mm3") or 0.0)
            if mass <= 0.0:
                raise RuntimeError("empty mass")
            shape = ocp_read_step_shape(tmp_step)
            attempts.append(
                {
                    "recipe": tag,
                    "ok": True,
                    "mass_mm3": mass,
                    "pipe_mode": pipe_mode,
                    "strategy": strategy,
                    "fuzzy_mm": fuzzy,
                }
            )
            print(f"  [bare] OK {tag} mass={mass:.2f} mm3", flush=True)
            return shape, mass, tag, attempts
        except Exception as exc:
            last_exc = exc
            attempts.append(
                {
                    "recipe": tag,
                    "ok": False,
                    "error": str(exc)[:240],
                    "pipe_mode": pipe_mode,
                    "strategy": strategy,
                    "fuzzy_mm": fuzzy,
                }
            )
            print(f"  [bare] FAIL {tag}: {exc}", flush=True)

    # Q=0 L3 sequential fallback (historical)
    if q <= 1e-12:
        try:
            print("  [bare] try L3 sequential glue=off ...", flush=True)
            box = _box_from_bounds(unitcell_box_bounds_mm(params.cell_size_mm))
            cuts: list[Any] = []
            cut_sum = 0.0
            for i, part in enumerate(parts, start=1):
                cut = ocp_common(ocp_pipe_along_points(part[1], float(part[2])), box)
                m = ocp_mass(cut)
                if m <= 0.0:
                    raise RuntimeError(f"strut {i}: empty L3 cut")
                cuts.append(cut)
                cut_sum += m
            acc = cuts[0]
            for i, sh in enumerate(cuts[1:], start=2):
                acc = ocp_fuse_pair(
                    acc,
                    sh,
                    glue="off",
                    fuzzy_mm=0.05,
                    label=f"fillet-pipe-{i}",
                )
                mm = ocp_mass(acc)
                print(f"  [fillet] L3 fused 1..{i} mass={mm:.2f}", flush=True)
                if mm < 0.55 * cut_sum * (i / 8.0):
                    raise RuntimeError(f"L3 fuse mass collapse at step {i}")
            acc = ocp_heal_fused_solid(ocp_common(acc, box))
            mass = ocp_mass(acc)
            attempts.append({"recipe": "l3_sequential_glue_off", "ok": True, "mass_mm3": mass})
            return acc, mass, "l3_sequential_glue_off", attempts
        except Exception as exc:
            last_exc = exc
            attempts.append(
                {"recipe": "l3_sequential_glue_off", "ok": False, "error": str(exc)[:240]}
            )

    raise RuntimeError(
        f"bare pipe unitcell ladder failed after {len(attempts)} tries; "
        f"last={last_exc}; attempts={attempts}"
    )


def _edge_midpoint_mm(edge: Any) -> np.ndarray | None:
    from OCP.BRepAdaptor import BRepAdaptor_Curve

    try:
        ad = BRepAdaptor_Curve(edge)
        u0 = float(ad.FirstParameter())
        u1 = float(ad.LastParameter())
        p = ad.Value(0.5 * (u0 + u1))
        return np.array([float(p.X()), float(p.Y()), float(p.Z())], dtype=float)
    except Exception:
        return None


def _collect_edges_near_nodes(
    shape: Any,
    *,
    node_pts: list[np.ndarray],
    select_radius_mm: float,
) -> list[Any]:
    from OCP.TopAbs import TopAbs_EDGE
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS

    selected: list[Any] = []
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
        for npt in node_pts:
            if float(np.linalg.norm(mid - npt)) <= select_radius_mm:
                seen.add(key)
                selected.append(edge)
                break
    return selected


def _try_fillet(
    shape: Any,
    edges: list[Any],
    radius_mm: float,
) -> Any:
    from OCP.BRepFilletAPI import BRepFilletAPI_MakeFillet

    if not edges:
        raise ValueError("no edges to fillet")
    if radius_mm <= 0.0:
        raise ValueError("fillet radius must be > 0")

    mk = BRepFilletAPI_MakeFillet(shape)
    n_add = 0
    for edge in edges:
        try:
            mk.Add(float(radius_mm), edge)
            n_add += 1
        except Exception:
            continue
    if n_add == 0:
        raise RuntimeError("failed to add any edge to fillet builder")
    print(
        f"  [fillet] MakeFillet r={radius_mm:.3f} mm on {n_add}/{len(edges)} edge(s)...",
        flush=True,
    )
    mk.Build()
    if not mk.IsDone():
        raise RuntimeError("BRepFilletAPI_MakeFillet not done")
    out = mk.Shape()
    if ocp_mass(out) <= 0.0:
        raise RuntimeError("fillet produced empty solid")
    return out


def apply_junction_fillets(
    shape: Any,
    params: ExpFilletParams,
    *,
    node_pts: list[np.ndarray] | None = None,
    label: str = "fillet",
) -> tuple[Any, dict[str, Any]]:
    r = _strut_radius(params)
    r_req = float(params.r_blend_factor) * r
    select_r = float(params.edge_select_factor) * r

    if node_pts is None:
        nodes: list[np.ndarray] = []
        if params.fillet_centre:
            nodes.append(np.zeros(3, dtype=float))
        if params.fillet_corners:
            for c in unitcell_octant_corners_mm(params.cell_size_mm):
                nodes.append(np.asarray(c, dtype=float))
    else:
        nodes = [np.asarray(p, dtype=float) for p in node_pts]

    edges = _collect_edges_near_nodes(shape, node_pts=nodes, select_radius_mm=select_r)
    print(
        f"  [{label}] candidate edges near nodes: {len(edges)} "
        f"(select_r={select_r:.3f} mm, nodes={len(nodes)})",
        flush=True,
    )
    if not edges:
        raise RuntimeError(f"{label}: no candidate edges found near nodes")

    factors = list(params.r_blend_fallback_factors)
    if params.r_blend_factor not in factors:
        factors = [params.r_blend_factor, *factors]
    seen_f: set[float] = set()
    try_factors: list[float] = []
    for f in factors:
        ff = float(f)
        if ff in seen_f or ff <= 0.0:
            continue
        seen_f.add(ff)
        try_factors.append(ff)

    errors: list[str] = []
    for fac in try_factors:
        rad = fac * r
        try:
            filleted = _try_fillet(shape, edges, rad)
            topo = ocp_shape_topology(filleted)
            if int(topo.get("solids") or 0) != 1:
                raise RuntimeError(f"fillet solids={topo.get('solids')}")
            report = {
                "r_blend_mm": rad,
                "r_blend_factor_used": fac,
                "n_candidate_edges": len(edges),
                "n_nodes": len(nodes),
                "select_radius_mm": select_r,
                "fillet_centre": params.fillet_centre if node_pts is None else None,
                "fillet_corners": params.fillet_corners if node_pts is None else None,
                "topology_after": topo,
                "mass_after_mm3": ocp_mass(filleted),
                "label": label,
            }
            print(
                f"  [{label}] OK factor={fac:g} r={rad:.3f} mm "
                f"mass={report['mass_after_mm3']:.2f}",
                flush=True,
            )
            return filleted, report
        except Exception as exc:
            msg = f"factor={fac:g}: {exc}"
            errors.append(msg)
            print(f"  [{label}] fail {msg}", flush=True)

    raise RuntimeError(f"{label}: all fillet radii failed: {errors}")


def export_exp_bcc_fillet_unitcell(
    out_step: str,
    params: ExpFilletParams | None = None,
    *,
    write_manifest: bool = True,
    also_write_pre_fillet: bool = True,
) -> dict[str, Any]:
    """Export scheme-A 1×1 STEP (pipes fuse + junction fillet). No spheres."""
    params = params or ExpFilletParams()
    out_step = os.path.abspath(out_step)
    os.makedirs(os.path.dirname(out_step) or ".", exist_ok=True)

    print(f"\n=== EXP scheme-A fillet → {out_step} ===", flush=True)
    solid, mass_pre, seed_method = _fuse_pipes_unitcell(params)
    topo_pre = ocp_shape_topology(solid)

    if also_write_pre_fillet:
        pre_path = os.path.splitext(out_step)[0] + "_pre_fillet.step"
        ocp_write_step_via_gmsh_brep_heal(ocp_heal_fused_solid(solid), pre_path)
        print(f"  [fillet] pre-fillet STEP → {pre_path}", flush=True)
    else:
        pre_path = None

    filleted, fillet_rep = apply_junction_fillets(solid, params)
    # Keep paper_box L³ envelope
    box = _box_from_bounds(unitcell_box_bounds_mm(params.cell_size_mm))
    filleted = ocp_common(filleted, box)
    filleted = ocp_heal_fused_solid(filleted)
    step_rb = ocp_write_step_via_gmsh_brep_heal(filleted, out_step)

    report: dict[str, Any] = {
        "experiment": "bcc_scheme_a_fillet",
        "params": asdict(params),
        "strut_radius_mm": _strut_radius(params),
        "seed_method": seed_method,
        "mass_pre_fillet_mm3": mass_pre,
        "topology_pre": topo_pre,
        "pre_fillet_step": pre_path,
        "fillet": fillet_rep,
        "merged_mass_mm3": ocp_mass(filleted),
        "topology": ocp_shape_topology(filleted),
        "step_path": out_step,
        "step_readback_topology": step_rb,
        "main_path_untouched": True,
        "no_junction_spheres": True,
    }
    if write_manifest:
        man_path = os.path.splitext(out_step)[0] + "_manifest.json"
        with open(man_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, default=str)
        report["manifest_path"] = man_path
    print(
        f"  [fillet] 1x1 mass {mass_pre:.2f} → {report['merged_mass_mm3']:.2f} mm3 "
        f"(Δ={report['merged_mass_mm3'] - mass_pre:+.2f})",
        flush=True,
    )
    return report


def shared_corner_nodes_world_mm(
    *,
    cell_size_mm: float,
    nx: int,
    ny: int,
    nz: int,
    min_multiplicity: int = 2,
) -> list[np.ndarray]:
    """World positions of cube corners shared by ≥``min_multiplicity`` cells."""
    from src.export.export_sw import _lattice_cell_offset_xyz_mm

    L = float(cell_size_mm)
    h = 0.5 * L
    local_corners = unitcell_octant_corners_mm(L)
    # key → (count, representative point)
    buckets: dict[tuple[int, int, int], list[np.ndarray]] = {}
    for iz in range(int(nz)):
        for iy in range(int(ny)):
            for ix in range(int(nx)):
                ox, oy, oz = _lattice_cell_offset_xyz_mm(
                    ix,
                    iy,
                    iz,
                    nx=int(nx),
                    ny=int(ny),
                    nz=int(nz),
                    cell_size=L,
                    origin_centered=False,
                )
                for c in local_corners:
                    wx = float(c[0]) + float(ox)
                    wy = float(c[1]) + float(oy)
                    wz = float(c[2]) + float(oz)
                    key = (round(wx * 1000), round(wy * 1000), round(wz * 1000))
                    buckets.setdefault(key, []).append(np.array([wx, wy, wz], dtype=float))

    shared: list[np.ndarray] = []
    for pts in buckets.values():
        if len(pts) >= int(min_multiplicity):
            shared.append(np.mean(np.stack(pts, axis=0), axis=0))
    shared.sort(key=lambda p: (float(p[0]), float(p[1]), float(p[2])))
    return shared


def export_exp_fillet_array_then_shared_corners(
    seed_1x1_step: str,
    out_array_step: str,
    params: ExpFilletParams | None = None,
    *,
    force: bool = False,
    write_manifest: bool = True,
) -> dict[str, Any]:
    """2×2×1 fuse first, then fillet shared corner nodes on the assembled solid."""
    from src.export.ocp_paper_box_array_fuse import ocp_read_step_shape

    params = params or ExpFilletParams()
    seed_1x1_step = os.path.abspath(seed_1x1_step)
    out_array_step = os.path.abspath(out_array_step)
    os.makedirs(os.path.dirname(out_array_step) or ".", exist_ok=True)

    pre_path = os.path.splitext(out_array_step)[0] + "_pre_corner_fillet.step"
    nx, ny, nz = int(params.array_nx), int(params.array_ny), int(params.array_nz)

    print("\n=== EXP scheme-A: array fuse then shared-corner fillet ===", flush=True)
    print(f"  seed 1x1: {seed_1x1_step}", flush=True)

    # Stage 1: fuse array (reuse existing z-slab for nz=1)
    if nz != 1:
        raise ValueError("array post-fillet smoke currently supports nz=1 only")
    fuse_rep = export_exp_bcc_zslab_2x2x1(
        seed_1x1_step,
        pre_path,
        cell_size_mm=float(params.cell_size_mm),
        force=force,
    )
    # export_exp_bcc_zslab hardcodes 2x2 — if nx/ny differ, still OK for default 2x2x1
    if nx != 2 or ny != 2:
        print(
            f"  [WARN] zslab helper is 2x2; params asked {nx}x{ny}x{nz}",
            flush=True,
        )

    shape = ocp_read_step_shape(pre_path)
    mass_pre = ocp_mass(shape)
    print(f"  [fillet] fused array mass={mass_pre:.2f} mm3", flush=True)

    if not params.array_fillet_shared_corners:
        # Just copy/rename
        if force or not os.path.isfile(out_array_step):
            import shutil

            shutil.copy2(pre_path, out_array_step)
        return {
            "experiment": "bcc_scheme_a_array_no_corner_fillet",
            "step_path": out_array_step,
            "pre_corner_fillet_step": pre_path,
            "fuse_report": fuse_rep,
            "merged_mass_mm3": mass_pre,
            "skipped_corner_fillet": True,
        }

    shared = shared_corner_nodes_world_mm(
        cell_size_mm=float(params.cell_size_mm),
        nx=nx,
        ny=ny,
        nz=nz,
        min_multiplicity=2,
    )
    print(
        f"  [fillet] shared corner nodes (mult≥2): {len(shared)}",
        flush=True,
    )
    for i, p in enumerate(shared):
        print(
            f"    node {i}: ({p[0]:+.3f}, {p[1]:+.3f}, {p[2]:+.3f})",
            flush=True,
        )
    if not shared:
        raise RuntimeError("no shared corners found for array fillet")

    filleted, fillet_rep = apply_junction_fillets(
        shape,
        params,
        node_pts=shared,
        label="array-corner-fillet",
    )
    filleted = ocp_heal_fused_solid(filleted)
    mass_after = ocp_mass(filleted)
    step_rb = ocp_write_step_via_gmsh_brep_heal(filleted, out_array_step)

    report: dict[str, Any] = {
        "experiment": "bcc_scheme_a_fuse_then_shared_corner_fillet",
        "params": asdict(params),
        "seed_1x1_step": seed_1x1_step,
        "pre_corner_fillet_step": pre_path,
        "step_path": out_array_step,
        "fuse_report": fuse_rep,
        "shared_corner_nodes": [p.tolist() for p in shared],
        "mass_pre_corner_fillet_mm3": mass_pre,
        "fillet": fillet_rep,
        "merged_mass_mm3": mass_after,
        "mass_delta_mm3": mass_after - mass_pre,
        "topology": ocp_shape_topology(filleted),
        "step_readback_topology": step_rb,
        "main_path_untouched": True,
        "no_junction_spheres": True,
    }
    if write_manifest:
        man_path = os.path.splitext(out_array_step)[0] + "_manifest.json"
        with open(man_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, default=str)
        report["manifest_path"] = man_path
    print(
        f"  [fillet] array mass {mass_pre:.2f} → {mass_after:.2f} mm3 "
        f"(Δ={mass_after - mass_pre:+.2f}) → {out_array_step}",
        flush=True,
    )
    return report
