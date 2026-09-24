"""
Scheme B canal verify: spine–strut armpit blends for Q=1.5 (no MakeFillet).

  py -3 scripts/exp_scheme_b_q15_verify.py --force
  py -3 scripts/exp_scheme_b_q15_verify.py --force --mode spine_strut --r-blend 0.45

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

from src.export.exp_node_transition.bcc_scheme_b_blend import (
    SchemeBParams,
    export_scheme_b_unitcell,
)


def main() -> int:
    p = argparse.ArgumentParser(description="EXP scheme-B canal Q15")
    p.add_argument("--Q", type=float, default=1.5)
    p.add_argument("--Af", type=float, default=2.0)
    p.add_argument("--rod-d", type=float, default=2.0)
    p.add_argument("--L", type=float, default=20.0)
    p.add_argument("--n-segments", type=int, default=32)
    p.add_argument(
        "--r-blend",
        type=float,
        default=0.35,
        help="fillet Rf / strut R (rolling-ball canal radius)",
    )
    p.add_argument(
        "--mode",
        choices=("spine_strut", "adjacent"),
        default="spine_strut",
        help="spine_strut=Z-spine/strut armpit; adjacent=legacy ring valleys",
    )
    p.add_argument(
        "--side",
        choices=("outer", "inner"),
        default="outer",
        help="only for --mode adjacent",
    )
    p.add_argument("--s-start", type=float, default=3.20)
    p.add_argument("--s-end", type=float, default=4.80)
    p.add_argument(
        "--both-armpits",
        action="store_true",
        help="place both ±tangential armpits per strut (default: one side only)",
    )
    p.add_argument(
        "--seed",
        default="",
        help="optional bareCentre STEP; else rebuild bare ladder",
    )
    p.add_argument("--force", action="store_true")
    p.add_argument("--out-dir", default="")
    args = p.parse_args()

    params = SchemeBParams(
        cell_size_mm=float(args.L),
        rod_d_mm=float(args.rod_d),
        amplitude_mm=float(args.Af),
        period_factor=float(args.Q),
        n_segments=int(args.n_segments),
        r_blend_factor=float(args.r_blend),
        mode=str(args.mode),
        side=str(args.side),
        s_start_mm=float(args.s_start),
        s_end_mm=float(args.s_end),
        both_armpits=bool(args.both_armpits),
    )
    seed = args.seed.strip() or None
    if seed is None:
        cand = os.path.join(
            _ROOT,
            "output",
            "cad",
            "_exp_node_transition",
            "exp_adaptA_af2q1p5_L20_d2p0_k0p5_noHub_bareCentre_1x1_clean.step",
        )
        if os.path.isfile(cand):
            seed = cand

    rep = export_scheme_b_unitcell(
        params,
        out_dir=args.out_dir or None,
        force=bool(args.force),
        seed_step=seed,
    )
    print(json_summary(rep))
    return 0


def json_summary(rep: dict) -> str:
    import json

    slim = {
        "step_path": rep.get("step_path"),
        "stl_path": rep.get("stl_path"),
        "mass_mm3": rep.get("mass_mm3"),
        "n_applied": (rep.get("blend") or {}).get("n_applied"),
        "n_planned": (rep.get("blend") or {}).get("n_planned"),
        "n_skipped": (rep.get("blend") or {}).get("n_skipped"),
        "topology": rep.get("topology"),
        "skipped": rep.get("skipped"),
    }
    return json.dumps(slim, indent=2, default=str)


if __name__ == "__main__":
    raise SystemExit(main())
