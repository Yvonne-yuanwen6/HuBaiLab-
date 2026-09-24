"""
Pre-compute slot angles / edge sizes / geometric Rf candidates for Q grid,
then probe MakeFillet at those radii (esp. larger than prior tiny sweeps).

  py -3 scripts/exp_fillet_geom_radius_plan.py
"""
from __future__ import annotations

import json
import math
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import numpy as np
from OCP.BRepBuilderAPI import BRepBuilderAPI_Copy

from src.export.exp_node_transition.acute_slot_fillet import (
    SlotFilletParams,
    _as_single_solid,
    _assign_edge_for_slot,
    _bbox_span,
    _mid_key,
    _slot_z_group,
    _try_fillet_per_edge,
    _write_step_hard_solid,
    adaptive_slot_radius_mm,
    build_slots_for_params,
    default_rf_for_q,
)
from src.export.exp_node_transition.bcc_explicit_cores import default_exp_out_dir
from src.export.exp_node_transition.bcc_fillet_blend import (
    ExpFilletParams,
    fuse_pipes_unitcell_bare_ladder,
)
from src.export.ocp_unitcell_fuse import ocp_mass, ocp_shape_topology


def _geom_radii_mm(*, R: float, theta_deg: float, edge_len: float) -> dict[str, float]:
    """
    Geometry-informed Rf candidates (mm).

    open = min(θ, 180-θ) is the crotch opening.
    Prior adaptive *shrinks* for acute; user asked to consider larger based on size.
    """
    open_deg = min(float(theta_deg), 180.0 - float(theta_deg))
    th = math.radians(max(open_deg, 1e-3))
    # Classic angle-limited bounds (order-of-magnitude)
    r_sin = float(R) * math.sin(0.5 * th)
    r_tan = float(R) * math.tan(0.5 * th)
    # Edge-length fractions (fillet surface spans along the intersection)
    r_e25 = 0.25 * float(edge_len)
    r_e40 = 0.40 * float(edge_len)
    r_e50 = 0.50 * float(edge_len)
    # Absolute caps vs strut
    r_025R = 0.25 * float(R)
    r_35R = 0.35 * float(R)
    r_50R = 0.50 * float(R)
    # Proposed probe set: prefer larger of angle/edge clues, still ≤ 0.5R
    proposed = sorted(
        {
            round(x, 4)
            for x in (
                r_sin,
                r_tan,
                r_e25,
                r_e40,
                r_025R,
                r_35R,
                min(r_e50, r_50R),
                min(max(r_tan, r_e25), r_50R),
                min(max(r_sin * 2.0, r_e25), r_50R),
            )
            if 0.02 <= x <= 0.55 * float(R) + 1e-9
        }
    )
    return {
        "open_deg": open_deg,
        "r_sin_half": r_sin,
        "r_tan_half": r_tan,
        "r_edge_0p25": r_e25,
        "r_edge_0p40": r_e40,
        "r_0p25R": r_025R,
        "r_0p35R": r_35R,
        "r_0p50R": r_50R,
        "proposed": proposed,
    }


def plan_q(q: float) -> dict:
    R = 1.0  # rod_d=2
    rf_factor = default_rf_for_q(q)
    params = SlotFilletParams(
        period_factor=float(q),
        r_blend_factor=float(rf_factor),
        amplitude_mm=2.0,
        rod_d_mm=2.0,
        cell_size_mm=20.0,
        n_segments=32,
    )
    fp = ExpFilletParams(
        cell_size_mm=20.0,
        rod_d_mm=2.0,
        amplitude_mm=2.0,
        period_factor=float(q),
        n_segments=32,
    )
    print(f"\n######## PLAN Q={q:g} rf_factor={rf_factor} ########", flush=True)
    bare, m0, fuse_tag, _ = fuse_pipes_unitcell_bare_ladder(fp)
    span0 = _bbox_span(bare)
    slots = build_slots_for_params(params)
    used: set = set()
    rows = []
    for slot in slots:
        info = _assign_edge_for_slot(
            bare,
            slot,
            params,
            used_mids=used,
            max_edge_len_mm=None if abs(q) < 1.2 else 3.5,
        )
        if info is None:
            rows.append(
                {
                    "slot_id": slot.slot_id,
                    "pair": [slot.i, slot.j],
                    "group": _slot_z_group(slot),
                    "theta_deg": slot.theta_deg,
                    "assigned": False,
                    "r_adaptive": adaptive_slot_radius_mm(slot, params),
                }
            )
            continue
        used.add(_mid_key(info["mid"]))
        elen = float(info["length_mm"])
        geom = _geom_radii_mm(R=R, theta_deg=slot.theta_deg, edge_len=elen)
        r_ad = adaptive_slot_radius_mm(slot, params)
        rows.append(
            {
                "slot_id": slot.slot_id,
                "pair": [slot.i, slot.j],
                "group": _slot_z_group(slot),
                "theta_deg": round(float(slot.theta_deg), 2),
                "open_deg": round(float(geom["open_deg"]), 2),
                "edge_len_mm": round(elen, 3),
                "assigned": True,
                "r_adaptive": round(r_ad, 4),
                "geom": {k: (round(v, 4) if isinstance(v, float) else v) for k, v in geom.items()},
            }
        )
        print(
            f"  slot#{slot.slot_id:02d} {_slot_z_group(slot):5s} "
            f"θ={slot.theta_deg:6.1f}° open={geom['open_deg']:5.1f}° "
            f"L={elen:5.2f}  r_adapt={r_ad:.3f}  "
            f"r_sin={geom['r_sin_half']:.3f} r_tan={geom['r_tan_half']:.3f} "
            f"r_e25={geom['r_edge_0p25']:.3f}  propose={geom['proposed']}",
            flush=True,
        )

    assigned = [r for r in rows if r.get("assigned")]
    summary = {
        "Q": q,
        "R_strut_mm": R,
        "r_blend_factor": rf_factor,
        "fuse": fuse_tag,
        "mass_bare": float(m0),
        "span0": list(span0),
        "n_slots": len(slots),
        "n_assigned": len(assigned),
        "theta_min": min((r["theta_deg"] for r in assigned), default=None),
        "theta_max": max((r["theta_deg"] for r in assigned), default=None),
        "open_min": min((r["open_deg"] for r in assigned), default=None),
        "L_min": min((r["edge_len_mm"] for r in assigned), default=None),
        "L_max": max((r["edge_len_mm"] for r in assigned), default=None),
        "r_adapt_min": min((r["r_adaptive"] for r in assigned), default=None),
        "r_adapt_max": max((r["r_adaptive"] for r in assigned), default=None),
        "slots": rows,
    }
    return summary, bare, m0, span0, params, assigned


def probe_geom_radii(q: float, bare, m0, span0, params, assigned, out_dir: str) -> list[dict]:
    """Try single-edge MakeFillet at geometry-proposed radii (incl. larger)."""
    if abs(q) < 0.9:
        return []
    results = []
    max_span = 20.0 * 1.35
    # Prefer bot/top; take up to 4 longest edges (more room for larger Rf)
    cand = [r for r in assigned if r["group"] in ("bot", "top")]
    cand.sort(key=lambda r: -float(r["edge_len_mm"]))
    cand = cand[:4]
    print(f"\n-- PROBE MakeFillet Q={q:g} on {len(cand)} edges x geom radii --", flush=True)

    # Rebuild slot objects for assign
    slots_by_id = {s.slot_id: s for s in build_slots_for_params(params)}

    for row in cand:
        slot = slots_by_id[row["slot_id"]]
        proposed = list(row["geom"]["proposed"])
        # Ensure we also try explicitly larger set vs old tiny sweep
        for extra in (0.10, 0.12, 0.15, 0.18, 0.20, 0.25, 0.30, 0.35):
            if extra not in proposed and extra <= 0.55:
                proposed.append(extra)
        proposed = sorted(set(round(x, 4) for x in proposed))
        print(
            f"  edge slot#{row['slot_id']} L={row['edge_len_mm']} "
            f"open={row['open_deg']}° try r={proposed}",
            flush=True,
        )
        for r in proposed:
            tag = (
                f"geom_q{str(q).replace('.', 'p')}_s{row['slot_id']}"
                f"_r{str(r).replace('.', 'p')}"
            )
            try:
                src = BRepBuilderAPI_Copy(bare).Shape()
                info = _assign_edge_for_slot(
                    src, slot, params, used_mids=set(), max_edge_len_mm=3.5
                )
                if info is None:
                    print(f"    {tag} no edge", flush=True)
                    continue
                trial = _as_single_solid(_try_fillet_per_edge(src, [(info["edge"], float(r))]))
                m1 = float(ocp_mass(trial))
                dm = m1 - float(m0)
                sp = _bbox_span(trial)
                topo = ocp_shape_topology(trial, check_brep=True)
                if dm < -0.5 or dm > 12.0:
                    print(f"    {tag} skip dm={dm:+.3f}", flush=True)
                    continue
                if max(sp) > max_span or any(sp[k] > span0[k] + 2.5 for k in range(3)):
                    print(f"    {tag} skip bbox {tuple(round(x,2) for x in sp)}", flush=True)
                    continue
                path = os.path.join(out_dir, f"{tag}.step")
                try:
                    rb = _write_step_hard_solid(
                        trial, path, mass_ref=m1, max_drift=1.0, max_span_mm=max_span
                    )
                    rbm = float(ocp_mass(rb))
                    rbt = ocp_shape_topology(rb, check_brep=True)
                    hard_ok = (
                        abs(rbm - m1) <= 1.0
                        and int(rbt.get("solids") or 0) == 1
                        and bool(rbt.get("brep_valid"))
                    )
                    print(
                        f"    {tag} mem_dm={dm:+.3f} valid={topo.get('brep_valid')} "
                        f"hard={'OK' if hard_ok else 'FAIL'} rb_dm={rbm-m0:+.3f} "
                        f"rb_valid={rbt.get('brep_valid')}",
                        flush=True,
                    )
                    results.append(
                        {
                            "tag": tag,
                            "Q": q,
                            "slot_id": row["slot_id"],
                            "r": r,
                            "mem_dm": dm,
                            "mem_valid": bool(topo.get("brep_valid")),
                            "hard_ok": hard_ok,
                            "rb_dm": rbm - float(m0),
                            "rb_valid": bool(rbt.get("brep_valid")),
                            "path": path if hard_ok else None,
                        }
                    )
                except Exception as exc:
                    print(
                        f"    {tag} mem_dm={dm:+.3f} valid={topo.get('brep_valid')} "
                        f"hard FAIL {exc}",
                        flush=True,
                    )
                    results.append(
                        {
                            "tag": tag,
                            "Q": q,
                            "slot_id": row["slot_id"],
                            "r": r,
                            "mem_dm": dm,
                            "mem_valid": bool(topo.get("brep_valid")),
                            "hard_ok": False,
                            "error": str(exc),
                        }
                    )
            except Exception as exc:
                print(f"    {tag} ERR {exc}", flush=True)
    return results


def main() -> int:
    out = os.path.join(default_exp_out_dir(), "_fillet_geom_plan")
    os.makedirs(out, exist_ok=True)
    all_plans = []
    all_probe = []
    for q in (0.0, 0.5, 1.0, 1.5):
        plan, bare, m0, span0, params, assigned = plan_q(q)
        all_plans.append(plan)
        if abs(q) >= 0.9:
            all_probe.extend(
                probe_geom_radii(q, bare, m0, span0, params, assigned, out)
            )

    man_path = os.path.join(out, "geom_radius_plan.json")
    with open(man_path, "w", encoding="utf-8") as f:
        json.dump({"plans": all_plans, "probes": all_probe}, f, indent=2)

    print("\n======== SUMMARY ========", flush=True)
    for p in all_plans:
        print(
            f"  Q={p['Q']:g} assigned={p['n_assigned']}/{p['n_slots']} "
            f"open=[{p['open_min']},{p['open_max']}] "
            f"L=[{p['L_min']},{p['L_max']}] "
            f"r_adapt=[{p['r_adapt_min']},{p['r_adapt_max']}] "
            f"rf_factor={p['r_blend_factor']}",
            flush=True,
        )
    wins = [r for r in all_probe if r.get("hard_ok") and r.get("mem_valid") and r.get("rb_dm", 0) > 0.05]
    soft = [r for r in all_probe if r.get("hard_ok")]
    print(f"\nprobe hard_ok={len(soft)}  strict(+dm,valid)={len(wins)}", flush=True)
    for w in wins[:20]:
        print(f"  WIN {w}", flush=True)
    print(f"manifest: {man_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
