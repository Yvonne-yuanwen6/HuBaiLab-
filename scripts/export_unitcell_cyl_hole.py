"""
Pilot: square L³ unit-cell outer envelope + central cylindrical through-hole (Z).

Builds a Q=0 BCC 1×1 solid (paper-box / OCP), then subtracts a coaxial cylinder.

  py -3 scripts/export_unitcell_cyl_hole.py
  py -3 scripts/export_unitcell_cyl_hole.py --R-hole 4 --L 20 --rod-d 2

Does not write into verified batch trees; output under output/cad/_unitcell_cyl_hole/.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from src.export.ocp_unitcell_fuse import (
    ocp_cut_central_cylinder_z,
    ocp_shape_topology,
    ocp_write_step,
)
from src.export.unitcell_box_cut import export_unitcell_step_paper_box_cut
from src.generator.hu_bai_bcc import HuBaiLatticeGenerator
from src.paths import CAD_ROOT, ensure_output_dirs

ensure_output_dirs()


def _bbox_of_shape(shape) -> tuple[float, float, float, float, float, float]:
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib

    box = Bnd_Box()
    BRepBndLib.Add_s(shape, box)
    xmin, ymin, zmin, xmax, ymax, zmax = box.Get()
    return (xmin, xmax, ymin, ymax, zmin, zmax)


def _bbox_within_rve(
    bbox: tuple[float, float, float, float, float, float],
    cell_size_mm: float,
) -> tuple[bool, float, float]:
    """Match paper-box overshoot gate: tol = max(0.5, 0.05*L)."""
    h = 0.5 * float(cell_size_mm)
    tol = max(0.5, 0.05 * float(cell_size_mm))
    xmin, xmax, ymin, ymax, zmin, zmax = bbox
    overshoot = max(
        (-h) - xmin,
        xmax - h,
        (-h) - ymin,
        ymax - h,
        (-h) - zmin,
        zmax - h,
    )
    return overshoot <= tol, float(overshoot), float(tol)


def _load_step_shape(path: str, *, require_one_solid: bool = True):
    """Load STEP; optionally allow multi-body (large holes sever the BCC hub)."""
    from OCP.STEPControl import STEPControl_Reader

    from src.export.ocp_unitcell_fuse import ocp_shape_topology

    path = os.path.abspath(path)
    reader = STEPControl_Reader()
    if reader.ReadFile(path) != 1:
        raise RuntimeError(f"OCP STEP read failed: {path}")
    reader.TransferRoots()
    shape = reader.OneShape()
    if require_one_solid:
        stats = ocp_shape_topology(shape, count_faces=False, check_brep=False)
        if int(stats.get("solids") or 0) != 1:
            raise RuntimeError(
                f"OCP STEP must be 1 solid, got {stats.get('solids')} solid(s): {path}"
            )
    return shape


def build_q0_seed_step(
    seed_path: str,
    *,
    L: float,
    rod_d: float,
    Af: float,
    n_segments: int,
) -> dict:
    gen = HuBaiLatticeGenerator(
        cell_size=float(L),
        rod_diameter=float(rod_d),
        amplitude=float(Af),
        period_factor=0.0,
        n_segments=max(3, int(n_segments)),
    )
    gen.build_unitcell()
    nodes, beams, polylines = gen.get_data(copy=True)
    print(f"Build Q=0 seed ({gen.variant_name}) -> {seed_path}", flush=True)
    report = export_unitcell_step_paper_box_cut(
        nodes,
        beams,
        seed_path,
        polylines=polylines,
        cell_size_mm=float(L),
        n_segments_hint=max(3, int(n_segments)),
        period_factor=0.0,
        rod_diameter_mm=float(rod_d),
        amplitude_mm=float(Af),
        solid_profile="circle",
    )
    return {
        "variant": gen.variant_name,
        "seed_step": os.path.abspath(seed_path),
        **report,
    }


def main() -> int:
    p = argparse.ArgumentParser(
        description="Export 1×1 unit cell with central Z cylindrical hole (square outer)"
    )
    p.add_argument("--L", type=float, default=20.0, help="Unit cell edge [mm]")
    p.add_argument("--rod-d", type=float, default=2.0, help="Rod diameter [mm]")
    p.add_argument("--Af", type=float, default=2.0, help="Amplitude (unused for Q=0)")
    p.add_argument(
        "--R-hole",
        type=float,
        default=4.0,
        help="Hole radius [mm] (L=20 d=2: R<=~1.2 keeps 1 solid; R>=1.5 severs hub)",
    )
    p.add_argument(
        "--R-hole-list",
        type=float,
        nargs="*",
        default=None,
        help="Optional list of radii (default: single --R-hole; smoke: 1.2 3 4 5)",
    )
    p.add_argument(
        "--require-one-solid",
        action="store_true",
        help="Fail if any cut produces solids != 1",
    )
    p.add_argument("--n-segments", type=int, default=12)
    p.add_argument(
        "--overshoot-mm",
        type=float,
        default=0.1,
        help="Cylinder extends beyond ±L/2 by this amount [mm]",
    )
    p.add_argument("--out-dir", default="")
    p.add_argument(
        "--seed-step",
        default="",
        help="Reuse an existing Q=0 paper-box STEP instead of rebuilding",
    )
    args = p.parse_args()

    out_dir = args.out_dir or os.path.join(str(CAD_ROOT), "_unitcell_cyl_hole")
    os.makedirs(out_dir, exist_ok=True)

    radii = list(args.R_hole_list) if args.R_hole_list else [float(args.R_hole)]
    L = float(args.L)
    rod_d = float(args.rod_d)

    if args.seed_step:
        seed_path = os.path.abspath(args.seed_step)
        if not os.path.isfile(seed_path):
            raise FileNotFoundError(seed_path)
        seed_report = {
            "variant": "BCC_AF?Q0",
            "seed_step": seed_path,
            "reused_seed": True,
        }
        print(f"Reuse seed STEP: {seed_path}", flush=True)
    else:
        seed_path = os.path.join(out_dir, f"unitcell_bcc_L{L:g}_d{rod_d:g}_Q0_seed.step")
        seed_report = build_q0_seed_step(
            seed_path,
            L=L,
            rod_d=rod_d,
            Af=float(args.Af),
            n_segments=int(args.n_segments),
        )
        seed_report["reused_seed"] = False

    shape0 = _load_step_shape(seed_path)
    topo0 = ocp_shape_topology(shape0, count_faces=False, check_brep=True)
    print(
        f"Seed solids={topo0['solids']} mass={topo0['mass_mm3']:.2f} mm3 "
        f"brep_valid={topo0.get('brep_valid')}",
        flush=True,
    )

    manifest: dict = {
        "out_dir": os.path.abspath(out_dir),
        "cell_size_mm": L,
        "rod_diameter_mm": rod_d,
        "Q": 0.0,
        "axis": "z",
        "seed": seed_report,
        "seed_topology": topo0,
        "holes": [],
    }

    for r_hole in radii:
        tag = f"R{r_hole:g}".replace(".", "p")
        out_step = os.path.join(
            out_dir,
            f"unitcell_bcc_L{L:g}_d{rod_d:g}_Q0_cylhole_{tag}.step",
        )
        print(f"Cut central cylinder R={r_hole:g} mm -> {out_step}", flush=True)
        cut_shape, cut_rep = ocp_cut_central_cylinder_z(
            shape0,
            radius_mm=float(r_hole),
            cell_size_mm=L,
            overshoot_mm=float(args.overshoot_mm),
        )
        ocp_write_step(cut_shape, out_step)
        bbox = _bbox_of_shape(cut_shape)
        bbox_ok, overshoot, bbox_tol = _bbox_within_rve(bbox, L)
        entry = {
            **cut_rep,
            "step": os.path.abspath(out_step),
            "size_bytes": os.path.getsize(out_step),
            "bbox_xmin_xmax_ymin_ymax_zmin_zmax": list(bbox),
            "bbox_overshoot_mm": overshoot,
            "bbox_overshoot_tolerance_mm": bbox_tol,
            "bbox_within_rve": bbox_ok,
            "fused_volume_count": int(cut_rep["solids_after"]),
        }
        # Sanity read-back (multi-body allowed when hub is severed)
        rb = ocp_shape_topology(
            _load_step_shape(out_step, require_one_solid=False),
            count_faces=False,
            check_brep=True,
        )
        entry["step_readback"] = rb
        entry["single_solid"] = int(rb.get("solids") or 0) == 1
        # SW can open compounds; "safe" here = valid BRep + bbox, not necessarily 1 solid
        entry["step_solidworks_safe"] = bool(
            rb.get("brep_valid") and entry["bbox_within_rve"] and int(rb.get("solids") or 0) >= 1
        )
        manifest["holes"].append(entry)
        print(
            f"  mass {cut_rep['mass_before_mm3']:.1f} -> {cut_rep['mass_after_mm3']:.1f} "
            f"(removed {cut_rep['mass_removed_mm3']:.1f}) "
            f"solids={cut_rep['solids_after']} "
            f"single={entry['single_solid']} "
            f"bbox_ok={entry['bbox_within_rve']} "
            f"sw_safe={entry['step_solidworks_safe']}",
            flush=True,
        )

    manifest_path = os.path.join(out_dir, "manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    print(f"\nManifest: {manifest_path}", flush=True)
    print(
        "Open one STEP in SolidWorks: expect 1 part, square outer, circular Z hole.",
        flush=True,
    )

    require_one = bool(args.require_one_solid)
    bad = []
    for h in manifest["holes"]:
        if float(h.get("mass_removed_mm3", 0.0)) <= 0.0 or not h.get("bbox_within_rve"):
            bad.append(h)
        elif require_one and int(h.get("solids_after", 0)) != 1:
            bad.append(h)
    multi = [h for h in manifest["holes"] if int(h.get("solids_after", 0)) != 1]
    if multi and not require_one:
        print(
            f"[NOTE] {len(multi)} case(s) are multi-body "
            "(central hole severed BCC hub; expected for R>~1.2 mm at L=20 d=2).",
            flush=True,
        )
    if bad:
        print(f"[FAIL] {len(bad)} hole case(s) failed QC", flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
