"""
Export one Q=1 *group strut*: two single struts merged into one continuous centreline
and one pipe sweep (corner → cell centre → opposite corner).

Example pairing (body diagonal through origin):
  strut 1 (mmm) + strut 8 (ppp)  →  (-L/2,-L/2,-L/2) → (0,0,0) → (+L/2,+L/2,+L/2)

  py -3 scripts/export_paired_strut_group_demo.py
  py -3 scripts/export_paired_strut_group_demo.py --strut-a 1 --strut-b 2
  py -3 scripts/export_paired_strut_group_demo.py --list-pairs
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
from src.export.unitcell_box_cut import _bbox_mm
from src.export.sw_parasolid import analyze_step_for_solidworks
from src.generator.hu_bai_bcc import HuBaiLatticeGenerator
from src.paths import CAD_ROOT, ensure_output_dirs

ensure_output_dirs()

# Default: four body diagonals (opposite corners through cell centre).
DEFAULT_STRUT_PAIRS_1BASED: tuple[tuple[int, int], ...] = (
    (1, 8),  # mmm ↔ ppp
    (2, 7),  # pmm ↔ mpp
    (3, 6),  # mpm ↔ pmp
    (4, 5),  # ppm ↔ mmp
)


def _corner_tag(path_pts: tuple) -> str:
    x, y, z = (float(path_pts[-1][0]), float(path_pts[-1][1]), float(path_pts[-1][2]))
    sx = "p" if x > 0 else "m"
    sy = "p" if y > 0 else "m"
    sz = "p" if z > 0 else "m"
    return f"{sx}{sy}{sz}"


def merge_strut_paths_through_centre(
    path_a: tuple[tuple[float, ...], ...],
    path_b: tuple[tuple[float, ...], ...],
    *,
    centre_tol: float = 1e-3,
) -> tuple[tuple[float, float, float], ...]:
    """
    Merge two centre→corner polylines into one corner→centre→corner path.

    Each input path starts at the cell centre (0,0,0) and ends at its corner.
    Output is one continuous polyline for a single pipe sweep.
    """
    pts_a = [tuple(float(v) for v in p) for p in path_a]
    pts_b = [tuple(float(v) for v in p) for p in path_b]
    if len(pts_a) < 2 or len(pts_b) < 2:
        raise ValueError("Each strut path needs at least two points.")

    centre_a, corner_a = pts_a[0], pts_a[-1]
    centre_b, corner_b = pts_b[0], pts_b[-1]
    if any(abs(centre_a[i] - centre_b[i]) > centre_tol for i in range(3)):
        raise ValueError(
            f"Strut centre endpoints differ: {centre_a} vs {centre_b}"
        )

    # corner_a → … → centre → … → corner_b  (one wire, one pipe)
    merged: list[tuple[float, float, float]] = list(reversed(pts_a))
    merged.extend(pts_b[1:])
    return tuple(merged)


def load_q1_pipes(
    *,
    cell_size_mm: float,
    rod_diameter: float,
    amplitude: float,
    n_segments: int,
) -> list[tuple[str, tuple, float]]:
    gen = HuBaiLatticeGenerator(
        cell_size=float(cell_size_mm),
        rod_diameter=float(rod_diameter),
        amplitude=float(amplitude),
        period_factor=1.0,
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
    if len(pipes) != 8:
        raise ValueError(f"Expected 8 pipe struts, got {len(pipes)}")
    return pipes


def export_group_strut_step(
    *,
    strut_a: int,
    strut_b: int,
    out_path: str,
    cell_size_mm: float = 20.0,
    rod_diameter: float = 2.0,
    amplitude: float = 2.0,
    n_segments: int = 24,
) -> dict:
    """Export one group strut STEP (full pipe, no box cut — geometry QA)."""
    import gmsh

    pipes = load_q1_pipes(
        cell_size_mm=cell_size_mm,
        rod_diameter=rod_diameter,
        amplitude=amplitude,
        n_segments=n_segments,
    )
    ia, ib = int(strut_a) - 1, int(strut_b) - 1
    if ia < 0 or ib < 0 or ia >= 8 or ib >= 8:
        raise ValueError(f"--strut-a/b must be 1..8, got {strut_a} and {strut_b}")

    part_a, part_b = pipes[ia], pipes[ib]
    merged_path = merge_strut_paths_through_centre(part_a[1], part_b[1])
    radius = float(part_a[2])
    tag_a, tag_b = _corner_tag(part_a[1]), _corner_tag(part_b[1])
    group_part: tuple[str, tuple, float] = ("pipe", merged_path, radius)

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)

    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add(f"group_{tag_a}_{tag_b}")
        _configure_occ_for_fuse()
        vol_tag = _occ_dimtags_from_parts([group_part])[0]
        gmsh.model.occ.synchronize()
        mass = float(gmsh.model.occ.getMass(3, int(vol_tag[1])))
        bbox = _bbox_mm(vol_tag)
        _occ_remove_all_volumes_except(vol_tag)
        step_report = _finalize_occ_step_write(out_path, fuse=True, validate_step=False)
    finally:
        gmsh.finalize()

    sw = analyze_step_for_solidworks(out_path)
    report = {
        "strut_a_1based": strut_a,
        "strut_b_1based": strut_b,
        "corner_a": tag_a,
        "corner_b": tag_b,
        "path_points": len(merged_path),
        "centre_index": len(part_a[1]) - 1,
        "corner_a_mm": tuple(float(v) for v in part_a[1][-1]),
        "corner_b_mm": tuple(float(v) for v in part_b[1][-1]),
        "mass_mm3": mass,
        "bbox_mm": bbox,
        "step_path": os.path.abspath(out_path),
        "solid_count": int(step_report.get("solid_count", 0)),
        "sw_safe": bool(sw.get("solidworks_safe", False)),
        "merge_rule": "corner_a -> centre -> corner_b (single pipe sweep)",
    }
    _postprocess_written_step(out_path, report)
    return report


def main() -> None:
    p = argparse.ArgumentParser(description="Export one Q=1 paired group strut STEP.")
    p.add_argument("--strut-a", type=int, default=1, help="First strut index 1..8")
    p.add_argument("--strut-b", type=int, default=8, help="Second strut index 1..8")
    p.add_argument("--L", type=float, default=20.0)
    p.add_argument("--rod-d", type=float, default=2.0)
    p.add_argument("--Af", type=float, default=2.0)
    p.add_argument("--n-segments", type=int, default=24)
    p.add_argument(
        "--out",
        default="",
        help="Output STEP (default: output/cad/.../group_strut_*.step)",
    )
    p.add_argument(
        "--list-pairs",
        action="store_true",
        help="Print default four diagonal pairings and exit",
    )
    args = p.parse_args()

    if args.list_pairs:
        pipes = load_q1_pipes(
            cell_size_mm=args.L,
            rod_diameter=args.rod_d,
            amplitude=args.Af,
            n_segments=args.n_segments,
        )
        print("Default group pairings (body diagonals through centre):")
        for a, b in DEFAULT_STRUT_PAIRS_1BASED:
            ta, tb = _corner_tag(pipes[a - 1][1]), _corner_tag(pipes[b - 1][1])
            print(f"  group: strut {a} ({ta}) + strut {b} ({tb})")
        return

    ia, ib = int(args.strut_a), int(args.strut_b)
    pipes = load_q1_pipes(
        cell_size_mm=args.L,
        rod_diameter=args.rod_d,
        amplitude=args.Af,
        n_segments=args.n_segments,
    )
    ta = _corner_tag(pipes[ia - 1][1])
    tb = _corner_tag(pipes[ib - 1][1])
    out = args.out.strip() or os.path.join(
        CAD_ROOT,
        "_unitcell_paper_box_cut",
        "demo",
        f"group_strut_{ia}_{ta}__{ib}_{tb}.step",
    )

    report = export_group_strut_step(
        strut_a=ia,
        strut_b=ib,
        out_path=out,
        cell_size_mm=args.L,
        rod_diameter=args.rod_d,
        amplitude=args.Af,
        n_segments=args.n_segments,
    )
    meta_path = os.path.splitext(out)[0] + ".json"
    with open(meta_path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)

    print(f"Group strut STEP: {out}")
    print(
        f"  strut {ia} ({report['corner_a']}) + strut {ib} ({report['corner_b']}) "
        f"-> one pipe, {report['path_points']} path pts, "
        f"centre at index {report['centre_index']}"
    )
    print(
        f"  corners: {report['corner_a_mm']} <-> {report['corner_b_mm']} "
        f"(through origin)"
    )
    print(
        f"  mass={report['mass_mm3']:.1f} mm3  vol={report['solid_count']}  "
        f"sw_safe={report['sw_safe']}"
    )
    print(f"  metadata: {meta_path}")
    print("Open in SolidWorks: expect ONE solid, two bent arms meeting at (0,0,0).")


if __name__ == "__main__":
    main()
