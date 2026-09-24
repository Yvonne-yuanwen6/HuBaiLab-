"""
Centre-taper smooth STEP (build-time BRep, Q=1.5).

  py -3 scripts/exp_centre_taper_verify.py --force
  py -3 scripts/exp_centre_taper_verify.py --force --taper-scale 1.35 --taper-mm 3.5

Outputs under output/cad/_exp_node_transition/ only.
"""

from __future__ import annotations

import argparse
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from src.export.exp_node_transition.centre_taper_pipe import (
    CentreTaperParams,
    export_centre_taper_unitcell,
)


def main() -> int:
    p = argparse.ArgumentParser(description="EXP centre taper pipe → smooth STEP")
    p.add_argument("--Q", type=float, default=1.5)
    p.add_argument("--Af", type=float, default=2.0)
    p.add_argument("--rod-d", type=float, default=2.0)
    p.add_argument("--L", type=float, default=20.0)
    p.add_argument("--n-segments", type=int, default=32)
    p.add_argument("--taper-mm", type=float, default=3.5)
    p.add_argument("--taper-scale", type=float, default=1.45)
    p.add_argument("--force", action="store_true")
    p.add_argument("--out-dir", default="")
    args = p.parse_args()

    params = CentreTaperParams(
        cell_size_mm=float(args.L),
        rod_d_mm=float(args.rod_d),
        amplitude_mm=float(args.Af),
        period_factor=float(args.Q),
        n_segments=int(args.n_segments),
        taper_mm=float(args.taper_mm),
        taper_scale=float(args.taper_scale),
    )
    man = export_centre_taper_unitcell(
        params,
        out_dir=args.out_dir or None,
        force=bool(args.force),
    )
    print(
        "ok step=",
        man.get("step_path"),
        "mass=",
        (man.get("step_readback") or {}).get("mass_mm3"),
        "valid=",
        ((man.get("step_readback") or {}).get("topology") or {}).get("brep_valid"),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
