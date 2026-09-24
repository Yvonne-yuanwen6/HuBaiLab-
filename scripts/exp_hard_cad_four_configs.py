"""
Hard CAD four-config delivery (STEP / x_t only).

  py -3 scripts/exp_hard_cad_four_configs.py --force
  py -3 scripts/exp_hard_cad_four_configs.py --force --no-xt
"""

from __future__ import annotations

import argparse
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from src.export.exp_node_transition.hard_cad_delivery import export_four_hard_cad


def main() -> int:
    p = argparse.ArgumentParser(description="Hard CAD four-config delivery")
    p.add_argument("--force", action="store_true")
    p.add_argument("--no-xt", action="store_true", help="Skip SolidWorks x_t convert")
    p.add_argument(
        "--qs",
        type=float,
        nargs="+",
        default=[0.0, 0.5, 1.0, 1.5],
    )
    args = p.parse_args()

    summary = export_four_hard_cad(
        qs=tuple(float(q) for q in args.qs),
        force=bool(args.force),
        try_xt=not bool(args.no_xt),
    )
    return 0 if summary.get("n_ok") == summary.get("n_total") else 1


if __name__ == "__main__":
    raise SystemExit(main())
