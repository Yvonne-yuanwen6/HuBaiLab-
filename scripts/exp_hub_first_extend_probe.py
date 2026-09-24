"""
Hub-first → extend unitcell probe (experiment isolation).

Builds smooth hub kernel (stubs + canals) then outer arms for Q=1 / Q=1.5.
Does NOT promote into formal hard CAD delivery.

  py -3 scripts/exp_hub_first_extend_probe.py
  py -3 scripts/exp_hub_first_extend_probe.py --qs 1.0 1.5 --s-hub 4.0 --rf 0.40
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
from src.export.exp_node_transition.hard_cad_delivery import delivery_out_dir
from src.export.exp_node_transition.hub_first_extend import (
    HubFirstParams,
    export_hub_first_extend,
)
from src.export.ocp_paper_box_array_fuse import ocp_read_step_shape
from src.export.ocp_unitcell_fuse import ocp_mass, ocp_shape_topology


def _delivery_refs() -> dict[float, str]:
    root = delivery_out_dir()
    return {
        1.0: os.path.join(
            root, "exp_hardSwFillet_af2q1p0_L20_d2p0_r0p15_n12_1x1.step"
        ),
        1.5: os.path.join(
            root, "exp_hardSwFillet_af2q1p5_L20_d2p0_r0p15_n11_1x1.step"
        ),
    }


def _stat_step(path: str) -> dict:
    if not os.path.isfile(path) or os.path.getsize(path) < 500:
        return {"path": path, "exists": False}
    try:
        shape = ocp_read_step_shape(path)
        topo = ocp_shape_topology(shape, check_brep=True)
        return {
            "path": os.path.abspath(path),
            "exists": True,
            "solids": topo.get("solids"),
            "faces": topo.get("faces"),
            "brep_valid": topo.get("brep_valid"),
            "mass_mm3": float(ocp_mass(shape)),
            "bytes": os.path.getsize(path),
        }
    except Exception as exc:
        return {"path": os.path.abspath(path), "exists": True, "error": str(exc)[:300]}


def main() -> int:
    p = argparse.ArgumentParser(description="Hub-first extend probe Q=1/1.5")
    p.add_argument("--qs", type=float, nargs="+", default=[1.0, 1.5])
    p.add_argument("--s-hub", type=float, default=4.0)
    p.add_argument("--overlap", type=float, default=1.2)
    p.add_argument("--rf", type=float, default=0.40, help="r_blend / strut R")
    p.add_argument("--nseg", type=int, default=32)
    p.add_argument(
        "--seed-sphere",
        type=float,
        default=3.5,
        help="Connectivity sphere R/R_strut (0=off); canals still do crotch fill",
    )
    p.add_argument("--no-step", action="store_true")
    args = p.parse_args()

    out_dir = os.path.join(
        default_exp_out_dir(), "_hard_cad_delivery", "_hub_first_extend"
    )
    os.makedirs(out_dir, exist_ok=True)
    refs = _delivery_refs()

    rows: list[dict] = []
    for q in args.qs:
        params = HubFirstParams(
            period_factor=float(q),
            s_hub_mm=float(args.s_hub),
            arm_overlap_mm=float(args.overlap),
            r_blend_factor=float(args.rf),
            n_segments=int(args.nseg),
            seed_sphere_factor=float(args.seed_sphere),
        )
        row: dict = {"Q": float(q), "ok": False}
        try:
            rep = export_hub_first_extend(
                params,
                out_dir=out_dir,
                write_step=not bool(args.no_step),
            )
            row.update(
                {
                    "ok": True,
                    "slug": rep.get("slug"),
                    "mass_mm3": rep.get("merged_mass_mm3"),
                    "topology": rep.get("topology"),
                    "n_canals_applied": rep.get("hub", {}).get("n_canals_applied"),
                    "n_canals_planned": rep.get("hub", {}).get("n_canals_planned"),
                    "step_path": rep.get("step_path"),
                    "step_solid_ok": rep.get("step_solid_ok"),
                    "step_route": rep.get("step_route"),
                    "manifest_path": rep.get("manifest_path"),
                }
            )
            if rep.get("step_path"):
                row["step_stat"] = _stat_step(str(rep["step_path"]))
        except Exception as exc:
            row["error"] = str(exc)[:500]
            print(f"FAIL Q={q}: {exc}", flush=True)

        ref = refs.get(float(q)) or refs.get(round(float(q), 1))
        if ref is None and abs(float(q) - 1.0) < 1e-9:
            ref = refs[1.0]
        if ref is None and abs(float(q) - 1.5) < 1e-9:
            ref = refs[1.5]
        if ref:
            row["delivery_ref"] = _stat_step(ref)
        rows.append(row)

    summary = {
        "experiment": "hub_first_extend_probe",
        "out_dir": os.path.abspath(out_dir),
        "n_ok": sum(1 for r in rows if r.get("ok")),
        "n_total": len(rows),
        "params": {
            "s_hub_mm": float(args.s_hub),
            "arm_overlap_mm": float(args.overlap),
            "r_blend_factor": float(args.rf),
            "n_segments": int(args.nseg),
            "seed_sphere_factor": float(args.seed_sphere),
        },
        "rows": rows,
        "note": (
            "Compare STEP visually to delivery n12/n11. "
            "Do not promote until crotch looks clearly cleaner."
        ),
    }
    summary_path = os.path.join(out_dir, "hub_first_summary.json")
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, default=str)
    print(f"\nWrote {summary_path}", flush=True)
    print(f"n_ok={summary['n_ok']}/{summary['n_total']}", flush=True)
    for r in rows:
        if r.get("ok"):
            print(
                f"  Q={r['Q']} mass={r.get('mass_mm3'):.2f} "
                f"canals={r.get('n_canals_applied')}/{r.get('n_canals_planned')} "
                f"step_ok={r.get('step_solid_ok')} "
                f"→ {r.get('step_path')}",
                flush=True,
            )
            dr = r.get("delivery_ref") or {}
            if dr.get("exists"):
                print(
                    f"    vs delivery: faces={dr.get('faces')} "
                    f"mass={dr.get('mass_mm3'):.2f}",
                    flush=True,
                )
        else:
            print(f"  Q={r['Q']} FAIL: {r.get('error')}", flush=True)
    return 0 if summary["n_ok"] == summary["n_total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
