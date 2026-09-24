"""
Intersection-edge MakeFillet (strut–strut meeting curves → smooth STEP).

  py -3 scripts/exp_intersection_fillet_verify.py --force --Q 0
  py -3 scripts/exp_intersection_fillet_four_configs.py

Outputs under output/cad/_exp_node_transition/ only.
"""

from __future__ import annotations

import argparse
import os
import sys
import traceback

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from src.export.exp_node_transition.intersection_edge_fillet import (
    IntersectionFilletParams,
    _default_rf_for_q,
    export_intersection_fillet_unitcell,
)


def _export_one(q: float, *, rf: float | None, force: bool) -> dict:
    r_blend = float(rf) if rf is not None else _default_rf_for_q(q)
    params = IntersectionFilletParams(
        cell_size_mm=20.0,
        rod_d_mm=2.0,
        amplitude_mm=2.0,
        period_factor=float(q),
        n_segments=32,
        r_blend_factor=r_blend,
        # Q>0: keep away from origin spine a bit via select_r still includes armpits
        select_radius_mm=5.0 if abs(q) > 1e-12 else 4.5,
        max_edges_apply=8 if abs(q) < 1e-12 else 6,
    )
    return export_intersection_fillet_unitcell(params, force=force)


def main() -> int:
    p = argparse.ArgumentParser(description="EXP intersection-edge MakeFillet")
    p.add_argument("--Q", type=float, default=None, help="single Q; omit for all four")
    p.add_argument("--rf", type=float, default=None, help="override Rf/R")
    p.add_argument("--force", action="store_true")
    p.add_argument("--all-four", action="store_true", help="Q in {0,0.5,1,1.5}")
    args = p.parse_args()

    qs: list[float]
    if args.all_four or args.Q is None:
        qs = [0.0, 0.5, 1.0, 1.5]
    else:
        qs = [float(args.Q)]

    rows: list[dict] = []
    for q in qs:
        print(f"\n######## intersection fillet Q={q:g} ########", flush=True)
        try:
            man = _export_one(q, rf=args.rf, force=bool(args.force))
            fil = man.get("fillet") or {}
            rows.append(
                {
                    "Q": q,
                    "ok": True,
                    "fallback": man.get("used_bare_fallback"),
                    "n_applied": fil.get("n_applied"),
                    "mass": man.get("mass_mm3"),
                    "valid": (man.get("topology") or {}).get("brep_valid"),
                    "step": man.get("step_path"),
                    "write": man.get("step_write"),
                }
            )
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            rows.append({"Q": q, "ok": False, "error": str(exc)})

    print("\n======== INTERSECTION FILLET SUMMARY ========", flush=True)
    for r in rows:
        if r.get("ok"):
            print(
                f"  Q={r['Q']:g}  OK  fallback={r['fallback']}  "
                f"n_fillet={r['n_applied']}  mass={float(r['mass']):.2f}  "
                f"valid={r['valid']}  write={r['write']}",
                flush=True,
            )
            print(f"       {r['step']}", flush=True)
        else:
            print(f"  Q={r['Q']:g}  FAIL  {r.get('error')}", flush=True)
    n_ok = sum(1 for r in rows if r.get("ok") and not r.get("fallback"))
    n_any = sum(1 for r in rows if r.get("ok"))
    print(f"filleted_ok {n_ok}/{len(rows)}  (step_written {n_any}/{len(rows)})", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
