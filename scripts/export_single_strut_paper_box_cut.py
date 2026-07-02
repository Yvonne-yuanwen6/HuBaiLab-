"""
Export one paper-style box-cut strut as STEP (pipe sweep + 1/8 octant intersect).

Each strut lives in the octant block that contains the cell centre (0,0,0) and its
corner — so eight cut struts meet face-to-face on x/y/z=0 planes without centre overlap.

  py -3 scripts/export_single_strut_paper_box_cut.py --Q 1.0 --strut 1
  py -3 scripts/export_single_strut_paper_box_cut.py --Q 1.0 --strut 8 --list
"""

from __future__ import annotations

import argparse
import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from src.export.export_sw import (
    _collect_solid_primitives,
    _configure_occ_for_fuse,
    _finalize_occ_step_write,
    _occ_dimtags_from_parts,
    _occ_remove_all_volumes_except,
    _postprocess_written_step,
)
from src.export.sw_parasolid import analyze_step_for_solidworks
from src.export.unitcell_box_cut import (
    OCTANT_CENTER_OVERLAP_MM,
    _bbox_mm,
    _canonical_corner_from_pipe_path,
    _occ_add_box_from_bounds,
    _occ_align_single_cut_to_virtual_box,
    _occ_octant_cut_single_pipe_tag,
    _occ_reposition_octant_cut_for_origin_assembly,
    _octant_bounds_from_corner_mm,
    octant_centre_path_extension_mm,
    pipe_part_with_both_end_path_extension,
    pipe_part_with_centre_path_extension,
    unitcell_octant_assembly_bounds_mm,
    unitcell_octant_assembly_scale,
)
from src.generator.hu_bai_bcc import HuBaiLatticeGenerator
from src.paths import CAD_ROOT, ensure_output_dirs

ensure_output_dirs()


def _corner_tag(path_pts: tuple) -> str:
    x, y, z = (float(path_pts[-1][0]), float(path_pts[-1][1]), float(path_pts[-1][2]))
    sx = "p" if x > 0 else "m"
    sy = "p" if y > 0 else "m"
    sz = "p" if z > 0 else "m"
    return f"{sx}{sy}{sz}"


def export_single_strut_raw(
    *,
    period_factor: float,
    strut_index: int,
    cell_size_mm: float = 20.0,
    n_segments: int = 24,
    rod_diameter: float = 2.0,
    amplitude: float = 2.0,
    out_path: str,
) -> dict:
    """Export one full pipe sweep (no octant box cut) for CAD inspection."""
    import gmsh

    gen = HuBaiLatticeGenerator(
        cell_size=float(cell_size_mm),
        rod_diameter=float(rod_diameter),
        amplitude=float(amplitude),
        period_factor=float(period_factor),
        n_segments=max(3, int(n_segments)),
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
    pipes = [p for p in pipes_only if p[0] == "pipe"]
    if not pipes:
        raise ValueError("No pipe primitives.")
    idx = int(strut_index)
    if idx < 1 or idx > len(pipes):
        raise ValueError(f"--strut must be 1..{len(pipes)}, got {idx}")

    part = pipes[idx - 1]
    path_pts = part[1]
    corner = path_pts[-1]
    corner_tag = _corner_tag(path_pts)
    centre = path_pts[0]
    p1 = path_pts[1] if len(path_pts) > 1 else centre

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)

    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add(f"single_strut_raw_{corner_tag}")
        _configure_occ_for_fuse()

        pipe_tags = _occ_dimtags_from_parts([part])
        gmsh.model.occ.synchronize()
        pipe_vol = pipe_tags[0]
        pipe_mass = float(gmsh.model.occ.getMass(3, int(pipe_vol[1])))
        bbox = _bbox_mm(pipe_vol)
        _occ_remove_all_volumes_except(pipe_vol)

        step_report = _finalize_occ_step_write(out_path, fuse=True, validate_step=False)
    finally:
        gmsh.finalize()

    step_report = _postprocess_written_step(
        out_path,
        step_report,
        fused_single=True,
        max_flatten_bodies=1,
    )
    try:
        step_report = analyze_step_for_solidworks(out_path, fused_single=True)
    except RuntimeError as exc:
        raise RuntimeError(
            f"STEP not SolidWorks-safe (orphan PRODUCTs → multi-window): {exc}"
        ) from exc

    import math

    chord_len = math.dist(
        (float(centre[0]), float(centre[1]), float(centre[2])),
        (float(p1[0]), float(p1[1]), float(p1[2])),
    )
    return {
        "step_path": os.path.abspath(out_path),
        "variant": gen.variant_name,
        "Q": float(period_factor),
        "strut_index": idx,
        "corner_mm": tuple(float(v) for v in corner),
        "corner_tag": corner_tag,
        "centre_mm": tuple(float(v) for v in centre),
        "first_interior_mm": tuple(float(v) for v in p1),
        "first_chord_length_mm": chord_len,
        "path_point_count": len(path_pts),
        "pipe_mass_mm3": pipe_mass,
        "bbox_mm": bbox,
        "fused_volume_count": step_report.get("solid_count"),
        "step_product_count": step_report.get("product_count"),
        "step_solidworks_safe": step_report.get("solidworks_safe"),
        "method": "single_strut_pipe_raw_no_cut",
        "pipe_open_centre": False,
        "octant_cut": False,
        "size_bytes": os.path.getsize(out_path) if os.path.isfile(out_path) else 0,
    }


def _export_volume_in_fresh_session(
    *,
    model_name: str,
    build_volume,
    out_path: str,
) -> dict:
    """Run ``build_volume(gmsh) -> vol`` in a new gmsh session and write one STEP."""
    import gmsh

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add(model_name)
        _configure_occ_for_fuse()
        vol = build_volume()
        gmsh.model.occ.synchronize()
        _occ_remove_all_volumes_except(vol)
        step_report = _finalize_occ_step_write(out_path, fuse=True, validate_step=False)
    finally:
        gmsh.finalize()

    step_report = _postprocess_written_step(
        out_path,
        step_report,
        fused_single=True,
        max_flatten_bodies=1,
    )
    try:
        step_report = analyze_step_for_solidworks(out_path, fused_single=True)
    except RuntimeError as exc:
        raise RuntimeError(
            f"STEP not SolidWorks-safe (orphan PRODUCTs → multi-window): {exc}"
        ) from exc
    step_report["step_path"] = os.path.abspath(out_path)
    step_report["size_bytes"] = os.path.getsize(out_path) if os.path.isfile(out_path) else 0
    return step_report


def export_single_strut_aligned_octant_cut_step(
    *,
    period_factor: float,
    strut_index: int,
    out_path: str,
    cell_size_mm: float = 20.0,
    n_segments: int = 24,
    rod_diameter: float = 2.0,
    amplitude: float = 2.0,
    both_end_extension: bool = True,
    centre_extension_mm: float | None = None,
    corner_extension_mm: float | None = None,
) -> dict:
    """Export one cell-frame aligned octant-cut strut (after intersect + virtual-box align)."""
    gen = HuBaiLatticeGenerator(
        cell_size=float(cell_size_mm),
        rod_diameter=float(rod_diameter),
        amplitude=float(amplitude),
        period_factor=float(period_factor),
        n_segments=max(3, int(n_segments)),
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
    pipes = [p for p in pipes_only if p[0] == "pipe"]
    idx = int(strut_index)
    part = pipes[idx - 1]
    rod_radius = 0.5 * float(rod_diameter)
    centre_ext = (
        float(centre_extension_mm)
        if centre_extension_mm is not None
        else octant_centre_path_extension_mm(rod_radius)
    )
    corner_ext = (
        float(corner_extension_mm)
        if corner_extension_mm is not None
        else centre_ext
    )
    if both_end_extension:
        pipe_part = pipe_part_with_both_end_path_extension(
            part,
            centre_ext,
            corner_extension_mm=corner_ext,
        )
    else:
        pipe_part = pipe_part_with_centre_path_extension(part, centre_ext)
    corner_tuple = _canonical_corner_from_pipe_path(part[1], cell_size_mm)

    def _build_aligned_cut():
        import gmsh

        pipe_tags = _occ_dimtags_from_parts([pipe_part])
        gmsh.model.occ.synchronize()
        cut_vol = _occ_octant_cut_single_pipe_tag(
            pipe_tags[0],
            pipe_part,
            cell_size_mm,
            progress_label=f"aligned-cut-strut-{idx}",
        )
        return _occ_align_single_cut_to_virtual_box(
            cut_vol,
            corner_tuple,
            cell_size_mm,
            center_overlap_mm=OCTANT_CENTER_OVERLAP_MM,
            progress_label=f"aligned-cut-strut-{idx}-align",
        )

    report = _export_volume_in_fresh_session(
        model_name=f"aligned_cut_s{idx:02d}",
        build_volume=_build_aligned_cut,
        out_path=out_path,
    )
    report.update(
        {
            "variant": gen.variant_name,
            "Q": float(period_factor),
            "strut_index": idx,
            "both_end_extension": both_end_extension,
            "centre_path_extension_mm": centre_ext,
            "corner_path_extension_mm": corner_ext if both_end_extension else 0.0,
            "method": "single_strut_aligned_octant_cut_step",
        }
    )
    return report


def export_single_strut_cut_inspection(
    *,
    period_factor: float,
    strut_index: int,
    cell_size_mm: float = 20.0,
    n_segments: int = 24,
    rod_diameter: float = 2.0,
    amplitude: float = 2.0,
    out_dir: str,
    centre_extension_mm: float | None = None,
    corner_extension_mm: float | None = None,
    both_end_extension: bool = False,
) -> dict:
    """
    Export CAD inspection set for one octant cut (cell frame + origin assembly):

      01_pipe_extended.step   — extended pipe before boolean
      02_octant_cut_box.step  — 1/8 virtual hexahedron used for intersect
      03_cut_after_intersect.step
      04_cut_after_align.step
      05_cut_at_origin.step
    """
    import gmsh

    gen = HuBaiLatticeGenerator(
        cell_size=float(cell_size_mm),
        rod_diameter=float(rod_diameter),
        amplitude=float(amplitude),
        period_factor=float(period_factor),
        n_segments=max(3, int(n_segments)),
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
    pipes = [p for p in pipes_only if p[0] == "pipe"]
    if not pipes:
        raise ValueError("No pipe primitives.")
    idx = int(strut_index)
    if idx < 1 or idx > len(pipes):
        raise ValueError(f"--strut must be 1..{len(pipes)}, got {idx}")

    part = pipes[idx - 1]
    path_pts = part[1]
    corner = path_pts[-1]
    corner_tag = _corner_tag(path_pts)
    corner_tuple = tuple(float(v) for v in corner)
    rod_radius = 0.5 * float(rod_diameter)
    centre_ext = (
        float(centre_extension_mm)
        if centre_extension_mm is not None
        else octant_centre_path_extension_mm(rod_radius)
    )
    corner_ext = (
        float(corner_extension_mm)
        if corner_extension_mm is not None
        else centre_ext
    )
    if both_end_extension or corner_extension_mm is not None:
        pipe_part = pipe_part_with_both_end_path_extension(
            part,
            centre_ext,
            corner_extension_mm=corner_ext,
        )
    else:
        pipe_part = pipe_part_with_centre_path_extension(part, centre_ext)
    oct_bounds = _octant_bounds_from_corner_mm(corner_tuple, cell_size_mm)
    align_bounds = _octant_bounds_from_corner_mm(
        corner_tuple,
        cell_size_mm,
        center_overlap_mm=OCTANT_CENTER_OVERLAP_MM,
    )

    slug = gen.variant_name.lower()
    ext_suffix = "_both_ext" if (both_end_extension or corner_extension_mm is not None) else ""
    case_dir = os.path.join(
        out_dir,
        f"inspect_{slug}_s{idx:02d}_{corner_tag}{ext_suffix}",
    )
    os.makedirs(case_dir, exist_ok=True)

    paths = {
        "pipe_extended": os.path.join(case_dir, "01_pipe_extended.step"),
        "cut_box": os.path.join(case_dir, "02_octant_cut_box.step"),
        "after_intersect": os.path.join(case_dir, "03_cut_after_intersect.step"),
        "after_align": os.path.join(case_dir, "04_cut_after_align.step"),
        "at_origin": os.path.join(case_dir, "05_cut_at_origin.step"),
    }

    def _build_pipe():
        pipe_tags = _occ_dimtags_from_parts([pipe_part])
        gmsh.model.occ.synchronize()
        return pipe_tags[0]

    def _build_box():
        return _occ_add_box_from_bounds(oct_bounds)

    def _build_after_intersect():
        import gmsh

        pipe_tags = _occ_dimtags_from_parts([pipe_part])
        gmsh.model.occ.synchronize()
        return _occ_octant_cut_single_pipe_tag(
            pipe_tags[0],
            pipe_part,
            cell_size_mm,
            progress_label=f"inspect-strut-{idx}",
        )

    def _build_after_align():
        cut_vol = _build_after_intersect()
        return _occ_align_single_cut_to_virtual_box(
            cut_vol,
            corner_tuple,
            cell_size_mm,
            center_overlap_mm=OCTANT_CENTER_OVERLAP_MM,
            progress_label=f"inspect-strut-{idx}-align",
        )

    def _build_at_origin():
        cut_vol = _build_after_align()
        return _occ_reposition_octant_cut_for_origin_assembly(
            cut_vol,
            corner_tuple,
            cell_size_mm,
            progress_label=f"inspect-strut-{idx}-origin",
        )

    reports: dict[str, dict] = {}
    reports["pipe_extended"] = _export_volume_in_fresh_session(
        model_name=f"inspect_{corner_tag}_pipe",
        build_volume=_build_pipe,
        out_path=paths["pipe_extended"],
    )
    reports["cut_box"] = _export_volume_in_fresh_session(
        model_name=f"inspect_{corner_tag}_box",
        build_volume=_build_box,
        out_path=paths["cut_box"],
    )
    reports["after_intersect"] = _export_volume_in_fresh_session(
        model_name=f"inspect_{corner_tag}_cut1",
        build_volume=_build_after_intersect,
        out_path=paths["after_intersect"],
    )
    reports["after_align"] = _export_volume_in_fresh_session(
        model_name=f"inspect_{corner_tag}_cut2",
        build_volume=_build_after_align,
        out_path=paths["after_align"],
    )
    reports["at_origin"] = _export_volume_in_fresh_session(
        model_name=f"inspect_{corner_tag}_cut3",
        build_volume=_build_at_origin,
        out_path=paths["at_origin"],
    )

    import gmsh

    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add(f"inspect_{corner_tag}_metrics")
        _configure_occ_for_fuse()
        pipe_tags = _occ_dimtags_from_parts([pipe_part])
        gmsh.model.occ.synchronize()
        pipe_mass = float(gmsh.model.occ.getMass(3, int(pipe_tags[0][1])))
        cut_vol = _build_at_origin()
        cut_mass = float(gmsh.model.occ.getMass(3, int(cut_vol[1])))
        bbox_origin = _bbox_mm(cut_vol)
    finally:
        gmsh.finalize()

    manifest = {
        "variant": gen.variant_name,
        "Q": float(period_factor),
        "strut_index": idx,
        "corner_mm": corner_tuple,
        "corner_tag": corner_tag,
        "centre_mm": tuple(float(v) for v in path_pts[0]),
        "centre_path_extension_mm": centre_ext,
        "corner_path_extension_mm": corner_ext
        if (both_end_extension or corner_extension_mm is not None)
        else 0.0,
        "both_end_extension": both_end_extension,
        "extended_start_mm": tuple(float(v) for v in pipe_part[1][0]),
        "extended_end_mm": tuple(float(v) for v in pipe_part[1][-1]),
        "pipe_mass_mm3": pipe_mass,
        "cut_mass_at_origin_mm3": cut_mass,
        "mass_ratio": cut_mass / pipe_mass if pipe_mass > 0 else None,
        "octant_cut_box_bounds_mm": oct_bounds,
        "align_box_bounds_mm": align_bounds,
        "center_overlap_mm": OCTANT_CENTER_OVERLAP_MM,
        "bbox_at_origin_mm": bbox_origin,
        "assembly_virtual_box_mm": unitcell_octant_assembly_bounds_mm(cell_size_mm),
        "assembly_scale": unitcell_octant_assembly_scale(corner_tuple, cell_size_mm),
        "inspect_dir": os.path.abspath(case_dir),
        "steps": {key: os.path.abspath(path) for key, path in paths.items()},
        "step_reports": reports,
        "method": "single_strut_octant_cut_inspection",
    }
    meta_path = os.path.join(case_dir, "inspect_manifest.json")
    with open(meta_path, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    manifest["manifest_path"] = os.path.abspath(meta_path)
    return manifest


def export_single_strut_paper_box_cut(
    *,
    period_factor: float,
    strut_index: int,
    cell_size_mm: float = 20.0,
    n_segments: int = 24,
    rod_diameter: float = 2.0,
    amplitude: float = 2.0,
    out_path: str,
    origin_assembly: bool = True,
    centre_extension_mm: float | None = None,
) -> dict:
    import gmsh

    gen = HuBaiLatticeGenerator(
        cell_size=float(cell_size_mm),
        rod_diameter=float(rod_diameter),
        amplitude=float(amplitude),
        period_factor=float(period_factor),
        n_segments=max(3, int(n_segments)),
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
    pipes = [p for p in pipes_only if p[0] == "pipe"]
    if not pipes:
        raise ValueError("No pipe primitives.")
    idx = int(strut_index)
    if idx < 1 or idx > len(pipes):
        raise ValueError(f"--strut must be 1..{len(pipes)}, got {idx}")

    part = pipes[idx - 1]
    path_pts = part[1]
    corner = path_pts[-1]
    corner_tag = _corner_tag(path_pts)
    rod_radius = 0.5 * float(rod_diameter)
    centre_ext = (
        float(centre_extension_mm)
        if centre_extension_mm is not None
        else octant_centre_path_extension_mm(rod_radius)
    )
    pipe_part = pipe_part_with_centre_path_extension(part, centre_ext)
    extended_start = pipe_part[1][0]

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)

    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add(f"single_strut_{corner_tag}")
        _configure_occ_for_fuse()

        pipe_tags = _occ_dimtags_from_parts([pipe_part])
        gmsh.model.occ.synchronize()
        pipe_mass = float(gmsh.model.occ.getMass(3, int(pipe_tags[0][1])))
        oct_bounds = _octant_bounds_from_corner_mm(corner, cell_size_mm)
        corner_tuple = tuple(float(v) for v in corner)

        cut_vol = _occ_octant_cut_single_pipe_tag(
            pipe_tags[0],
            pipe_part,
            cell_size_mm,
            progress_label=f"strut-{idx}",
        )
        cut_vol = _occ_align_single_cut_to_virtual_box(
            cut_vol,
            corner_tuple,
            cell_size_mm,
            center_overlap_mm=OCTANT_CENTER_OVERLAP_MM,
            progress_label=f"strut-{idx}-align",
        )
        if origin_assembly:
            cut_vol = _occ_reposition_octant_cut_for_origin_assembly(
                cut_vol,
                corner_tuple,
                cell_size_mm,
                progress_label=f"strut-{idx}-origin",
            )
        cut_mass = float(gmsh.model.occ.getMass(3, int(cut_vol[1])))
        bbox = _bbox_mm(cut_vol)
        assembly_bounds = unitcell_octant_assembly_bounds_mm(cell_size_mm)
        assembly_scale = unitcell_octant_assembly_scale(corner_tuple, cell_size_mm)
        # Drop uncut pipe and any boolean debris — only the octant-cut strut may remain.
        gmsh.model.occ.remove(pipe_tags, recursive=True)
        gmsh.model.occ.synchronize()
        _occ_remove_all_volumes_except(cut_vol)

        step_report = _finalize_occ_step_write(out_path, fuse=True, validate_step=False)
    finally:
        gmsh.finalize()

    step_report = _postprocess_written_step(
        out_path,
        step_report,
        fused_single=True,
        max_flatten_bodies=1,
    )
    try:
        step_report = analyze_step_for_solidworks(out_path, fused_single=True)
    except RuntimeError as exc:
        raise RuntimeError(
            f"STEP not SolidWorks-safe (orphan PRODUCTs → multi-window): {exc}"
        ) from exc

    return {
        "step_path": os.path.abspath(out_path),
        "variant": gen.variant_name,
        "Q": float(period_factor),
        "strut_index": idx,
        "corner_mm": tuple(float(v) for v in corner),
        "corner_tag": corner_tag,
        "centre_mm": tuple(float(v) for v in path_pts[0]),
        "centre_path_extension_mm": centre_ext,
        "extended_start_mm": tuple(float(v) for v in extended_start),
        "pipe_mass_mm3": pipe_mass,
        "cut_mass_mm3": cut_mass,
        "mass_ratio": cut_mass / pipe_mass if pipe_mass > 0 else None,
        "bbox_mm": bbox,
        "octant_bounds_mm": oct_bounds,
        "bbox_expected_mm": assembly_bounds if origin_assembly else oct_bounds,
        "origin_assembly": origin_assembly,
        "assembly_junction_mm": (0.0, 0.0, 0.0),
        "assembly_scale": assembly_scale,
        "assembly_virtual_box_mm": assembly_bounds,
        "fused_volume_count": step_report.get("solid_count"),
        "step_product_count": step_report.get("product_count"),
        "step_solidworks_safe": step_report.get("solidworks_safe"),
        "method": "single_strut_pipe_octant_1_8_box_cut",
        "pipe_open_centre": False,
        "octant_cut": True,
        "centre_weld": False,
        "size_bytes": os.path.getsize(out_path) if os.path.isfile(out_path) else 0,
    }


def main() -> int:
    p = argparse.ArgumentParser(description="Export one paper box-cut strut STEP")
    p.add_argument("--Q", type=float, default=1.0)
    p.add_argument("--strut", type=int, default=1, help="1..8 (centre-to-corner index)")
    p.add_argument("--list", action="store_true", help="Print strut corners and exit")
    p.add_argument("--L", type=float, default=20.0)
    p.add_argument("--Af", type=float, default=2.0)
    p.add_argument("--rod-d", type=float, default=2.0)
    p.add_argument("--n-segments", type=int, default=24)
    p.add_argument("--no-cut", action="store_true", help="Export full pipe only (no octant cut)")
    p.add_argument(
        "--cell-frame",
        action="store_true",
        help="Keep cut strut in cell frame (junction at cell centre, not origin-repositioned)",
    )
    p.add_argument("--all", action="store_true", help="Export all 8 cut struts")
    p.add_argument(
        "--centre-extension-mm",
        type=float,
        default=None,
        help="Extra path length past cell centre before cut (default: 1.5× rod radius, min 1 mm)",
    )
    p.add_argument(
        "--corner-extension-mm",
        type=float,
        default=None,
        help="Extra path length past cell corner before cut (default: same as centre extension)",
    )
    p.add_argument(
        "--both-end-extension",
        action="store_true",
        help="Extend path at centre and corner before cut (inspect / export)",
    )
    p.add_argument("--out", default="")
    p.add_argument(
        "--inspect",
        action="store_true",
        help=(
            "Export inspection STEPs: extended pipe, cut box, and 3 cut stages "
            "(intersect / align / origin assembly)"
        ),
    )
    p.add_argument(
        "--aligned-cut-out",
        default="",
        help="Export aligned octant-cut strut STEP (cell frame) to this path and exit",
    )
    args = p.parse_args()

    if args.aligned_cut_out:
        report = export_single_strut_aligned_octant_cut_step(
            period_factor=float(args.Q),
            strut_index=int(args.strut),
            out_path=args.aligned_cut_out,
            cell_size_mm=float(args.L),
            n_segments=int(args.n_segments),
            rod_diameter=float(args.rod_d),
            amplitude=float(args.Af),
            both_end_extension=args.both_end_extension or True,
            centre_extension_mm=args.centre_extension_mm,
            corner_extension_mm=args.corner_extension_mm,
        )
        print(f"Wrote: {report['step_path']}", flush=True)
        return 0

    gen = HuBaiLatticeGenerator(
        cell_size=float(args.L),
        rod_diameter=float(args.rod_d),
        amplitude=float(args.Af),
        period_factor=float(args.Q),
        n_segments=max(3, int(args.n_segments)),
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
    pipes = [p for p in pipes_only if p[0] == "pipe"]

    if args.list:
        print(f"{gen.variant_name}  struts={len(pipes)}", flush=True)
        for i, part in enumerate(pipes, start=1):
            c = part[1][-1]
            print(
                f"  {i}: corner=({c[0]:g}, {c[1]:g}, {c[2]:g})  tag={_corner_tag(part[1])}",
                flush=True,
            )
        return 0

    out_dir = os.path.join(str(CAD_ROOT), "_single_strut_paper_box_cut")
    slug = gen.variant_name.lower()
    strut_indices = list(range(1, len(pipes) + 1)) if args.all else [int(args.strut)]

    if args.inspect:
        if args.all:
            raise SystemExit("--inspect does not support --all (pick one --strut)")
        manifest = export_single_strut_cut_inspection(
            period_factor=float(args.Q),
            strut_index=int(args.strut),
            cell_size_mm=float(args.L),
            n_segments=int(args.n_segments),
            rod_diameter=float(args.rod_d),
            amplitude=float(args.Af),
            out_dir=out_dir,
            centre_extension_mm=args.centre_extension_mm,
            corner_extension_mm=args.corner_extension_mm,
            both_end_extension=args.both_end_extension,
        )
        print(f"Inspect dir: {manifest['inspect_dir']}", flush=True)
        for key, path in manifest["steps"].items():
            rep = manifest["step_reports"].get(key, {})
            print(
                f"  {os.path.basename(path)}  "
                f"products={rep.get('step_product_count')} "
                f"solids={rep.get('fused_volume_count')} "
                f"sw_safe={rep.get('step_solidworks_safe')}",
                flush=True,
            )
        print(
            f"  strut {manifest['strut_index']} corner={manifest['corner_mm']} "
            f"centre_ext={manifest['centre_path_extension_mm']:.3g} mm "
            f"corner_ext={manifest['corner_path_extension_mm']:.3g} mm "
            f"both_ends={manifest['both_end_extension']} "
            f"pipe_mass={manifest['pipe_mass_mm3']:.1f} mm3 "
            f"cut_mass={manifest['cut_mass_at_origin_mm3']:.1f} mm3 "
            f"cut_box={manifest['octant_cut_box_bounds_mm']}",
            flush=True,
        )
        print(f"Manifest: {manifest['manifest_path']}", flush=True)
        print(
            "  SolidWorks: insert 01+02 at origin to check pipe vs box; "
            "03/04 are cell frame, 05 is origin assembly [0,L/2]^3.",
            flush=True,
        )
        return 0

    reports: list[dict] = []
    for strut_idx in strut_indices:
        corner_tag = _corner_tag(pipes[strut_idx - 1][1])
        if args.no_cut:
            out_path = args.out if len(strut_indices) == 1 and args.out else os.path.join(
                out_dir,
                f"single_strut_{slug}_s{strut_idx:02d}_{corner_tag}_raw.step",
            )
            report = export_single_strut_raw(
                period_factor=float(args.Q),
                strut_index=strut_idx,
                cell_size_mm=float(args.L),
                n_segments=int(args.n_segments),
                rod_diameter=float(args.rod_d),
                amplitude=float(args.Af),
                out_path=out_path,
            )
        else:
            suffix = "octant" if args.cell_frame else "octant_at_origin"
            out_path = args.out if len(strut_indices) == 1 and args.out else os.path.join(
                out_dir,
                f"single_strut_{slug}_s{strut_idx:02d}_{corner_tag}_{suffix}.step",
            )
            report = export_single_strut_paper_box_cut(
                period_factor=float(args.Q),
                strut_index=strut_idx,
                cell_size_mm=float(args.L),
                n_segments=int(args.n_segments),
                rod_diameter=float(args.rod_d),
                amplitude=float(args.Af),
                out_path=out_path,
                origin_assembly=not args.cell_frame,
                centre_extension_mm=args.centre_extension_mm,
            )

        meta_path = os.path.splitext(out_path)[0] + "_meta.json"
        with open(meta_path, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2, ensure_ascii=False)
            fh.write("\n")

        reports.append(report)
        print(f"Wrote: {report['step_path']}", flush=True)
        if report.get("octant_cut") is False:
            print(
                f"  strut {report['strut_index']} corner={report['corner_mm']} "
                f"centre={report['centre_mm']} "
                f"p1={report['first_interior_mm']} "
                f"chord0={report['first_chord_length_mm']:.3f} mm "
                f"pipe_mass={report['pipe_mass_mm3']:.1f} mm3 "
                f"products={report.get('step_product_count')} "
                f"solids={report.get('fused_volume_count')} "
                f"sw_safe={report['step_solidworks_safe']}",
                flush=True,
            )
        else:
            origin_note = (
                f" junction={report.get('assembly_junction_mm')} "
                f"virtual_box={report.get('assembly_virtual_box_mm')} "
                if report.get("origin_assembly")
                else " cell-frame "
            )
            print(
                f"  strut {report['strut_index']} corner={report['corner_mm']} "
                f"cut_mass={report['cut_mass_mm3']:.1f} mm3 "
                f"{origin_note}"
                f"products={report.get('step_product_count')} "
                f"solids={report.get('fused_volume_count')} "
                f"sw_safe={report['step_solidworks_safe']}",
                flush=True,
            )
        print(f"Meta: {meta_path}", flush=True)

    if len(reports) > 1:
        print(f"Exported {len(reports)} strut(s) to {out_dir}", flush=True)
    print(
        "  SolidWorks: open each STEP separately; with --all, insert 8 parts at origin to assemble.",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
