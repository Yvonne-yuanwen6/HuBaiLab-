"""
Experimental scheme A: centre fillet on 1×1, then 2×2×1 fuse, then shared-corner fillet.

  py -3 scripts/exp_bcc_fillet_blend_2x2x1.py
  py -3 scripts/exp_bcc_fillet_blend_2x2x1.py --r-blend-factor 0.5 --force
  py -3 scripts/exp_bcc_fillet_blend_2x2x1.py --unitcell-only

Unit-cell corners are NOT filleted (avoids array clover/convex tips).
Shared corners are filleted only after array boolean fuse.

Outputs: output/cad/_exp_node_transition/
Main-path batch recipes are untouched. Q=0 only for this smoke.
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
from src.export.exp_node_transition.bcc_fillet_blend import (
    ExpFilletParams,
    export_exp_bcc_fillet_unitcell,
    export_exp_fillet_array_then_shared_corners,
)


def _slug(params: ExpFilletParams) -> str:
    q = params.period_factor
    q_tag = str(q).replace(".", "p")
    if abs(q - round(q)) < 1e-9:
        q_tag = str(int(round(q)))
    d_tag = str(params.rod_d_mm).replace(".", "p")
    rb = str(params.r_blend_factor).replace(".", "p")
    return (
        f"exp_filletA_af{int(round(params.amplitude_mm))}q{q_tag}"
        f"_L{int(round(params.cell_size_mm))}_d{d_tag}_rb{rb}"
    )


def main() -> int:
    p = argparse.ArgumentParser(
        description="EXP scheme-A: centre fillet → fuse → shared-corner fillet"
    )
    p.add_argument("--L", type=float, default=20.0)
    p.add_argument("--rod-d", type=float, default=2.0)
    p.add_argument("--Af", type=float, default=2.0)
    p.add_argument("--Q", type=float, default=0.0, help="Smoke supports Q=0 only")
    p.add_argument("--n-segments", type=int, default=24)
    p.add_argument("--r-blend-factor", type=float, default=0.50)
    p.add_argument("--edge-select-factor", type=float, default=2.8)
    p.add_argument(
        "--fillet-unitcell-corners",
        action="store_true",
        help="Also fillet corners on 1x1 (NOT recommended; causes array clover)",
    )
    p.add_argument("--no-centre", action="store_true")
    p.add_argument(
        "--skip-array-corner-fillet",
        action="store_true",
        help="Only fuse 2x2x1; do not fillet shared corners",
    )
    p.add_argument("--unitcell-only", action="store_true")
    p.add_argument("--force", action="store_true")
    p.add_argument("--out-dir", default="")
    args = p.parse_args()

    if abs(float(args.Q)) > 1e-12:
        print(
            "ERROR: scheme-A fillet smoke is Q=0 only for now. Use --Q 0.",
            flush=True,
        )
        return 2

    out_dir = args.out_dir or default_exp_out_dir()
    os.makedirs(out_dir, exist_ok=True)
    params = ExpFilletParams(
        cell_size_mm=float(args.L),
        rod_d_mm=float(args.rod_d),
        amplitude_mm=float(args.Af),
        period_factor=float(args.Q),
        n_segments=int(args.n_segments),
        r_blend_factor=float(args.r_blend_factor),
        edge_select_factor=float(args.edge_select_factor),
        fillet_centre=not args.no_centre,
        fillet_corners=bool(args.fillet_unitcell_corners),
        array_fillet_shared_corners=not args.skip_array_corner_fillet,
        r_blend_fallback_factors=(
            float(args.r_blend_factor),
            0.45,
            0.35,
            0.25,
            0.15,
        ),
    )

    slug = _slug(params)
    step_1x1 = os.path.join(out_dir, f"{slug}_1x1_centreFillet.step")
    summary: dict = {
        "scheme": "A_fuse_then_shared_corner_fillet",
        "out_dir": out_dir,
        "params": params.__dict__,
        "main_path_untouched": True,
        "runs": {},
    }

    if args.force or not os.path.isfile(step_1x1):
        summary["runs"]["fillet_1x1"] = export_exp_bcc_fillet_unitcell(step_1x1, params)
    else:
        print(f"  [skip] exists: {step_1x1}", flush=True)
        summary["runs"]["fillet_1x1"] = {"step_path": step_1x1, "skipped": True}

    if not args.unitcell_only:
        step_arr = os.path.join(out_dir, f"{slug}_2x2x1_sharedCornerFillet.step")
        summary["runs"]["fillet_2x2x1"] = export_exp_fillet_array_then_shared_corners(
            summary["runs"]["fillet_1x1"]["step_path"],
            step_arr,
            params,
            force=args.force,
        )

    man = os.path.join(out_dir, "exp_filletA_run_summary.json")
    with open(man, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, default=str)
    print(f"\n=== EXP fillet-A summary → {man} ===", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
