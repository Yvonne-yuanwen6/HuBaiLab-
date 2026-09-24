"""
Plane-chain hub edge diagnose / heal probe.

  py -3 scripts/exp_plane_chain_heal_probe.py --diagnose-only --qs 1.0 1.5
  py -3 scripts/exp_plane_chain_heal_probe.py --heal --qs 1.0 1.5 --force
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
from src.export.exp_node_transition.plane_chain_edge_heal import (
    PlaneChainParams,
    default_plane_chain_out_dir,
    export_plane_chain_for_q,
)


def _bare_step_for_q(delivery: str, q: float) -> str | None:
    step_map = {
        1.0: os.path.join(delivery, "exp_hardBare_af2q1p0_L20_d2p0_1x1.step"),
        1.5: os.path.join(delivery, "exp_hardBare_af2q1p5_L20_d2p0_1x1.step"),
    }
    key = min(step_map.keys(), key=lambda k: abs(k - float(q)))
    if abs(key - float(q)) > 0.05:
        return None
    path = step_map[key]
    return path if os.path.isfile(path) else None


def main() -> int:
    p = argparse.ArgumentParser(description="Plane-chain hub edge diagnose/heal")
    p.add_argument("--qs", type=float, nargs="+", default=[1.0, 1.5])
    p.add_argument("--diagnose-only", action="store_true")
    p.add_argument("--heal", action="store_true")
    p.add_argument("--force", action="store_true")
    p.add_argument("--hub-r", type=float, default=4.0)
    p.add_argument("--max-edge-len", type=float, default=2.5)
    p.add_argument("--gap-tol", type=float, default=0.10)
    p.add_argument("--max-plane-dist", type=float, default=1.25)
    args = p.parse_args()

    if not args.diagnose_only and not args.heal:
        args.diagnose_only = True

    delivery = os.path.join(default_exp_out_dir(), "_hard_cad_delivery")
    out_dir = default_plane_chain_out_dir()
    rows: list[dict] = []

    for q in args.qs:
        qf = float(q)
        step_in = _bare_step_for_q(delivery, qf)
        print(f"\n######## planeChain Q={qf:g} ########", flush=True)
        if not step_in:
            rows.append({"Q": qf, "ok": False, "error": "missing bare STEP"})
            print("  missing bare STEP", flush=True)
            continue
        params = PlaneChainParams(
            period_factor=qf,
            hub_r_mm=float(args.hub_r),
            max_edge_len_mm=float(args.max_edge_len),
            gap_tol_mm=float(args.gap_tol),
            max_plane_dist_mm=float(args.max_plane_dist),
        )
        try:
            man = export_plane_chain_for_q(
                period_factor=qf,
                step_in=step_in,
                out_dir=out_dir,
                diagnose_only=bool(args.diagnose_only) and not bool(args.heal),
                force=bool(args.force),
                params=params,
            )
            rows.append({"Q": qf, "ok": True, **{k: man.get(k) for k in (
                "slug",
                "diagnose_path",
                "step_path",
                "mass_mm3",
                "diagnose",
                "heal",
            ) if k in man}})
        except Exception as exc:
            rows.append({"Q": qf, "ok": False, "error": str(exc)[:500]})
            print(f"  FAIL: {exc}", flush=True)

    summary_path = os.path.join(out_dir, "plane_chain_summary.json")
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2)
    print(f"\nWrote {summary_path}", flush=True)
    n_ok = sum(1 for r in rows if r.get("ok"))
    print(f"n_ok={n_ok}/{len(rows)}", flush=True)
    return 0 if n_ok == len(rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
