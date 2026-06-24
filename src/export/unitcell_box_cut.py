"""Paper-style unit cell: pipe sweep + virtual hexahedron boolean cut (no junction spheres).

Same pipe-first OCC sweep as ``export_lattice_step_occ`` (CorrectedFrenet + spline wire),
but the RVE boundary is a cube L×L×L centred on the cell origin. Strut ends on cell
faces/edges/corners become planar cut caps instead of nodal sphere connections.
"""

from __future__ import annotations

import os
from typing import Any

from src.export.export_sw import (
    _collect_solid_primitives,
    _configure_occ_for_fuse,
    _finalize_occ_step_write,
    _occ_fuse_dimtags,
    _occ_fuse_unitcell_solid,
    _occ_remove_all_volumes_except,
    _occ_volumes_mass,
    _rewrite_and_analyze_fused_step,
)


def unitcell_box_bounds_mm(cell_size_mm: float) -> tuple[float, float, float, float, float, float]:
    """Origin-centred RVE box (matches HuBaiLatticeGenerator single-cell block)."""
    h = 0.5 * float(cell_size_mm)
    return (-h, h, -h, h, -h, h)


def _occ_add_unitcell_box(cell_size_mm: float) -> tuple[int, int]:
    import gmsh

    h = 0.5 * float(cell_size_mm)
    side = float(cell_size_mm)
    tag = gmsh.model.occ.addBox(-h, -h, -h, side, side, side)
    return (3, int(tag))


def _occ_fuse_lattice_for_box_cut(
    pipe_parts: list[tuple[str, tuple, float]],
    junction_parts: list[tuple[str, tuple, float]],
    *,
    progress_label: str = "pipe-fuse",
) -> tuple[list[tuple[int, int]], str]:
    """
    Fuse struts for paper box-cut export.

    Prefer pipe-only merge (no junction spheres). Fall back to the verified
    seed-export path (pipe-first + junction spheres) when high-Q spline pipes
    fail to fuse without nodal overlap geometry.
    """
    try:
        from src.export.export_sw import _occ_fuse_unitcell_pipe_first

        vols = _occ_fuse_unitcell_pipe_first(
            pipe_parts,
            progress_label=progress_label,
            per_strut_corner_caps=False,
        )
        print(f"  {progress_label}: strategy=pipe-first (no junction spheres)", flush=True)
        return vols, "pipe-first (no junction spheres)"
    except Exception as exc:
        print(
            f"  {progress_label}: pipe-only fuse failed ({exc}); "
            "retry with junction spheres (clipped by RVE box)...",
            flush=True,
        )
    vols = _occ_fuse_unitcell_solid(junction_parts, progress_label=progress_label)
    print(f"  {progress_label}: strategy=seed fuse + RVE clip", flush=True)
    return vols, "seed pipe-first + junction spheres (RVE clip removes boundary caps)"


def _occ_intersect_volumes_with_box(
    lattice_vols: list[tuple[int, int]],
    cell_size_mm: float,
    *,
    progress_label: str = "box-cut",
) -> tuple[int, int]:
    """Boolean-intersect fused lattice volume(s) with the virtual RVE hexahedron."""
    import gmsh

    if not lattice_vols:
        raise RuntimeError(f"{progress_label}: no lattice volumes to clip")

    box_vol = _occ_add_unitcell_box(cell_size_mm)
    gmsh.model.occ.synchronize()
    print(
        f"  {progress_label}: intersect {len(lattice_vols)} lattice volume(s) "
        f"with L={cell_size_mm:g} mm RVE box...",
        flush=True,
    )
    out, _ = gmsh.model.occ.intersect(lattice_vols, [box_vol])
    gmsh.model.occ.synchronize()
    cut_vols = [(3, int(t)) for dim, t in out if dim == 3]
    if not cut_vols:
        raise RuntimeError(f"{progress_label}: box intersect produced no volume")
    if len(cut_vols) > 1:
        print(
            f"  {progress_label}: unify {len(cut_vols)} fragment(s) after intersect...",
            flush=True,
        )
        cut_vols = _occ_fuse_dimtags(cut_vols, progress_label=progress_label)
    keep = cut_vols[0]
    _occ_remove_all_volumes_except(keep)
    return keep


def _bbox_mm(vol: tuple[int, int]) -> tuple[float, float, float, float, float, float]:
    import gmsh

    return tuple(float(x) for x in gmsh.model.occ.getBoundingBox(*vol))


def export_unitcell_step_paper_box_cut(
    nodes: list,
    beams: list,
    path: str,
    *,
    polylines: list[dict] | None = None,
    cell_size_mm: float = 20.0,
) -> dict[str, Any]:
    """
    Export one fused unit-cell STEP using paper-style virtual hexahedron cutting.

    Pipeline:
    1. Eight curved pipe sweeps (centre → corner), no junction spheres.
    2. Pipe-first boolean fuse (same OCC path as verified seed export).
    3. Single intersect with cube ``[-L/2, L/2]³`` → planar caps on the RVE boundary.
    """
    try:
        import gmsh
    except ImportError as exc:
        raise ImportError(
            "Paper box-cut STEP export requires gmsh. Install: pip install gmsh"
        ) from exc

    _, pipe_parts_only = _collect_solid_primitives(
        nodes,
        beams,
        polylines=polylines,
        junction_spheres=False,
        trim_for_junctions=False,
        polyline_sweep="pipe",
    )
    _, junction_parts = _collect_solid_primitives(
        nodes,
        beams,
        polylines=polylines,
        junction_spheres=True,
        trim_for_junctions=False,
        polyline_sweep="pipe",
    )
    pipe_parts = [p for p in pipe_parts_only if p[0] == "pipe"]
    pipe_count = len(pipe_parts)
    if pipe_count == 0:
        raise ValueError("No pipe primitives for paper box-cut export.")

    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    expected = unitcell_box_bounds_mm(cell_size_mm)

    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add(os.path.splitext(os.path.basename(path))[0] or "unitcell_box_cut")
        _configure_occ_for_fuse()

        print(
            f"  Paper box-cut: {pipe_count} pipe(s), L={cell_size_mm:g} mm, "
            "junction spheres=off...",
            flush=True,
        )
        fused_vols, fuse_strategy = _occ_fuse_lattice_for_box_cut(
            pipe_parts,
            junction_parts,
            progress_label="intra-fuse",
        )
        pre_mass = _occ_volumes_mass(fused_vols)

        cut_vol = _occ_intersect_volumes_with_box(
            fused_vols,
            cell_size_mm,
            progress_label="box-cut",
        )
        post_mass = float(gmsh.model.occ.getMass(3, int(cut_vol[1])))
        bbox = _bbox_mm(cut_vol)

        step_report = _finalize_occ_step_write(path, fuse=True, validate_step=False)
        fused_volume_count = int(step_report.get("solid_count", 0))
    finally:
        gmsh.finalize()

    step_report = _rewrite_and_analyze_fused_step(path, prior=step_report)
    fused_volume_count = int(step_report.get("solid_count", 0))

    tol = max(0.5, 0.05 * float(cell_size_mm))
    h = 0.5 * float(cell_size_mm)
    overshoot = max(
        (-h) - bbox[0],
        bbox[1] - h,
        (-h) - bbox[2],
        bbox[3] - h,
        (-h) - bbox[4],
        bbox[5] - h,
    )
    bbox_ok = overshoot <= tol

    return {
        "step_path": path,
        "pipe_count": pipe_count,
        "cell_size_mm": float(cell_size_mm),
        "fused_volume_count": fused_volume_count,
        "step_product_count": step_report.get("product_count"),
        "step_solidworks_safe": step_report.get("solidworks_safe"),
        "fuse_strategy": f"{fuse_strategy} + RVE box intersect",
        "mass_mm3_before_cut": pre_mass,
        "mass_mm3_after_cut": post_mass,
        "mass_ratio_after_cut": post_mass / pre_mass if pre_mass > 0.0 else None,
        "bbox_mm": bbox,
        "bbox_expected_mm": expected,
        "bbox_overshoot_mm": overshoot,
        "bbox_overshoot_tolerance_mm": tol,
        "bbox_within_rve": bbox_ok,
        "node_count": len(nodes),
        "beam_count": len(beams),
        "polyline_count": len(polylines or []),
        "method": "gmsh_occ_pipe_box_cut",
    }
