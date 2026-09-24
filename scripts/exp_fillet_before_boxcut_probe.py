"""
Isolated probe: large-overlap octant → MakeFillet → hard STEP.

Raw extended-pipe fuse collapses for Q>=1; this tests less-aggressive hub trim.

  py -3 scripts/exp_fillet_before_boxcut_probe.py --qs 1.0 1.5 --force
"""

from __future__ import annotations

import argparse
import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from src.export.exp_node_transition.acute_slot_fillet import (
    SlotFilletParams,
    default_rf_for_q,
)
from src.export.exp_node_transition.bcc_explicit_cores import default_exp_out_dir
from src.export.exp_node_transition.fillet_before_boxcut import export_fillet_before_boxcut


def main() -> int:
    p = argparse.ArgumentParser(description="Large-overlap octant fillet probe")
    p.add_argument("--force", action="store_true")
    p.add_argument("--qs", type=float, nargs="+", default=[1.0, 1.5])
    p.add_argument(
        "--no-baseline",
        action="store_true",
        help="Skip ov=0.02 baseline edge-length compare",
    )
    args = p.parse_args()

    out_dir = os.path.join(default_exp_out_dir(), "_fillet_pre_boxcut")
    os.makedirs(out_dir, exist_ok=True)
    print(f"out_dir={out_dir}", flush=True)

    rows: list[dict] = []
    for q in args.qs:
        rf = default_rf_for_q(float(q))
        print(f"\n######## Q={q:g} rf={rf:g} ########", flush=True)
        params = SlotFilletParams(period_factor=float(q), r_blend_factor=float(rf))
        try:
            man = export_fillet_before_boxcut(
                params,
                out_dir=out_dir,
                force=bool(args.force),
                compare_baseline_ov=None if args.no_baseline else 0.02,
            )
            masses = man.get("masses_mm3") or {}
            edges = man.get("edge_lengths_mm") or {}
            row = {
                "Q": float(q),
                "center_overlap_mm": man.get("center_overlap_mm"),
                "hard_step_ok": man.get("hard_step_ok"),
                "mass_final": masses.get("filleted"),
                "dm_fillet": masses.get("dm_fillet_vs_fused"),
                "edge_base_max": (edges.get("baseline_min_mean_max") or {}).get("max"),
                "edge_ov_max": (edges.get("large_overlap_min_mean_max") or {}).get(
                    "max"
                ),
                "edge_base_mean": (edges.get("baseline_min_mean_max") or {}).get(
                    "mean"
                ),
                "edge_ov_mean": (edges.get("large_overlap_min_mean_max") or {}).get(
                    "mean"
                ),
                "fillet_mode": (man.get("fillet") or {}).get("mode"),
                "brep_valid": (man.get("filleted_topology") or {}).get("brep_valid"),
                "step_brep_valid": (man.get("step_readback") or {}).get("brep_valid"),
                "error": man.get("hard_step_error"),
            }
        except Exception as exc:
            row = {"Q": float(q), "hard_step_ok": False, "error": str(exc)[:400]}
            print(f"  FAIL Q={q:g}: {exc}", flush=True)
        rows.append(row)
        print(f"  row={row}", flush=True)

    summary_path = os.path.join(out_dir, "probe_summary.json")
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2)
    print(f"\nWrote {summary_path}", flush=True)

    wins = [r for r in rows if r.get("hard_step_ok")]
    print(f"n_hard_wins={len(wins)}/{len(rows)}", flush=True)
    return 0 if wins else 1


if __name__ == "__main__":
    raise SystemExit(main())
