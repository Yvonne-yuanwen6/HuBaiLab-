"""
Slot-batch MakeFillet for Q in {0, 0.5, 1.0, 1.5} (L=20, d=2, Af=2).

  py -3 scripts/exp_slot_fillet_four_configs.py --force
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
    export_slot_fillet,
)
from src.export.exp_node_transition.bcc_explicit_cores import default_exp_out_dir


def main() -> int:
    p = argparse.ArgumentParser(description="Slot fillet four Q configs")
    p.add_argument("--force", action="store_true")
    p.add_argument(
        "--qs",
        type=float,
        nargs="+",
        default=[0.0, 0.5, 1.0, 1.5],
    )
    args = p.parse_args()

    out_dir = default_exp_out_dir()
    rows: list[dict] = []
    for q in args.qs:
        rf = default_rf_for_q(float(q))
        print(f"\n######## Q={q:g} rf={rf:g} ########", flush=True)
        params = SlotFilletParams(
            period_factor=float(q),
            r_blend_factor=float(rf),
        )
        man = export_slot_fillet(params, force=bool(args.force))
        fil = man.get("fillet") or {}
        row = {
            "Q": float(q),
            "rf": float(rf),
            "mode": fil.get("mode"),
            "n_slots": fil.get("n_slots") or fil.get("n_edges"),
            "n_filled": fil.get("n_slots_filled") or fil.get("n_edges"),
            "coverage": fil.get("coverage"),
            "r_used_mm": fil.get("r_used_mm") or fil.get("r_used"),
            "chamfer_fallback": man.get("used_chamfer_fallback"),
            "fallback": man.get("used_bare_fallback"),
            "brep_valid": (man.get("topology") or {}).get("brep_valid"),
            "mass_mm3": man.get("mass_mm3"),
            "span": man.get("span"),
            "step_write": man.get("step_write"),
            "step": man.get("step_path"),
            "error": fil.get("error") or fil.get("step_error"),
        }
        rows.append(row)
        print(
            f"  → cov={row['n_filled']}/{row['n_slots']} "
            f"r={row['r_used_mm']} fallback={row['fallback']} "
            f"valid={row['brep_valid']}",
            flush=True,
        )

    summary_path = os.path.join(out_dir, "exp_slotFillet_four_summary.json")
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2)

    print("\n=== SUMMARY ===", flush=True)
    for r in rows:
        print(
            f"  Q={r['Q']:g}  {r['n_filled']}/{r['n_slots']}  "
            f"r_used={r['r_used_mm']}  fallback={r['fallback']}  "
            f"valid={r['brep_valid']}  mass={r['mass_mm3']}",
            flush=True,
        )
    print(f"summary → {summary_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
