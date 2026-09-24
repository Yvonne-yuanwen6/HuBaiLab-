"""
Promote SolidWorks sequential fillet probe wins into hard CAD delivery.

  py -3 scripts/exp_promote_sw_fillet.py
"""

from __future__ import annotations

import argparse
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from src.export.exp_node_transition.hard_cad_delivery import (
    promote_sw_fillet_probe_summary,
)


def main() -> int:
    p = argparse.ArgumentParser(description="Promote SW fillet probe → delivery")
    p.add_argument(
        "--probe-summary",
        default=None,
        help="Path to sw_fillet_probe_summary.json",
    )
    args = p.parse_args()
    summary = promote_sw_fillet_probe_summary(
        probe_summary_path=args.probe_summary,
    )
    return 0 if summary.get("n_ok") == summary.get("n_total") else 1


if __name__ == "__main__":
    raise SystemExit(main())
