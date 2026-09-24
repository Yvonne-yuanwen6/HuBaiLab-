"""
Adaptive scheme-A fillet (experiment only). Default: Q=1.5 bare-centre verify.

  py -3 scripts/exp_adaptive_fillet_verify.py --unitcell-only --force
  py -3 scripts/exp_adaptive_fillet_verify.py --Q 1.5 --fillet-clusters --unitcell-only --force
  py -3 scripts/exp_adaptive_fillet_verify.py --Q 0 --force

Outputs under output/cad/_exp_node_transition/ only.
Does NOT touch batch main-path recipes.
"""

from __future__ import annotations

import argparse
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from src.export.exp_node_transition.adaptive_fillet import AdaptiveFilletConfig
from src.export.exp_node_transition.adaptive_pipeline import export_adaptive_fillet_case


def main() -> int:
    p = argparse.ArgumentParser(description="EXP adaptive fillet verify (isolated)")
    p.add_argument("--Q", type=float, default=1.5)
    p.add_argument("--Af", type=float, default=2.0)
    p.add_argument("--rod-d", type=float, default=2.0)
    p.add_argument("--L", type=float, default=20.0)
    p.add_argument("--n-segments", type=int, default=32)
    p.add_argument("--k-blend", type=float, default=0.50)
    p.add_argument(
        "--hub-factor",
        type=float,
        default=0.0,
        help="Q>0 hub fallback R/R_strut (0=bare pipe only)",
    )
    p.add_argument(
        "--fillet-clusters",
        action="store_true",
        help="Q>0: enable small fillets on ±Z clusters only (not spine)",
    )
    p.add_argument(
        "--unitcell-only",
        action="store_true",
        help="Skip 2x2x1 array stage (recommended while reviewing Q=1.5 centre)",
    )
    p.add_argument("--force", action="store_true")
    p.add_argument("--out-dir", default="")
    args = p.parse_args()

    cfg = AdaptiveFilletConfig(
        k_blend=float(args.k_blend),
        q_gt0_hub_factor=float(args.hub_factor),
        fillet_q_gt0_interior=bool(args.fillet_clusters),
        fillet_q_gt0_clusters_only=True,
    )
    out_dir = args.out_dir or None
    export_adaptive_fillet_case(
        period_factor=float(args.Q),
        amplitude_mm=float(args.Af),
        rod_d_mm=float(args.rod_d),
        cell_size_mm=float(args.L),
        n_segments=int(args.n_segments),
        cfg=cfg,
        out_dir=out_dir,
        force=bool(args.force),
        unitcell_only=bool(args.unitcell_only),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
