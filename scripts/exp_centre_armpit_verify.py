"""
Equal-R struts + pairwise adaptive crotch canals (experiment) → hard STEP.

  py -3 scripts/exp_centre_armpit_verify.py --force
  py -3 scripts/exp_centre_armpit_verify.py --force --Q 1.5

Default: adaptive Rf from pair angle (no --rf). Outputs under
output/cad/_exp_node_transition/ only. Does not touch batch defaults.
"""

from __future__ import annotations

import argparse
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from src.export.exp_node_transition.centre_armpit_blend import (
    CentreArmpitParams,
    export_centre_armpit_unitcell,
)


def main() -> int:
    p = argparse.ArgumentParser(description="EXP pair-canal equal-R → hard STEP")
    p.add_argument("--Q", type=float, default=1.5)
    p.add_argument("--Af", type=float, default=2.0)
    p.add_argument("--rod-d", type=float, default=2.0)
    p.add_argument("--L", type=float, default=20.0)
    p.add_argument("--n-segments", type=int, default=32)
    p.add_argument("--s-start", type=float, default=1.20)
    p.add_argument("--s-end", type=float, default=3.20)
    p.add_argument("--max-pairs", type=int, default=8)
    p.add_argument(
        "--rf",
        type=float,
        default=None,
        help="optional global canal radius mm; default = per-pair adaptive",
    )
    p.add_argument("--force", action="store_true")
    p.add_argument("--out-dir", default="")
    args = p.parse_args()

    params = CentreArmpitParams(
        cell_size_mm=float(args.L),
        rod_d_mm=float(args.rod_d),
        amplitude_mm=float(args.Af),
        period_factor=float(args.Q),
        n_segments=int(args.n_segments),
        s_start_mm=float(args.s_start),
        s_end_mm=float(args.s_end),
        max_pairs=int(args.max_pairs),
        r_blend_mm=(None if args.rf is None else float(args.rf)),
        tool="canal",
    )
    man = export_centre_armpit_unitcell(
        params,
        out_dir=args.out_dir or None,
        force=bool(args.force),
        write_stl=False,
    )
    print(
        "ok",
        "applied=",
        man.get("blend", {}).get("n_applied"),
        "dmass=",
        man.get("mass_delta_vs_bare_mm3"),
        "step=",
        man.get("step_path"),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
