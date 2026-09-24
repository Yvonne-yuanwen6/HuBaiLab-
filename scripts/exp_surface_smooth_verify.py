"""
Direct surface smooth of fused unitcell (no Boolean add-ons). V2 anti-tear.

  py -3 scripts/exp_surface_smooth_verify.py --force
  py -3 scripts/exp_surface_smooth_verify.py --force --smooth-r 3.5 --iters 8

Outputs under output/cad/_exp_node_transition/ only.
Open the *V2* .stl (one SW window). Do not open old surfSmooth (v1).
"""

from __future__ import annotations

import argparse
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from src.export.exp_node_transition.surface_smooth import (
    SurfaceSmoothParams,
    export_surface_smooth_unitcell,
)


def main() -> int:
    p = argparse.ArgumentParser(description="EXP surface smooth V2 (anti-tear)")
    p.add_argument("--Q", type=float, default=1.5)
    p.add_argument("--Af", type=float, default=2.0)
    p.add_argument("--rod-d", type=float, default=2.0)
    p.add_argument("--L", type=float, default=20.0)
    p.add_argument("--n-segments", type=int, default=32)
    p.add_argument("--smooth-r", type=float, default=3.5)
    p.add_argument("--falloff", type=float, default=4.0)
    p.add_argument("--iters", type=int, default=8)
    p.add_argument("--mesh-deflection", type=float, default=0.08)
    p.add_argument("--with-step", action="store_true", help="also try faceted STEP")
    p.add_argument("--force", action="store_true")
    p.add_argument("--out-dir", default="")
    args = p.parse_args()

    params = SurfaceSmoothParams(
        cell_size_mm=float(args.L),
        rod_d_mm=float(args.rod_d),
        amplitude_mm=float(args.Af),
        period_factor=float(args.Q),
        n_segments=int(args.n_segments),
        mesh_deflection_mm=float(args.mesh_deflection),
        smooth_radius_mm=float(args.smooth_r),
        falloff_mm=float(args.falloff),
        iterations=int(args.iters),
        write_faceted_step=bool(args.with_step),
    )
    man = export_surface_smooth_unitcell(
        params,
        out_dir=args.out_dir or None,
        force=bool(args.force),
    )
    print(
        "ok stl=",
        man.get("stl_path"),
        "watertight=",
        (man.get("mesh") or {}).get("watertight"),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
