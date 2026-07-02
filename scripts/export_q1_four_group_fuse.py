"""
Q=1 unit cell via four group-strut pipe sweeps + OCC fuse.

Each group strut merges two opposite single struts into one corner→centre→corner
polyline and one pipe solid. Four groups fuse to one unit-cell solid.

  py -3 scripts/export_q1_four_group_fuse.py
  py -3 scripts/export_q1_four_group_fuse.py --strategy sequential
"""

from __future__ import annotations

import argparse
import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from scripts.export_paired_strut_group_demo import (
    DEFAULT_STRUT_PAIRS_1BASED,
    load_q1_pipes,
    merge_strut_paths_through_centre,
)
from src.export.export_sw import (
    _configure_occ_for_fuse,
    _finalize_occ_step_write,
    _occ_dimtags_from_parts,
    _occ_list_volume_dimtags,
    _occ_primary_volume,
    _occ_remove_all_volumes_except,
    _occ_volumes_mass,
    _postprocess_written_step,
)
from src.export.unitcell_box_cut import (
    MIN_CUT_MERGE_MASS_RATIO,
    _bbox_mm,
    _occ_build_aligned_octant_cut_volumes,
    _occ_intersect_volumes_with_box,
)
from src.export.sw_parasolid import analyze_step_for_solidworks
from src.mesh.occ_pipe import prune_occ_for_step_export
from src.paths import CAD_ROOT, ensure_output_dirs

ensure_output_dirs()

# Target from proven 8-strut octant sequential fuse (L=20, d=2, Af=2, Q=1).
REFERENCE_UNITCELL_MASS_MM3 = 381.3


def build_group_pipe_parts(
    pipes: list[tuple[str, tuple, float]],
    pairs: tuple[tuple[int, int], ...] = DEFAULT_STRUT_PAIRS_1BASED,
) -> list[tuple[str, tuple, float]]:
    """Four corner→centre→corner pipe parts (one solid sweep each)."""
    group_parts: list[tuple[str, tuple, float]] = []
    for a, b in pairs:
        part_a, part_b = pipes[a - 1], pipes[b - 1]
        merged = merge_strut_paths_through_centre(part_a[1], part_b[1])
        group_parts.append(("pipe", merged, float(part_a[2])))
    return group_parts


def _occ_build_group_volumes(
    group_parts: list[tuple[str, tuple, float]],
) -> list[tuple[int, int]]:
    import gmsh

    vols: list[tuple[int, int]] = []
    for idx, part in enumerate(group_parts, start=1):
        tag = _occ_dimtags_from_parts([part])[0]
        gmsh.model.occ.synchronize()
        vols.append(tag)
        mass = float(gmsh.model.occ.getMass(3, int(tag[1])))
        corners = part[1][0], part[1][-1]
        print(
            f"  group {idx}/4: pipe mass={mass:.1f} mm3 "
            f"({corners[0]} -> {corners[1]})",
            flush=True,
        )
    junk = [v for v in _occ_list_volume_dimtags() if v not in set(vols)]
    if junk:
        from src.export.export_sw import _occ_remove_volumes_in_set

        _occ_remove_volumes_in_set(set(junk), vols[0])
    return vols


def _fuse_four_sequential(
    vols: list[tuple[int, int]],
    *,
    ref_mass: float,
    progress_label: str = "group-sequential",
) -> tuple[int, int]:
    import gmsh

    if len(vols) != 4:
        raise ValueError(f"expected 4 group volumes, got {len(vols)}")
    min_mass = MIN_CUT_MERGE_MASS_RATIO * ref_mass
    mean_piece = ref_mass / 4.0
    min_step_delta = 0.20 * mean_piece

    acc = vols[0]
    for idx, vol in enumerate(vols[1:], start=2):
        prev_mass = float(gmsh.model.occ.getMass(3, int(acc[1])))
        vol_mass = float(gmsh.model.occ.getMass(3, int(vol[1])))
        prev_acc = acc
        fused, _ = gmsh.model.occ.fuse([acc], [vol])
        gmsh.model.occ.synchronize()
        outs = [(3, int(t)) for dim, t in fused if dim == 3]
        if not outs:
            raise RuntimeError(f"{progress_label}: empty fuse at group {idx}/4")
        acc = _occ_primary_volume(outs) if len(outs) > 1 else outs[0]
        new_mass = float(gmsh.model.occ.getMass(3, int(acc[1])))
        if new_mass < prev_mass + min_step_delta:
            raise RuntimeError(
                f"{progress_label}: group {idx}/4 not merged "
                f"(mass {new_mass:.1f} mm3, need >= {prev_mass + min_step_delta:.1f}; "
                f"group ~{vol_mass:.1f} mm3)"
            )
        from src.export.export_sw import _occ_remove_volumes_in_set

        _occ_remove_volumes_in_set({prev_acc, vol}, acc)
        print(
            f"  {progress_label}: fused group {idx}/4 (mass={new_mass:.1f} mm3)",
            flush=True,
        )

    merged_mass = float(gmsh.model.occ.getMass(3, int(acc[1])))
    if merged_mass < min_mass:
        raise RuntimeError(
            f"{progress_label}: merged mass {merged_mass:.1f} < {min_mass:.1f} mm3"
        )
    _occ_remove_all_volumes_except(acc)
    return acc


def _fuse_four_batch(
    vols: list[tuple[int, int]],
    *,
    ref_mass: float,
    progress_label: str = "group-batch",
) -> tuple[int, int]:
    import gmsh

    fused, _ = gmsh.model.occ.fuse([vols[0]], vols[1:])
    gmsh.model.occ.synchronize()
    outs = [(3, int(t)) for dim, t in fused if dim == 3]
    if not outs:
        raise RuntimeError(f"{progress_label}: batch fuse empty")
    acc = _occ_primary_volume(outs)
    merged_mass = float(gmsh.model.occ.getMass(3, int(acc[1])))
    min_mass = MIN_CUT_MERGE_MASS_RATIO * ref_mass
    if merged_mass < min_mass:
        raise RuntimeError(
            f"{progress_label}: batch mass {merged_mass:.1f} < {min_mass:.1f} mm3"
        )
    _occ_remove_all_volumes_except(acc)
    print(f"  {progress_label}: batch OK (mass={merged_mass:.1f} mm3)", flush=True)
    return acc


def export_four_group_fused_unitcell(
    *,
    out_path: str,
    cell_size_mm: float = 20.0,
    rod_diameter: float = 2.0,
    amplitude: float = 2.0,
    n_segments: int = 24,
    strategy: str = "sequential",
    box_cut: bool = True,
) -> dict:
    import gmsh

    pipes = load_q1_pipes(
        cell_size_mm=cell_size_mm,
        rod_diameter=rod_diameter,
        amplitude=amplitude,
        n_segments=n_segments,
    )
    group_parts = build_group_pipe_parts(pipes)

    # Reference: 8-strut octant cut sum (same session baseline).
    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add("ref")
        _configure_occ_for_fuse()
        _, ref_mass = _occ_build_aligned_octant_cut_volumes(
            pipes,
            cell_size_mm,
            progress_label="octant-ref",
            pipe_centre_stub=True,
        )
    finally:
        gmsh.finalize()

    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add("four_group_fuse")
        _configure_occ_for_fuse()

        print("  Four-group fuse: building 4 pipe solids...", flush=True)
        vols = _occ_build_group_volumes(group_parts)
        group_sum = _occ_volumes_mass(vols)
        print(f"  group pipe sum (overlap at centre): {group_sum:.1f} mm3", flush=True)
        print(f"  octant 8-strut reference: {ref_mass:.1f} mm3", flush=True)

        strat = strategy.strip().lower()
        if strat == "batch":
            merged = _fuse_four_batch(vols, ref_mass=ref_mass)
            merge_strategy = "4 group pipes batch fuse"
        elif strat == "sequential":
            merged = _fuse_four_sequential(vols, ref_mass=ref_mass)
            merge_strategy = "4 group pipes sequential fuse"
        else:
            raise ValueError(f"strategy must be sequential|batch, got {strategy!r}")

        fused_mass = float(gmsh.model.occ.getMass(3, int(merged[1])))
        if box_cut:
            merged = _occ_intersect_volumes_with_box(
                [merged],
                cell_size_mm,
                progress_label="group-fuse-box",
            )
            final_mass = float(gmsh.model.occ.getMass(3, int(merged[1])))
        else:
            final_mass = fused_mass

        ratio = final_mass / ref_mass if ref_mass > 0 else 0.0
        bbox = _bbox_mm(merged)
        prune_occ_for_step_export()
        _occ_remove_all_volumes_except(merged)

        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
        step_report = _finalize_occ_step_write(out_path, fuse=True, validate_step=False)
    finally:
        gmsh.finalize()

    sw = analyze_step_for_solidworks(out_path)
    report = {
        "method": "gmsh_occ_four_group_fuse",
        "merge_strategy": merge_strategy,
        "strategy": strat,
        "box_cut": box_cut,
        "group_pipe_sum_mm3": group_sum,
        "octant_ref_mass_mm3": ref_mass,
        "fused_mass_mm3": fused_mass,
        "final_mass_mm3": final_mass,
        "mass_ratio_vs_octant_ref": ratio,
        "reference_target_mm3": REFERENCE_UNITCELL_MASS_MM3,
        "bbox_mm": bbox,
        "step_path": os.path.abspath(out_path),
        "solid_count": int(step_report.get("solid_count", 0)),
        "sw_safe": bool(sw.get("solidworks_safe", False)),
        "pairs_1based": list(DEFAULT_STRUT_PAIRS_1BASED),
    }
    _postprocess_written_step(out_path, report)
    return report


def main() -> None:
    p = argparse.ArgumentParser(description="Q=1 unitcell: fuse 4 group struts.")
    p.add_argument("--strategy", choices=("sequential", "batch"), default="sequential")
    p.add_argument("--no-box-cut", action="store_true")
    p.add_argument("--L", type=float, default=20.0)
    p.add_argument("--rod-d", type=float, default=2.0)
    p.add_argument("--Af", type=float, default=2.0)
    p.add_argument("--n-segments", type=int, default=24)
    p.add_argument(
        "--out",
        default=os.path.join(
            CAD_ROOT,
            "_unitcell_paper_box_cut",
            "unitcell_sfbls_af2q1_four_group_fused.step",
        ),
    )
    args = p.parse_args()

    report = export_four_group_fused_unitcell(
        out_path=args.out,
        cell_size_mm=args.L,
        rod_diameter=args.rod_d,
        amplitude=args.Af,
        n_segments=args.n_segments,
        strategy=args.strategy,
        box_cut=not args.no_box_cut,
    )
    meta = os.path.splitext(args.out)[0] + ".json"
    with open(meta, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)

    ok = report["mass_ratio_vs_octant_ref"] >= MIN_CUT_MERGE_MASS_RATIO
    print(f"STEP: {report['step_path']}")
    print(
        f"  {report['merge_strategy']} + "
        f"{'L3 box-cut' if report['box_cut'] else 'no box-cut'}"
    )
    print(
        f"  final mass={report['final_mass_mm3']:.1f} mm3  "
        f"ratio={report['mass_ratio_vs_octant_ref']:.3f} "
        f"(ref {report['octant_ref_mass_mm3']:.1f})  "
        f"vol={report['solid_count']} sw_safe={report['sw_safe']}"
    )
    print(f"  metadata: {meta}")
    print(f"  {'OK' if ok else 'WARN'} (need ratio >= {MIN_CUT_MERGE_MASS_RATIO:.2f})")


if __name__ == "__main__":
    main()
