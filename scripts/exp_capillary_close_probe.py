"""
Capillary morphological close probe (Q=1 / Q=1.5 isolation).

Writes watertight STL + faceted STEP by default (smooth-looking CAD).

  py -3 scripts/exp_capillary_close_probe.py --force
  py -3 scripts/exp_capillary_close_probe.py --qs 1.0 1.5 --force
  py -3 scripts/exp_capillary_close_probe.py --no-step   # STL only
"""

from __future__ import annotations

import argparse
import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from src.export.exp_node_transition.bcc_explicit_cores import default_exp_out_dir
from src.export.exp_node_transition.capillary_close import (
    CapillaryCloseParams,
    default_r_cap_mm,
    export_capillary_close_unitcell,
)


def main() -> int:
    p = argparse.ArgumentParser(description="Capillary close isolated probe")
    p.add_argument("--force", action="store_true")
    p.add_argument("--qs", type=float, nargs="+", default=[1.0, 1.5])
    p.add_argument("--voxel", type=float, default=0.18)
    p.add_argument("--hub-r", type=float, default=5.0)
    p.add_argument(
        "--r-cap",
        type=float,
        default=None,
        help="Override capillary radius (mm); default from Q/rod",
    )
    p.add_argument(
        "--no-step",
        action="store_true",
        help="Skip faceted STEP (STL only)",
    )
    p.add_argument(
        "--with-step",
        action="store_true",
        help="Deprecated: STEP is default; kept for compatibility",
    )
    args = p.parse_args()

    out_dir = os.path.join(default_exp_out_dir(), "_capillary_close")
    os.makedirs(out_dir, exist_ok=True)
    print(f"out_dir={out_dir}", flush=True)

    rows: list[dict] = []
    for q in args.qs:
        r_cap = (
            float(args.r_cap)
            if args.r_cap is not None
            else default_r_cap_mm(2.0, float(q))
        )
        print(f"\n######## Q={q:g} R_cap={r_cap:g} ########", flush=True)
        params = CapillaryCloseParams(
            period_factor=float(q),
            voxel_mm=float(args.voxel),
            r_cap_mm=r_cap,
            hub_radius_mm=float(args.hub_r),
            write_faceted_step=not bool(args.no_step),
        )
        try:
            man = export_capillary_close_unitcell(
                params, out_dir=out_dir, force=bool(args.force)
            )
            vols = man.get("volumes_mm3") or {}
            gates = man.get("success_gates") or {}
            close = man.get("close") or {}
            row = {
                "Q": float(q),
                "r_cap_mm": r_cap,
                "watertight": gates.get("watertight"),
                "dvol_voxel_frac": vols.get("dvol_voxel_frac"),
                "dvol_frac_ok": gates.get("dvol_frac_ok"),
                "n_voxels_added": close.get("n_voxels_added"),
                "stl": man.get("stl_path"),
                "step": man.get("step_path"),
                "faceted_step_ok": man.get("faceted_step_ok"),
                "error": None,
            }
        except Exception as exc:
            row = {
                "Q": float(q),
                "r_cap_mm": r_cap,
                "watertight": False,
                "faceted_step_ok": False,
                "error": str(exc)[:400],
            }
            print(f"  FAIL Q={q:g}: {exc}", flush=True)
        rows.append(row)
        print(f"  row={row}", flush=True)

    summary_path = os.path.join(out_dir, "probe_summary.json")
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2)
    print(f"\nWrote {summary_path}", flush=True)

    wins = [
        r
        for r in rows
        if r.get("watertight")
        and r.get("error") is None
        and r.get("dvol_frac_ok")
        and (args.no_step or r.get("faceted_step_ok"))
    ]
    print(
        f"n_wins={len(wins)}/{len(rows)} "
        f"(watertight + |dV_voxel|<8%"
        f"{'' if args.no_step else ' + STEP'})",
        flush=True,
    )
    return 0 if len(wins) == len(rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
