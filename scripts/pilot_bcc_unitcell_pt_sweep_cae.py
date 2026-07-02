#!/usr/bin/env python3
"""
Pilot: BCC unit-cell ellipse_major with parallel-transport sweep (no junction sphere).

Exports one STEP, optionally runs Abaqus CAE C3D4 mesh probe (Linux server / --mesh-locally).

Example:
  py -3 scripts/pilot_bcc_unitcell_pt_sweep_cae.py
  py -3 scripts/pilot_bcc_unitcell_pt_sweep_cae.py --target-area-pi --cae-mesh --mesh-locally
"""

from __future__ import annotations

import argparse
import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from src.export.cae_mesh_runner import run_cae_mesh
from src.export.ocp_bcc_unitcell_fuse import export_ocp_bcc_unitcell_step
from src.export.sw_parasolid import measure_step_occ_stats
from src.paths import CAD_ROOT, ensure_output_dirs


def main() -> int:
    ensure_output_dirs()
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--L", type=float, default=20.0)
    p.add_argument("--d-major", type=float, default=2.582)
    p.add_argument("--d-minor", type=float, default=1.549)
    p.add_argument(
        "--align",
        choices=("major", "minor"),
        default="major",
        help="Ellipse axis aligned to +Z compression (default major = ellmaj)",
    )
    p.add_argument("--target-area-pi", action="store_true")
    p.add_argument(
        "--out-step",
        default="",
        help="Output STEP path (default under output/cad/pilot/)",
    )
    p.add_argument("--cae-mesh", action="store_true", help="Run CAE tet mesh probe after export")
    p.add_argument("--cae-seed", type=float, default=0.6)
    p.add_argument("--mesh-locally", action="store_true")
    p.add_argument("--remote-host", default=os.environ.get("HU_BAI_REMOTE_HOST", ""))
    p.add_argument(
        "--remote-root",
        default=os.environ.get(
            "HU_BAI_REMOTE_ROOT",
            "/media/art/file/XiangLang/Lattice/LWY/HuBaiLab",
        ),
    )
    args = p.parse_args()

    import math

    d_major = float(args.d_major)
    d_minor = float(args.d_minor)
    if args.target_area_pi:
        target_a = math.pi
        aspect = 2.0 / 1.2
        d_minor = math.sqrt(4.0 * target_a / math.pi / aspect)
        d_major = aspect * d_minor

    minor_ratio = (0.5 * d_minor) / max(0.5 * d_major, 1e-12)
    tag = "ellmaj" if args.align == "major" else "ellmin"
    out_step = args.out_step.strip()
    if not out_step:
        out_dir = os.path.join(str(CAD_ROOT), "pilot")
        os.makedirs(out_dir, exist_ok=True)
        area_tag = "_Api" if args.target_area_pi else ""
        out_step = os.path.join(
            out_dir,
            f"hu_bai_bcc_unitcell_L{int(args.L)}_{tag}{area_tag}_pt_z.step",
        )
    out_step = os.path.abspath(out_step)
    os.makedirs(os.path.dirname(out_step) or ".", exist_ok=True)

    print(f"Export ellmaj/ellmin={tag} parallel-transport sweep -> {out_step}", flush=True)
    rep = export_ocp_bcc_unitcell_step(
        out_step,
        cell_size=float(args.L),
        rod_diameter=d_major,
        solid_profile="ellipse",
        ellipse_minor_ratio=minor_ratio,
        compression_axis=(0.0, 0.0, 1.0),
        ellipse_align_to_compression=str(args.align),
        ellipse_sweep_mode="parallel_transport",
    )
    stats = measure_step_occ_stats(out_step)
    rep["step_occ_stats"] = stats
    print("export:", json.dumps({k: rep[k] for k in rep if k != "mem_raw_topology"}, indent=2, default=str))

    if not args.cae_mesh:
        report_path = out_step.replace(".step", "_pilot_report.json")
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(rep, f, indent=2, default=str)
            f.write("\n")
        print(f"OK (no CAE probe): {out_step}")
        return 0

    mesh_inp = out_step.replace(".step", "_cae_mesh.inp")
    print(f"CAE mesh probe seed={args.cae_seed} mm -> {mesh_inp}", flush=True)
    loc = run_cae_mesh(
        _ROOT,
        out_step,
        mesh_inp,
        float(args.cae_seed),
        "LATTICE",
        mesh_on_server=not args.mesh_locally,
        remote_host=args.remote_host.strip(),
        remote_root=args.remote_root.strip(),
        mesh_mode="tet",
        mesh_quality="lattice_contact",
        rod_diameter_mm=d_major,
        rods_per_diameter=3.0,
        virtual_topology=False,
        element_type="C3D4",
    )
    rep["cae_mesh_location"] = loc
    rep["cae_mesh_inp"] = mesh_inp
    report_path = out_step.replace(".step", "_pilot_report.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(rep, f, indent=2, default=str)
        f.write("\n")
    print(f"CAE mesh OK ({loc}): {mesh_inp}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
