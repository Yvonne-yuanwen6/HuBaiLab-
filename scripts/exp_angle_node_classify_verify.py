"""
Read-only angle detection + node classification (experiment).

  py -3 scripts/exp_angle_node_classify_verify.py
  py -3 scripts/exp_angle_node_classify_verify.py --Q 0
  py -3 scripts/exp_angle_node_classify_verify.py --Q 1.5 --no-markers

Outputs under output/cad/_exp_node_transition/ only.
Does NOT modify lattice geometry or batch recipes.
"""

from __future__ import annotations

import argparse
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from src.export.exp_node_transition.angle_node_classify import (
    AngleClassifyParams,
    export_angle_classify_case,
)


def main() -> int:
    p = argparse.ArgumentParser(description="EXP angle + node classify (read-only)")
    p.add_argument("--Q", type=float, default=1.5)
    p.add_argument("--Af", type=float, default=2.0)
    p.add_argument("--rod-d", type=float, default=2.0)
    p.add_argument("--L", type=float, default=20.0)
    p.add_argument("--n-segments", type=int, default=32)
    p.add_argument("--sample-s", type=float, default=3.5, help="cluster sample s (mm)")
    p.add_argument("--no-markers", action="store_true")
    p.add_argument("--out-dir", default="")
    args = p.parse_args()

    params = AngleClassifyParams(
        cell_size_mm=float(args.L),
        rod_d_mm=float(args.rod_d),
        amplitude_mm=float(args.Af),
        period_factor=float(args.Q),
        n_segments=int(args.n_segments),
        cluster_sample_s_mm=float(args.sample_s),
    )
    rep = export_angle_classify_case(
        params,
        out_dir=args.out_dir or None,
        write_markers=not bool(args.no_markers),
    )
    print("summary:", rep.summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
