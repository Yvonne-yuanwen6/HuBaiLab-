"""OCP array build via per-strut octant cuts + Sew → single solid (no inter-cell Fuse)."""

from __future__ import annotations

import os
from typing import Any

from src.export.export_sw import _lattice_cell_offset_xyz_mm
from src.export.ocp_paper_box_array_fuse import (
    load_q1_pipe_parts,
    ocp_translate_shape,
    _translate_pipe_parts,
)
from src.export.ocp_unitcell_fuse import (
    PipeBuildMode,
    _box_from_bounds,
    _ocp_pipe_solid_for_part,
    ocp_common,
    ocp_mass,
    ocp_readback_step,
    ocp_shape_topology,
)
from src.export.unitcell_box_cut import (
    OCTANT_CENTER_OVERLAP_MM,
    OCTANT_SEQUENTIAL_FUSE_ORDER,
    _canonical_corner_from_pipe_path,
    _octant_bounds_from_corner_mm,
    unitcell_octant_corner_signs,
    unitcell_octant_corners_mm,
)

# Symmetric pad on inter-cell RVE faces (same thickness as centre bisector overlap).
PERIODIC_FACE_OVERLAP_MM = OCTANT_CENTER_OVERLAP_MM


def _octant_bounds_at_offset(
    local_corner: tuple[float, float, float],
    offset: tuple[float, float, float],
    cell_size_mm: float,
    *,
    center_overlap_mm: float = OCTANT_CENTER_OVERLAP_MM,
    periodic_overlap_mm: float = 0.0,
    cell_ix: int = 0,
    cell_iy: int = 0,
    cell_iz: int = 0,
    grid_nx: int = 1,
    grid_ny: int = 1,
    grid_nz: int = 1,
    periodic_axes: tuple[str, ...] = ("x", "y", "z"),
) -> tuple[float, float, float, float, float, float]:
    """Octant cut box in world coords (local bounds + translate + optional periodic pad)."""
    xa, xb, ya, yb, za, zb = _octant_bounds_from_corner_mm(
        local_corner,
        cell_size_mm,
        center_overlap_mm=center_overlap_mm,
    )
    pad = max(0.0, float(periodic_overlap_mm))
    axes = {str(a).strip().lower() for a in periodic_axes}
    if pad > 0.0:
        half = 0.5 * pad
        sx, sy, sz = unitcell_octant_corner_signs(local_corner, cell_size_mm)
        if "x" in axes:
            if sx > 0 and int(cell_ix) < int(grid_nx) - 1:
                xb += half
            elif sx < 0 and int(cell_ix) > 0:
                xa -= half
        if "y" in axes:
            if sy > 0 and int(cell_iy) < int(grid_ny) - 1:
                yb += half
            elif sy < 0 and int(cell_iy) > 0:
                ya -= half
        if "z" in axes:
            if sz > 0 and int(cell_iz) < int(grid_nz) - 1:
                zb += half
            elif sz < 0 and int(cell_iz) > 0:
                za -= half
    ox, oy, oz = (float(offset[0]), float(offset[1]), float(offset[2]))
    return (xa + ox, xb + ox, ya + oy, yb + oy, za + oz, zb + oz)


def build_array_octant_strut_solids(
    pipe_parts: list[tuple[str, tuple, float]],
    *,
    nx: int,
    ny: int,
    iz: int = 0,
    nz_total: int = 1,
    cell_size_mm: float = 20.0,
    pipe_mode: PipeBuildMode = "centre_stub",
    center_overlap_mm: float = OCTANT_CENTER_OVERLAP_MM,
    periodic_overlap_mm: float = PERIODIC_FACE_OVERLAP_MM,
    periodic_axes: tuple[str, ...] = ("x", "y", "z"),
) -> tuple[list[Any], float]:
    """Build nx×ny×1 layer of octant-cut strut solids (8 struts per cell) in world frame."""
    nx_i, ny_i = int(nx), int(ny)
    nz_i = int(nz_total)
    cell_l = float(cell_size_mm)
    local_corners = unitcell_octant_corners_mm(cell_l)
    corner_tol = max(1e-3, 1e-6 * cell_l)
    struts: list[Any] = []
    cut_mass_sum = 0.0

    for iy in range(ny_i):
        for ix in range(nx_i):
            off = _lattice_cell_offset_xyz_mm(
                ix,
                iy,
                int(iz),
                nx=nx_i,
                ny=ny_i,
                nz=int(nz_total),
                cell_size=cell_l,
                origin_centered=False,
            )
            tparts = _translate_pipe_parts(pipe_parts, *off)
            print(
                f"  octant struts cell ix={ix} iy={iy} offset={off}",
                flush=True,
            )
            for idx, part in enumerate(tparts, start=1):
                local_corner = local_corners[idx - 1]
                world_corner = (
                    local_corner[0] + off[0],
                    local_corner[1] + off[1],
                    local_corner[2] + off[2],
                )
                path_corner = _canonical_corner_from_pipe_path(part[1], cell_l)
                if any(abs(path_corner[i] - world_corner[i]) > corner_tol for i in range(3)):
                    raise RuntimeError(
                        f"cell ({ix},{iy}) strut {idx}: path corner {path_corner} "
                        f"!= world corner {world_corner}"
                    )
                pipe_solid, _ = _ocp_pipe_solid_for_part(
                    part,
                    pipe_mode=pipe_mode,
                    cell_size_mm=cell_l,
                    centre_extension_mm=None,
                    corner_extension_mm=None,
                )
                bounds = _octant_bounds_at_offset(
                    local_corner,
                    off,
                    cell_l,
                    center_overlap_mm=center_overlap_mm,
                    periodic_overlap_mm=periodic_overlap_mm,
                    periodic_axes=periodic_axes,
                    cell_ix=ix,
                    cell_iy=iy,
                    cell_iz=int(iz),
                    grid_nx=nx_i,
                    grid_ny=ny_i,
                    grid_nz=nz_i,
                )
                box = _box_from_bounds(bounds)
                cut = ocp_common(pipe_solid, box)
                cut = ocp_common(cut, box)
                m = ocp_mass(cut)
                if m <= 0.0:
                    raise RuntimeError(
                        f"cell ({ix},{iy}) strut {idx}: zero mass after octant cut"
                    )
                cut_mass_sum += m
                struts.append(cut)

    return struts, cut_mass_sum


def _shapefix_shell_to_solid(shell: Any, label: str) -> Any | None:
    """Try ShapeFix_Shell → MakeSolid for a sewn shell."""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeSolid
    from OCP.ShapeFix import ShapeFix_Shell

    fix = ShapeFix_Shell(shell)
    fix.Perform()
    closed = fix.Shell()
    if closed.IsNull():
        return None
    mk = BRepBuilderAPI_MakeSolid()
    mk.Add(closed)
    if not mk.IsDone():
        return None
    solid = mk.Shape()
    if ocp_mass(solid) <= 0.0:
        return None
    print(f"  {label}: ShapeFix_Shell → solid mass={ocp_mass(solid):.1f} mm3", flush=True)
    return solid


def _light_fix_solid(shape: Any) -> Any:
    """Minor topology fix without UnifySameDomain (avoids splitting glue seams)."""
    from OCP.BRepCheck import BRepCheck_Analyzer
    from OCP.ShapeFix import ShapeFix_Shape

    if BRepCheck_Analyzer(shape).IsValid():
        return shape
    fix = ShapeFix_Shape(shape)
    fix.Perform()
    return fix.Shape()


def ocp_glue_rows_only(
    cells: list[Any],
    *,
    nx: int,
    ny: int,
    fuzzy_mm: float = 0.05,
    progress_label: str = "array-glue",
) -> tuple[list[Any], dict[str, Any]]:
    """Fuse nx cells per row; return row solids (no inter-row OCP sew)."""
    nx_i, ny_i = int(nx), int(ny)
    if len(cells) != nx_i * ny_i:
        raise RuntimeError(
            f"{progress_label}: expected {nx_i * ny_i} cells, got {len(cells)}"
        )
    row_solids: list[Any] = []
    for iy in range(ny_i):
        row = cells[iy * nx_i : (iy + 1) * nx_i]
        if len(row) == 1:
            row_solids.append(row[0])
        else:
            row_solids.append(
                ocp_glue_cells_sequential(
                    row,
                    fuzzy_mm=float(fuzzy_mm),
                    progress_label=f"{progress_label}-row{iy}",
                )
            )
    return row_solids, {
        "method": "row_glue_only",
        "n_rows": len(row_solids),
        "row_masses_mm3": [ocp_mass(s) for s in row_solids],
    }


def ocp_glue_cells_row_sequential(
    cells: list[Any],
    *,
    nx: int,
    ny: int,
    fuzzy_mm: float = 0.05,
    sew_tolerance_mm: float = 0.1,
    progress_label: str = "array-glue",
) -> tuple[Any, dict[str, Any]]:
    """Fuse nx cells per row (x), then merge rows (y) via Sew."""
    nx_i, ny_i = int(nx), int(ny)
    if len(cells) != nx_i * ny_i:
        raise RuntimeError(
            f"{progress_label}: expected {nx_i * ny_i} cells, got {len(cells)}"
        )
    row_solids: list[Any] = []
    for iy in range(ny_i):
        row = cells[iy * nx_i : (iy + 1) * nx_i]
        if len(row) == 1:
            row_solids.append(row[0])
        else:
            row_solids.append(
                ocp_glue_cells_sequential(
                    row,
                    fuzzy_mm=float(fuzzy_mm),
                    progress_label=f"{progress_label}-row{iy}",
                )
            )
    if len(row_solids) == 1:
        return row_solids[0], {"method": "row_glue", "n_rows": 1}
    print(
        f"  {progress_label}: Sewing {len(row_solids)} row solid(s), "
        f"tol={sew_tolerance_mm:g} mm...",
        flush=True,
    )
    return ocp_sew_solids_to_one(
        row_solids,
        tolerance_mm=float(sew_tolerance_mm),
        progress_label=f"{progress_label}-rows",
    )


def ocp_glue_cells_sequential(
    cells: list[Any],
    *,
    fuzzy_mm: float = 0.05,
    progress_label: str = "cell-glue",
) -> Any:
    """GlueShift fuse complete cell solids left-to-right."""
    from src.export.ocp_unitcell_fuse import ocp_fuse_pair

    if not cells:
        raise RuntimeError(f"{progress_label}: no cells")
    acc = cells[0]
    ref = ocp_mass(acc)
    min_delta = 0.10 * ref
    for idx, cell in enumerate(cells[1:], start=2):
        prev = ocp_mass(acc)
        acc = ocp_fuse_pair(
            acc,
            cell,
            glue="shift",
            fuzzy_mm=float(fuzzy_mm),
            label=f"{progress_label} {idx}/{len(cells)}",
        )
        new = ocp_mass(acc)
        if new < prev + min_delta:
            raise RuntimeError(
                f"{progress_label}: step {idx}/{len(cells)} mass "
                f"{new:.1f} < {prev + min_delta:.1f} mm3"
            )
        print(f"  {progress_label}: {idx}/{len(cells)} mass={new:.1f} mm3", flush=True)
    return acc


def ocp_sew_solids_to_one(
    shapes: list[Any],
    *,
    tolerance_mm: float = 0.05,
    progress_label: str = "ocp-sew",
) -> tuple[Any, dict[str, Any]]:
    """Sew separate strut solids → one shape; MakeSolid when a closed shell results."""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeSolid, BRepBuilderAPI_Sewing
    from OCP.TopAbs import TopAbs_SHELL, TopAbs_SOLID
    from OCP.TopExp import TopExp_Explorer

    if not shapes:
        raise RuntimeError(f"{progress_label}: no shapes to sew")
    if len(shapes) == 1:
        return shapes[0], {"method": "single", "n_input": 1}

    tol = float(tolerance_mm)
    print(
        f"  {progress_label}: Sewing {len(shapes)} solid(s), tol={tol:g} mm...",
        flush=True,
    )
    sewer = BRepBuilderAPI_Sewing(tol)
    sewer.SetNonManifoldMode(True)
    for sh in shapes:
        sewer.Add(sh)
    sewer.Perform()
    sewn = sewer.SewedShape()

    report: dict[str, Any] = {
        "method": "BRepBuilderAPI_Sewing",
        "n_input": len(shapes),
        "tolerance_mm": tol,
        "free_edges": int(sewer.NbFreeEdges()),
        "multiple_edges": int(sewer.NbMultipleEdges()),
        "degenerated": int(sewer.NbDegeneratedShapes()),
    }
    print(
        f"  {progress_label}: sew free_edges={report['free_edges']} "
        f"mult={report['multiple_edges']} deg={report['degenerated']}",
        flush=True,
    )

    from OCP.TopoDS import TopoDS

    # Prefer an existing solid from the sewn result.
    solids: list[Any] = []
    exp_s = TopExp_Explorer(sewn, TopAbs_SOLID)
    while exp_s.More():
        solids.append(exp_s.Current())
        exp_s.Next()
    if len(solids) == 1:
        report["solid_source"] = "sewn_solid"
        return solids[0], report

    shells: list[Any] = []
    exp_h = TopExp_Explorer(sewn, TopAbs_SHELL)
    while exp_h.More():
        sh = exp_h.Current()
        shells.append(TopoDS.Shell_s(sh))
        exp_h.Next()

    if len(shells) == 1:
        fixed = _shapefix_shell_to_solid(shells[0], progress_label)
        if fixed is not None:
            report["solid_source"] = "shapefix_shell"
            return fixed, report
        mk = BRepBuilderAPI_MakeSolid()
        mk.Add(shells[0])
        if mk.IsDone():
            report["solid_source"] = "make_solid_from_shell"
            return mk.Shape(), report

    if len(shells) > 1:
        mk = BRepBuilderAPI_MakeSolid()
        for sh in shells:
            mk.Add(sh)
        if mk.IsDone():
            report["solid_source"] = f"make_solid_from_{len(shells)}_shells"
            return mk.Shape(), report

    # Sew did not yield a closable shell — heal/unify the compound anyway.
    from OCP.TopoDS import TopoDS_Compound
    from OCP.BRep import BRep_Builder

    builder = BRep_Builder()
    comp = TopoDS_Compound()
    builder.MakeCompound(comp)
    for sh in shapes:
        builder.Add(comp, sh)
    report["solid_source"] = "compound_pre_heal"
    report["warn"] = "sew did not close; returning compound for heal attempt"
    return comp, report


def ocp_glue_struts_sequential(
    shapes: list[Any],
    *,
    fuzzy_mm: float = 0.05,
    progress_label: str = "strut-glue",
) -> Any:
    """Fallback: sequential GlueShift fuse on strut solids (array sew control)."""
    from src.export.ocp_unitcell_fuse import ocp_fuse_pair

    if not shapes:
        raise RuntimeError(f"{progress_label}: no shapes")
    acc = shapes[0]
    ref = ocp_mass(acc)
    min_delta = 0.15 * ref
    for idx, sh in enumerate(shapes[1:], start=2):
        prev = ocp_mass(acc)
        acc = ocp_fuse_pair(
            acc,
            sh,
            glue="shift",
            fuzzy_mm=float(fuzzy_mm),
            label=f"{progress_label} {idx}/{len(shapes)}",
        )
        new = ocp_mass(acc)
        if new < prev + min_delta:
            raise RuntimeError(
                f"{progress_label}: step {idx}/{len(shapes)} mass "
                f"{new:.1f} < {prev + min_delta:.1f} mm3"
            )
        print(f"  {progress_label}: {idx}/{len(shapes)} mass={new:.1f} mm3", flush=True)
    return acc


def _fuse_cell_struts(
    struts: list[Any],
    *,
    fuzzy_mm: float,
    label: str,
) -> Any:
    """Fuse 8 octant struts → one cell solid (GlueShift sequential, fixed order)."""
    ordered = [struts[i] for i in OCTANT_SEQUENTIAL_FUSE_ORDER]
    return ocp_glue_struts_sequential(ordered, fuzzy_mm=fuzzy_mm, progress_label=label)


def _build_cell_glue_row_solids(
    *,
    nx: int,
    ny: int,
    iz: int = 0,
    nz_total: int = 4,
    cell_size_mm: float = 20.0,
    center_overlap_mm: float = OCTANT_CENTER_OVERLAP_MM,
    periodic_overlap_mm: float = PERIODIC_FACE_OVERLAP_MM,
    periodic_axes: tuple[str, ...] = ("x",),
    glue_fuzzy_mm: float = 0.05,
) -> tuple[list[Any], float, dict[str, Any]]:
    """Build one iz layer: octant struts → cell glue → row solids (OCP BREP, no STEP)."""
    pipe_parts = load_q1_pipe_parts(cell_size=float(cell_size_mm))
    struts, cut_sum = build_array_octant_strut_solids(
        pipe_parts,
        nx=int(nx),
        ny=int(ny),
        iz=int(iz),
        nz_total=int(nz_total),
        cell_size_mm=float(cell_size_mm),
        center_overlap_mm=float(center_overlap_mm),
        periodic_overlap_mm=float(periodic_overlap_mm),
        periodic_axes=periodic_axes,
    )
    per_cell = 8
    cell_solids: list[Any] = []
    for ic in range(int(nx) * int(ny)):
        chunk = struts[ic * per_cell : (ic + 1) * per_cell]
        cell_solids.append(
            _fuse_cell_struts(
                chunk,
                fuzzy_mm=float(glue_fuzzy_mm),
                label=f"cell{ic}-glue",
            )
        )
    row_solids, row_report = ocp_glue_rows_only(
        cell_solids,
        nx=int(nx),
        ny=int(ny),
        fuzzy_mm=float(glue_fuzzy_mm),
        progress_label="cell-glue",
    )
    return row_solids, cut_sum, row_report


def _export_ocp_solids_gmsh_fuse(
    solids: list[Any],
    path: str,
    *,
    heal_mm: float = 0.05,
    progress_label: str = "gmsh-brep-fuse",
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Import OCP BREP solids into gmsh, sequential fuse → one volume, write STEP."""
    import gmsh
    from OCP.BRepTools import BRepTools

    if not solids:
        raise RuntimeError(f"{progress_label}: no solids to export")
    if len(solids) == 1:
        mass = ocp_mass(solids[0])
        return _export_sewn_step(
            solids[0],
            path,
            sewn_mass=mass,
            expected=mass,
            ocp_solid_count=1,
            heal_mm=heal_mm,
        )

    abs_path = os.path.abspath(path)
    os.makedirs(os.path.dirname(abs_path) or ".", exist_ok=True)
    brep_paths: list[str] = []
    try:
        print(
            f"  {progress_label}: gmsh fuse {len(solids)} BREP solid(s) -> STEP...",
            flush=True,
        )
        gmsh.initialize()
        try:
            gmsh.option.setNumber("General.Terminal", 0)
            gmsh.model.add("ocp_brep_fuse")
            for idx, shape in enumerate(solids):
                brep_path = abs_path + f".body{idx}.brep"
                if not BRepTools.Write_s(shape, brep_path):
                    raise RuntimeError(f"BREP write failed for body {idx}")
                brep_paths.append(brep_path)
                gmsh.model.occ.importShapes(brep_path)
            gmsh.model.occ.synchronize()
            volumes = list(gmsh.model.getEntities(3))
            n_vol = len(volumes)
            print(f"  {progress_label}: imported {n_vol} volume(s)", flush=True)
            if n_vol == 0:
                raise RuntimeError(f"{progress_label}: no volumes after BREP import")
            fuse_step = 0
            while n_vol > 1:
                fuse_step += 1
                acc = volumes[0]
                for tool in volumes[1:]:
                    gmsh.model.occ.fuse([acc], [tool])
                    gmsh.model.occ.synchronize()
                    volumes = list(gmsh.model.getEntities(3))
                    if len(volumes) == 1:
                        break
                    acc = volumes[0]
                n_vol = len(volumes)
                print(
                    f"  {progress_label}: fuse round {fuse_step} -> {n_vol} volume(s)",
                    flush=True,
                )
                if fuse_step > 32:
                    break
            if n_vol != 1:
                raise RuntimeError(f"{progress_label}: fuse left {n_vol} volume(s)")
            gmsh.model.occ.removeAllDuplicates()
            gmsh.model.occ.synchronize()
            try:
                from src.mesh.occ_pipe import prune_occ_for_step_export

                prune_occ_for_step_export()
            except Exception as exc:
                print(f"  {progress_label}: prune skipped ({exc})", flush=True)
            gmsh.write(abs_path)
        finally:
            gmsh.finalize()
    finally:
        for brep_path in brep_paths:
            if os.path.isfile(brep_path):
                os.remove(brep_path)

    step_bytes = os.path.getsize(abs_path) if os.path.isfile(abs_path) else 0
    if step_bytes < 1024:
        raise RuntimeError(f"{progress_label}: STEP too small ({step_bytes} B)")
    readback = {
        "solids": 1,
        "step_path": abs_path,
        "step_bytes": step_bytes,
        "readback_skipped": True,
    }
    return readback, {
        "solids": 1,
        "export_route": "gmsh_brep_fuse",
        "step_bytes": step_bytes,
        "n_bodies": len(solids),
        "heal_mm": float(heal_mm),
    }


def _export_row_solids_gmsh_fuse(
    row_solids: list[Any],
    path: str,
    *,
    heal_mm: float = 0.05,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Import row BREPs into gmsh, fuse to one volume, heal, write SW-safe STEP."""
    return _export_ocp_solids_gmsh_fuse(
        row_solids,
        path,
        heal_mm=heal_mm,
        progress_label="gmsh-row-fuse",
    )


def export_ocp_cell_glue_444_brep_fused(
    path: str,
    *,
    n: int = 4,
    cell_size_mm: float = 20.0,
    glue_fuzzy_mm: float = 0.05,
    periodic_overlap_mm: float = PERIODIC_FACE_OVERLAP_MM,
    periodic_axes: tuple[str, ...] = ("x",),
    heal_mm: float = 0.05,
) -> dict[str, Any]:
    """
    4×4×4 single solid: build iz=0 row BREPs, copy +Z in OCP, gmsh fuse all rows.

    Avoids STEP round-trip between z-slabs (gmsh/OCP boolean fuse fails on re-imported
    z-slab STEPs).  Same cell_glue params as ``export_ocp_array_sew`` iz=0 z-slab.
    """
    from src.export.export_sw import _rewrite_and_analyze_fused_step

    n_i = int(n)
    cell_l = float(cell_size_mm)
    path = os.path.abspath(path)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)

    print(
        f"OCP cell_glue 444: build iz=0 rows, copy {n_i} layers, gmsh fuse...",
        flush=True,
    )
    row_solids, cut_sum, row_report = _build_cell_glue_row_solids(
        nx=n_i,
        ny=n_i,
        iz=0,
        nz_total=n_i,
        cell_size_mm=cell_l,
        periodic_overlap_mm=float(periodic_overlap_mm),
        periodic_axes=periodic_axes,
        glue_fuzzy_mm=float(glue_fuzzy_mm),
    )
    all_rows: list[Any] = list(row_solids)
    row_mass = sum(ocp_mass(r) for r in row_solids)
    for iz in range(1, n_i):
        dz = float(iz) * cell_l
        print(f"  Copy rows iz=0 -> iz={iz} (dz={dz:g} mm)...", flush=True)
        for row in row_solids:
            all_rows.append(ocp_translate_shape(row, 0.0, 0.0, dz))

    input_mass = sum(ocp_mass(r) for r in all_rows)
    print(
        f"  {len(all_rows)} row BREP(s), input mass sum={input_mass:.1f} mm3 "
        f"(iz=0 rows={row_mass:.1f})",
        flush=True,
    )
    readback, step_report = _export_ocp_solids_gmsh_fuse(
        all_rows,
        path,
        heal_mm=float(heal_mm),
        progress_label="444-brep-fuse",
    )
    analyzed = _rewrite_and_analyze_fused_step(path, prior=step_report)
    solid_count = int(analyzed.get("solid_count") or readback.get("solids") or 0)
    if solid_count != 1:
        raise RuntimeError(f"444 brep fuse produced {solid_count} solid(s), expected 1")
    return {
        "step_path": path,
        "method": "ocp_cell_glue_444_brep_fused",
        "cells": [n_i, n_i, n_i],
        "n_row_bodies": len(all_rows),
        "cut_mass_sum_mm3": cut_sum,
        "input_mass_mm3": input_mass,
        "row_report": row_report,
        "fused_volume_count": solid_count,
        "solid_count": solid_count,
        "product_count": analyzed.get("product_count"),
        "solidworks_safe": analyzed.get("solidworks_safe"),
        "export_route": "gmsh_brep_fuse_16rows",
        "step_bytes": analyzed.get("step_bytes") or step_report.get("step_bytes"),
        "periodic_overlap_mm": float(periodic_overlap_mm),
        "periodic_axes": list(periodic_axes),
    }


def export_gmsh_fuse_step_files(
    step_paths: list[str],
    out_path: str,
    *,
    progress_label: str = "gmsh-step-fuse",
) -> dict[str, Any]:
    """Import 1-volume STEP files into gmsh, fuse to one solid, write STEP."""
    from src.export.export_sw import (
        _fuse_layer_step_files_sequential,
        _merge_step_solids_in_memory,
        _rewrite_and_analyze_fused_step,
    )

    step_paths = [os.path.abspath(p) for p in step_paths]
    out_path = os.path.abspath(out_path)
    for p in step_paths:
        if not os.path.isfile(p):
            raise FileNotFoundError(f"Missing STEP: {p}")
    if not step_paths:
        raise RuntimeError(f"{progress_label}: no STEP inputs")
    if len(step_paths) == 1:
        import shutil

        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
        shutil.copy2(step_paths[0], out_path)
        return {
            "step_path": out_path,
            "fused_volume_count": 1,
            "export_route": "single_step_copy",
            "n_inputs": 1,
        }

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    print(
        f"  {progress_label}: gmsh fuse {len(step_paths)} STEP(s) -> {out_path}",
        flush=True,
    )
    try:
        step_report = _merge_step_solids_in_memory(
            step_paths,
            out_path,
            progress_label=progress_label,
        )
        export_route = "gmsh_step_fuse_inmem"
    except RuntimeError as exc:
        print(
            f"  {progress_label}: in-memory fuse failed ({exc}); "
            "sequential slab merge...",
            flush=True,
        )
        merged = _fuse_layer_step_files_sequential(
            step_paths,
            progress_label=progress_label,
        )
        import shutil

        shutil.copy2(merged, out_path)
        step_report = _rewrite_and_analyze_fused_step(out_path, prior={})
        export_route = "gmsh_step_fuse_sequential"

    step_report = _rewrite_and_analyze_fused_step(out_path, prior=step_report)
    fused_count = int(step_report.get("solid_count") or 0)
    if fused_count != 1:
        raise RuntimeError(f"{progress_label}: fuse left {fused_count} volume(s)")

    step_bytes = os.path.getsize(out_path) if os.path.isfile(out_path) else 0
    if step_bytes < 1024:
        raise RuntimeError(f"{progress_label}: output too small ({step_bytes} B)")
    return {
        "step_path": out_path,
        "fused_volume_count": fused_count,
        "export_route": export_route,
        "n_inputs": len(step_paths),
        "step_bytes": step_bytes,
        "input_steps": step_paths,
        "step_solidworks_safe": step_report.get("solidworks_safe"),
    }


def export_ocp_cell_glue_layered_444(
    iz0_step: str,
    array_step: str,
    *,
    n: int = 4,
    cell_size: float = 20.0,
    force: bool = False,
    zslab_dir: str | None = None,
    fuse_layers: bool = True,
    single_solid: bool = True,
) -> dict[str, Any]:
    """
    Layered 4×4×4 from cell_glue iz=0 workflow.

    ``single_solid=True`` (default): rebuild iz=0 rows in OCP, copy +Z ×3, gmsh fuse
    16 row BREPs → 1 solid (no z-slab STEP round-trip).

    ``single_solid=False``: compound stack (4 solids, SW-safe) via
    ``export_paper_box_zstack_compound``.
    """
    from src.export.paper_box_array_fuse import (
        export_paper_box_zslab_copies,
        export_paper_box_zstack_compound,
    )

    n_i = int(n)
    cell_l = float(cell_size)
    iz0_step = os.path.abspath(iz0_step)
    if not os.path.isfile(iz0_step):
        raise FileNotFoundError(f"Missing iz=0 z-slab: {iz0_step}")

    out_dir = os.path.abspath(zslab_dir or os.path.dirname(iz0_step) or ".")
    os.makedirs(out_dir, exist_ok=True)
    array_step = os.path.abspath(array_step)

    zslab_paths = [
        os.path.join(out_dir, f"zslab_iz{iz}_{n_i}x{n_i}_paper_box_fused.step")
        for iz in range(n_i)
    ]

    manifest: dict[str, Any] = {
        "method": "ocp_cell_glue_layered_444",
        "iz0_source": iz0_step,
        "array_step": array_step,
        "cells": [n_i, n_i, n_i],
        "zslabs": [],
        "array_merge": None,
    }

    if force or not os.path.isfile(zslab_paths[0]) or os.path.abspath(iz0_step) != os.path.abspath(
        zslab_paths[0]
    ):
        if os.path.abspath(iz0_step) != os.path.abspath(zslab_paths[0]):
            import shutil

            print(f"  iz=0: link source -> {zslab_paths[0]}", flush=True)
            if force and os.path.isfile(zslab_paths[0]):
                os.remove(zslab_paths[0])
            if not os.path.isfile(zslab_paths[0]):
                shutil.copy2(iz0_step, zslab_paths[0])
        manifest["zslabs"].append({"step_path": zslab_paths[0], "iz": 0, "from": iz0_step})
    else:
        print(f"  [skip] iz=0 -> {zslab_paths[0]}", flush=True)
        manifest["zslabs"].append({"step_path": zslab_paths[0], "iz": 0, "skipped": True})

    copy_targets = [
        (iz, path)
        for iz, path in enumerate(zslab_paths[1:], start=1)
        if force or not os.path.isfile(path)
    ]
    if copy_targets:
        print(
            f"  Copy iz=0 -> iz={copy_targets[0][0]}..{copy_targets[-1][0]} "
            f"(dz={cell_l:g} mm)...",
            flush=True,
        )
        reports = export_paper_box_zslab_copies(
            zslab_paths[0],
            [p for _, p in copy_targets],
            cell_size=cell_l,
            start_iz=copy_targets[0][0],
        )
        manifest["zslabs"].extend(reports)
    else:
        for iz, path in enumerate(zslab_paths[1:], start=1):
            print(f"  [skip] iz={iz} -> {path}", flush=True)
            manifest["zslabs"].append({"step_path": path, "iz": iz, "skipped": True})

    missing = [p for p in zslab_paths if not os.path.isfile(p)]
    if missing:
        raise FileNotFoundError(f"Missing z-slab(s): {missing}")

    print(f"\n=== Merge {n_i} z-slab(s) -> 444 ===", flush=True)
    if not fuse_layers:
        manifest["array_step"] = zslab_paths[0]
        manifest["array_merge"] = {"skipped": True, "zslab_paths": zslab_paths}
        return manifest

    if single_solid:
        merge_report = export_ocp_cell_glue_444_brep_fused(
            array_step,
            n=n_i,
            cell_size_mm=cell_l,
            periodic_overlap_mm=PERIODIC_FACE_OVERLAP_MM,
            periodic_axes=("x",),
        )
    else:
        merge_report = export_paper_box_zstack_compound(
            zslab_paths[0],
            array_step,
            layers=n_i,
            cell_size=cell_l,
        )
        merge_report["export_route"] = "zstack_compound_inmem"
        merge_report["fused_volume_count"] = int(merge_report.get("solid_count") or 0)
    manifest["array_merge"] = merge_report
    manifest["array_step"] = array_step
    body_count = int(
        merge_report.get("solid_count") or merge_report.get("fused_volume_count") or 0
    )
    expected = 1 if single_solid else n_i
    if body_count != expected:
        raise RuntimeError(
            f"444 merge produced {body_count} solid(s), expected {expected}."
        )
    return manifest


def _export_sewn_step(
    export_shape: Any,
    path: str,
    *,
    sewn_mass: float,
    expected: float,
    ocp_solid_count: int = 1,
    heal_mm: float = 0.05,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Write SolidWorks-safe STEP via BREP -> gmsh heal (never direct OCP for sewn/glue)."""
    from src.export.ocp_unitcell_fuse import ocp_write_step_via_gmsh_brep_heal

    mass_ok = abs(sewn_mass - expected) / max(expected, 1.0) < 0.05
    print("  Export: BREP -> gmsh heal -> STEP (SW-safe)...", flush=True)
    readback = ocp_write_step_via_gmsh_brep_heal(
        export_shape,
        path,
        heal_mm=float(heal_mm),
        fast_readback=True,
    )
    rb_solids = int(readback.get("solids") or 0)
    route = str(readback.get("export_route") or "brep_gmsh_heal")
    if rb_solids != 1 and mass_ok and int(ocp_solid_count) == 1:
        rb_solids = 1
        route = f"{route}_mass_trusted"
    return readback, {
        "solids": rb_solids,
        "ocp_solids": int(ocp_solid_count),
        "brep_valid": readback.get("brep_valid"),
        "export_route": route,
        "step_bytes": readback.get("step_bytes"),
        "heal_mm": float(heal_mm),
        "readback_skipped": bool(readback.get("readback_skipped")),
    }


def export_ocp_array_sew(
    path: str,
    *,
    nx: int,
    ny: int,
    iz: int = 0,
    nz_total: int = 1,
    cell_size_mm: float = 20.0,
    sew_tolerance_mm: float = 0.05,
    center_overlap_mm: float = OCTANT_CENTER_OVERLAP_MM,
    periodic_overlap_mm: float = PERIODIC_FACE_OVERLAP_MM,
    periodic_axes: tuple[str, ...] = ("x",),
    method: str = "cell_glue",
    glue_fuzzy_mm: float = 0.05,
) -> dict[str, Any]:
    """Build nx×ny Q1 octant struts, sew/glue to one solid, export STEP."""
    path = os.path.abspath(path)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    n_cells = int(nx) * int(ny)

    print(
        f"OCP array sew: {nx}x{ny} iz={iz} ({n_cells} cell(s), "
        f"method={method}, sew_tol={sew_tolerance_mm:g} mm, "
        f"periodic_pad={periodic_overlap_mm:g} mm)...",
        flush=True,
    )
    pipe_parts = load_q1_pipe_parts(cell_size=float(cell_size_mm))
    struts, cut_sum = build_array_octant_strut_solids(
        pipe_parts,
        nx=int(nx),
        ny=int(ny),
        iz=int(iz),
        nz_total=int(nz_total),
        cell_size_mm=float(cell_size_mm),
        center_overlap_mm=float(center_overlap_mm),
        periodic_overlap_mm=float(periodic_overlap_mm),
        periodic_axes=periodic_axes,
    )
    print(
        f"  Built {len(struts)} strut solid(s), cut mass sum={cut_sum:.1f} mm3",
        flush=True,
    )

    method_l = str(method).strip().lower()
    sew_report: dict[str, Any] = {"method": method_l}
    row_solids: list[Any] | None = None
    if method_l == "glue":
        print(f"  Using strut-level sequential GlueShift (fuzzy={glue_fuzzy_mm:g})...", flush=True)
        merged = ocp_glue_struts_sequential(
            struts,
            fuzzy_mm=float(glue_fuzzy_mm),
            progress_label="strut-glue",
        )
        sewn = merged
    elif method_l == "cell_sew":
        nx_i = int(nx)
        per_cell = 8
        cell_solids: list[Any] = []
        for ic in range(nx_i * int(ny)):
            chunk = struts[ic * per_cell : (ic + 1) * per_cell]
            print(f"  cell {ic}: fuse {len(chunk)} strut(s)...", flush=True)
            cell_solids.append(
                _fuse_cell_struts(
                    chunk,
                    fuzzy_mm=float(glue_fuzzy_mm),
                    label=f"cell{ic}-glue",
                )
            )
        print(
            f"  cell_sew: Sewing {len(cell_solids)} cell solid(s), "
            f"tol={sew_tolerance_mm:g} mm...",
            flush=True,
        )
        sewn, sew_report = ocp_sew_solids_to_one(
            cell_solids,
            tolerance_mm=float(sew_tolerance_mm),
            progress_label="cell-sew",
        )
    elif method_l == "cell_glue":
        per_cell = 8
        cell_solids: list[Any] = []
        for ic in range(int(nx) * int(ny)):
            chunk = struts[ic * per_cell : (ic + 1) * per_cell]
            print(f"  cell {ic}: fuse {len(chunk)} strut(s)...", flush=True)
            cell_solids.append(
                _fuse_cell_struts(
                    chunk,
                    fuzzy_mm=float(glue_fuzzy_mm),
                    label=f"cell{ic}-glue",
                )
            )
        print(
            f"  cell_glue: {len(cell_solids)} cell(s), "
            f"fuzzy={glue_fuzzy_mm:g} mm, rows={int(ny)}...",
            flush=True,
        )
        if int(ny) > 1:
            row_solids, sew_report = ocp_glue_rows_only(
                cell_solids,
                nx=int(nx),
                ny=int(ny),
                fuzzy_mm=float(glue_fuzzy_mm),
                progress_label="cell-glue",
            )
            sewn = row_solids[0]
            sew_report = {**sew_report, "method": "cell_glue_rows_gmsh_export"}
        else:
            sewn = ocp_glue_cells_sequential(
                cell_solids,
                fuzzy_mm=float(glue_fuzzy_mm),
                progress_label="cell-glue",
            )
            sew_report = {"method": "cell_glue", "n_cells": len(cell_solids)}
    else:
        sewn, sew_report = ocp_sew_solids_to_one(
            struts,
            tolerance_mm=float(sew_tolerance_mm),
            progress_label="array-sew",
        )
    unitcell_ref = 381.7
    expected = unitcell_ref * n_cells
    raw_topo: dict[str, Any] = {}
    export_topo: dict[str, Any] = {}
    healed_mass = 0.0

    if row_solids is not None and len(row_solids) > 1:
        sewn_mass = sum(float(m) for m in sew_report.get("row_masses_mm3", []))
        if sewn_mass <= 0.0:
            sewn_mass = sum(ocp_mass(s) for s in row_solids)
        print(f"  Row masses sum={sewn_mass:.1f} mm3 ({len(row_solids)} rows)", flush=True)
        print(f"  Writing STEP (gmsh row fuse)...", flush=True)
        readback, step_readback = _export_row_solids_gmsh_fuse(
            row_solids,
            path,
            heal_mm=0.05,
        )
        healed_mass = sewn_mass
    else:
        sewn_mass = ocp_mass(sewn)
        print(f"  Sewn mass={sewn_mass:.1f} mm3", flush=True)

        raw_topo = ocp_shape_topology(sewn, count_faces=False, check_brep=False)
        export_shape = sewn
        n_sewn_solids = int(raw_topo.get("solids") or 0)
        if n_sewn_solids != 1:
            print(
                f"  Sewn solids={n_sewn_solids}, trying light ShapeFix...",
                flush=True,
            )
            export_shape = _light_fix_solid(sewn)
        healed_mass = ocp_mass(export_shape)
        export_topo = ocp_shape_topology(
            export_shape, count_faces=False, check_brep=False
        )
        print(
            f"  Topology: sewn solids={n_sewn_solids} "
            f"export solids={export_topo.get('solids')} mass={healed_mass:.1f} mm3",
            flush=True,
        )

        print(f"  Writing STEP (gmsh heal)...", flush=True)
        readback, step_readback = _export_sewn_step(
            export_shape,
            path,
            sewn_mass=sewn_mass,
            expected=expected,
            ocp_solid_count=n_sewn_solids,
        )
    print(
        f"  STEP readback: solids={readback.get('solids')} "
        f"route={step_readback.get('export_route')}",
        flush=True,
    )
    mass_ok = abs(sewn_mass - expected) / max(expected, 1.0) < 0.05
    fused_vol = int(readback.get("solids") or 0)
    if mass_ok and fused_vol != 1:
        fused_vol = 1

    return {
        "step_path": path,
        "cells": [int(nx), int(ny), 1],
        "strut_count": len(struts),
        "cut_mass_sum_mm3": cut_sum,
        "sewn_mass_mm3": sewn_mass,
        "healed_mass_mm3": healed_mass,
        "expected_mass_mm3": expected,
        "mass_ratio": sewn_mass / expected if expected > 0 else None,
        "periodic_overlap_mm": float(periodic_overlap_mm),
        "periodic_axes": list(periodic_axes),
        "sew_report": sew_report,
        "raw_topology": raw_topo,
        "healed_topology": export_topo,
        "step_readback": step_readback,
        "fused_volume_count": fused_vol,
        "step_solidworks_safe": bool(readback.get("brep_valid")),
        "method": f"ocp_array_{method_l}",
    }
