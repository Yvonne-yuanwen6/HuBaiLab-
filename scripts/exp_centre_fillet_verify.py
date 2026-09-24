"""
Centre junction smooth STEP via OCC MakeFillet (true BRep, not mesh).

  py -3 scripts/exp_centre_fillet_verify.py --force
  py -3 scripts/exp_centre_fillet_verify.py --force --rf 0.20

Outputs under output/cad/_exp_node_transition/ only.
"""

from __future__ import annotations

import argparse
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from src.export.exp_node_transition.centre_edge_fillet import (
    CentreFilletParams,
    export_centre_fillet_unitcell,
)


def main() -> int:
    p = argparse.ArgumentParser(description="EXP centre MakeFillet → smooth STEP")
    p.add_argument("--Q", type=float, default=1.5)
    p.add_argument("--Af", type=float, default=2.0)
    p.add_argument("--rod-d", type=float, default=2.0)
    p.add_argument("--L", type=float, default=20.0)
    p.add_argument("--n-segments", type=int, default=32)
    p.add_argument("--select-r", type=float, default=4.0)
    p.add_argument("--rf", type=float, default=0.12, help="fillet Rf / strut R")
    p.add_argument("--band-rmin", type=float, default=1.8)
    p.add_argument("--band-rmax", type=float, default=3.8)
    p.add_argument("--all-edges", action="store_true", help="ignore concave filter")
    p.add_argument("--force", action="store_true")
    p.add_argument("--out-dir", default="")
    args = p.parse_args()

    params = CentreFilletParams(
        cell_size_mm=float(args.L),
        rod_d_mm=float(args.rod_d),
        amplitude_mm=float(args.Af),
        period_factor=float(args.Q),
        n_segments=int(args.n_segments),
        select_radius_mm=float(args.select_r),
        r_blend_factor=float(args.rf),
        band_rmin_mm=float(args.band_rmin),
        band_rmax_mm=float(args.band_rmax),
        concave_only=False if args.all_edges else False,
    )
    man = export_centre_fillet_unitcell(
        params,
        out_dir=args.out_dir or None,
        force=bool(args.force),
    )
    print(
        "ok step=",
        man.get("step_path"),
        "fallback=",
        man.get("used_bare_fallback"),
        "fillet=",
        man.get("fillet"),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
