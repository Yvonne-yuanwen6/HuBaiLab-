"""Promote best plane-chain SW fillet wins into hard CAD delivery."""

from __future__ import annotations

import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from src.export.exp_node_transition.hard_cad_delivery import (
    CAD_GATE,
    delivery_out_dir,
    promote_sw_fillet_win,
)


def main() -> int:
    out = delivery_out_dir()
    probe = os.path.join(out, "_sw_plane_chain_fillet")
    rows = [
        {
            "Q": 1.0,
            "ok": True,
            "step_path": os.path.join(
                probe,
                "exp_planeChain_af2q1p0_L20_d2p0_1x1_swFillet_r0p15_n12.step",
            ),
            "xt_path": os.path.join(
                probe,
                "exp_planeChain_af2q1p0_L20_d2p0_1x1_swFillet_r0p15_n12.x_t",
            ),
            "radius_mm": 0.15,
            "n_edges_filleted": 12,
            "n_edges_attempted": 16,
            "n_hub_candidates": 36,
            "step_in": os.path.join(
                out, "_plane_chain_heal", "exp_planeChain_af2q1p0_L20_d2p0_1x1.step"
            ),
        },
        {
            "Q": 1.5,
            "ok": True,
            "step_path": os.path.join(
                probe,
                "exp_planeChain_af2q1p5_L20_d2p0_1x1_swFillet_r0p15_n11.step",
            ),
            "xt_path": os.path.join(
                probe,
                "exp_planeChain_af2q1p5_L20_d2p0_1x1_swFillet_r0p15_n11.x_t",
            ),
            "radius_mm": 0.15,
            "n_edges_filleted": 11,
            "n_edges_attempted": 32,
            "n_hub_candidates": 47,
            "step_in": os.path.join(
                out, "_plane_chain_heal", "exp_planeChain_af2q1p5_L20_d2p0_1x1.step"
            ),
        },
    ]
    comb = os.path.join(probe, "sw_plane_chain_best_summary.json")
    with open(comb, "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2)
    print(f"wrote {comb}", flush=True)

    promoted = []
    for row in rows:
        if not os.path.isfile(row["step_path"]):
            raise FileNotFoundError(row["step_path"])
        if not os.path.isfile(row["xt_path"]):
            raise FileNotFoundError(row["xt_path"])
        man = promote_sw_fillet_win(probe_row=row, out_dir=out)
        man["fillet"] = "sw_fillet"
        man["fillet_detail"]["mode"] = "sw_plane_chain_fillet"
        man["fillet_detail"]["note"] = (
            "Hub edges clustered on AcuteSlot bot/top/cross planes, "
            "chained by endpoint gap, then SolidWorks FeatureFillet3 "
            "(whole-chain then sequential). Hard STEP+x_t."
        )
        man_path = os.path.join(out, f"{man['slug']}_manifest.json")
        with open(man_path, "w", encoding="utf-8") as f:
            json.dump(man, f, indent=2)
        promoted.append(man)
        print(
            f"promoted {man['slug']} mass={man['mass_mm3']:.2f} "
            f"valid={man['topology'].get('brep_valid')}",
            flush=True,
        )

    sum_path = os.path.join(out, "delivery_summary.json")
    with open(sum_path, encoding="utf-8") as f:
        prev = json.load(f)
    by_q = {float(r["Q"]): r for r in prev.get("rows") or []}
    for man in promoted:
        q = float(man["period_factor"])
        by_q[q] = {
            "Q": q,
            "fillet": "sw_fillet",
            "cad_format": man.get("cad_format"),
            "step_path": man.get("step_path"),
            "xt_path": man.get("xt_path"),
            "mass_mm3": man.get("mass_mm3"),
            "brep_valid": (man.get("topology") or {}).get("brep_valid"),
            "fillet_detail": man.get("fillet_detail"),
            "ok": True,
            "error": None,
        }
    ordered = [by_q[q] for q in sorted(by_q)]
    summary = {
        "experiment": "hard_cad_delivery",
        "cad_gate": CAD_GATE,
        "out_dir": os.path.abspath(out),
        "rows": ordered,
        "n_ok": sum(1 for r in ordered if r.get("ok")),
        "n_total": len(ordered),
        "sw_fillet_promoted": len(promoted),
        "plane_chain": True,
    }
    with open(sum_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    print(f"summary n_ok={summary['n_ok']}/{summary['n_total']}", flush=True)
    for r in ordered:
        fd = r.get("fillet_detail") or {}
        print(
            f"  Q={r['Q']} fillet={r.get('fillet')} mode={fd.get('mode')} "
            f"n={fd.get('n_edges_filleted')} valid={r.get('brep_valid')}",
            flush=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
