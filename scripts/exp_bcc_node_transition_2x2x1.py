"""
Experimental BCC node transition (explicit centre/corner cores) — isolated path.

Does NOT modify batch defaults or paper_box main recipes.

  py -3 scripts/exp_bcc_node_transition_2x2x1.py
  py -3 scripts/exp_bcc_node_transition_2x2x1.py --rod-d 2.0 --force
  py -3 scripts/exp_bcc_node_transition_2x2x1.py --baseline-only
  py -3 scripts/exp_bcc_node_transition_2x2x1.py --exp-only

Outputs under: output/cad/_exp_node_transition/
"""

from __future__ import annotations

import argparse
import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from src.export.exp_node_transition.bcc_explicit_cores import (
    ExpNodeTransitionParams,
    default_exp_out_dir,
    export_exp_bcc_baseline_unitcell,
    export_exp_bcc_unitcell_explicit_cores,
    export_exp_bcc_zslab_2x2x1,
)


def _slug(params: ExpNodeTransitionParams, kind: str) -> str:
    q = params.period_factor
    q_tag = str(q).replace(".", "p")
    if abs(q - round(q)) < 1e-9:
        q_tag = str(int(round(q)))
    d = params.rod_d_mm
    d_tag = str(d).replace(".", "p")
    return (
        f"exp_{kind}_af{int(round(params.amplitude_mm))}q{q_tag}"
        f"_L{int(round(params.cell_size_mm))}_d{d_tag}"
    )


def main() -> int:
    p = argparse.ArgumentParser(
        description="EXP: BCC explicit node cores + 2x2x1 array (isolated)"
    )
    p.add_argument("--L", type=float, default=20.0)
    p.add_argument("--rod-d", type=float, default=2.0)
    p.add_argument("--Af", type=float, default=2.0)
    p.add_argument("--Q", type=float, default=0.0, help="Prefer 0 for first smoke")
    p.add_argument("--n-segments", type=int, default=24)
    p.add_argument("--r-centre-factor", type=float, default=1.25)
    p.add_argument("--r-corner-factor", type=float, default=1.10)
    p.add_argument(
        "--l-shrink-centre",
        type=float,
        default=None,
        help="mm; default auto 0.55*R_core_centre",
    )
    p.add_argument(
        "--l-shrink-corner",
        type=float,
        default=None,
        help="mm; default auto 0.55*R_core_corner",
    )
    p.add_argument("--no-centre-core", action="store_true")
    p.add_argument("--no-corner-cores", action="store_true")
    p.add_argument("--baseline-only", action="store_true")
    p.add_argument("--exp-only", action="store_true")
    p.add_argument("--unitcell-only", action="store_true")
    p.add_argument("--force", action="store_true")
    p.add_argument("--out-dir", default="")
    args = p.parse_args()

    out_dir = args.out_dir or default_exp_out_dir()
    os.makedirs(out_dir, exist_ok=True)

    params = ExpNodeTransitionParams(
        cell_size_mm=float(args.L),
        rod_d_mm=float(args.rod_d),
        amplitude_mm=float(args.Af),
        period_factor=float(args.Q),
        n_segments=int(args.n_segments),
        r_core_centre_factor=float(args.r_centre_factor),
        r_core_corner_factor=float(args.r_corner_factor),
        l_shrink_centre_mm=args.l_shrink_centre,
        l_shrink_corner_mm=args.l_shrink_corner,
        enable_centre_core=not args.no_centre_core,
        enable_corner_cores=not args.no_corner_cores,
    )

    summary: dict = {
        "out_dir": out_dir,
        "params": params.__dict__,
        "main_path_untouched": True,
        "array": [2, 2, 1],
        "runs": {},
    }

    do_baseline = not args.exp_only
    do_exp = not args.baseline_only

    if do_baseline:
        b_slug = _slug(params, "baseline")
        b_step = os.path.join(out_dir, f"{b_slug}_1x1.step")
        if args.force or not os.path.isfile(b_step):
            summary["runs"]["baseline_1x1"] = export_exp_bcc_baseline_unitcell(b_step, params)
        else:
            print(f"  [skip] baseline 1x1 exists: {b_step}", flush=True)
            summary["runs"]["baseline_1x1"] = {"step_path": b_step, "skipped": True}
        if not args.unitcell_only:
            b_arr = os.path.join(out_dir, f"{b_slug}_2x2x1.step")
            summary["runs"]["baseline_2x2x1"] = export_exp_bcc_zslab_2x2x1(
                summary["runs"]["baseline_1x1"]["step_path"],
                b_arr,
                cell_size_mm=params.cell_size_mm,
                force=args.force,
            )

    if do_exp:
        e_slug = _slug(params, "cores")
        sc_tag = (
            "auto"
            if params.l_shrink_centre_mm is None
            else str(params.l_shrink_centre_mm).replace(".", "p")
        )
        sk_tag = (
            "auto"
            if params.l_shrink_corner_mm is None
            else str(params.l_shrink_corner_mm).replace(".", "p")
        )
        e_slug += (
            f"_rc{str(params.r_core_centre_factor).replace('.', 'p')}"
            f"_rk{str(params.r_core_corner_factor).replace('.', 'p')}"
            f"_sc{sc_tag}_sk{sk_tag}"
        )
        e_step = os.path.join(out_dir, f"{e_slug}_1x1.step")
        if args.force or not os.path.isfile(e_step):
            # Q≥1 uses hub-fuse builder; Q=0 uses shrink+cores L3 builder.
            summary["runs"]["exp_1x1"] = export_exp_bcc_unitcell_explicit_cores(
                e_step, params
            )
        else:
            print(f"  [skip] exp 1x1 exists: {e_step}", flush=True)
            summary["runs"]["exp_1x1"] = {"step_path": e_step, "skipped": True}
        if not args.unitcell_only:
            e_arr = os.path.join(out_dir, f"{e_slug}_2x2x1.step")
            summary["runs"]["exp_2x2x1"] = export_exp_bcc_zslab_2x2x1(
                summary["runs"]["exp_1x1"]["step_path"],
                e_arr,
                cell_size_mm=params.cell_size_mm,
                force=args.force,
            )

    summary_path = os.path.join(out_dir, "exp_run_summary.json")
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, default=str)
    print(f"\n=== EXP summary → {summary_path} ===", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
