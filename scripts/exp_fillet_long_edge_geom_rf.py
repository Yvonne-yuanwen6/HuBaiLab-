"""
Prefer longer/cleaner intersection edges, then geometry-based Rf MakeFillet.

  py -3 scripts/exp_fillet_long_edge_geom_rf.py
"""
from __future__ import annotations

import json
import math
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from OCP.BRepBuilderAPI import BRepBuilderAPI_Copy

from src.export.exp_node_transition.acute_slot_fillet import (
    SlotFilletParams,
    _as_single_solid,
    _bbox_span,
    _mid_key,
    _slot_z_group,
    _try_fillet_per_edge,
    _write_step_hard_solid,
    build_slots_for_params,
    default_rf_for_q,
    find_edges_for_slot,
)
from src.export.exp_node_transition.bcc_explicit_cores import default_exp_out_dir
from src.export.exp_node_transition.bcc_fillet_blend import (
    ExpFilletParams,
    fuse_pipes_unitcell_bare_ladder,
)
from src.export.ocp_unitcell_fuse import ocp_mass, ocp_shape_topology


def _loose_params(q: float) -> SlotFilletParams:
    p = SlotFilletParams(
        period_factor=float(q),
        r_blend_factor=float(default_rf_for_q(q)),
        amplitude_mm=2.0,
        rod_d_mm=2.0,
        cell_size_mm=20.0,
        n_segments=32,
        # Prefer longer edges: raise min, raise max
        min_edge_len_mm=0.50,
        max_edge_len_mm=8.0,
        r_band_min_mm=0.70,
        r_band_max_mm=5.5,
        max_ray_dist_mm=1.80,
        max_plane_dist_mm=1.80,
        normal_dot_max=0.92,
    )
    return p


def _geom_rf(open_deg: float, edge_len: float, R: float = 1.0) -> list[float]:
    th = math.radians(max(float(open_deg), 1e-3))
    r_sin = R * math.sin(0.5 * th)
    r_tan = R * math.tan(0.5 * th)
    r_e = 0.25 * float(edge_len)
    # Prefer mid-scale: not tiny adaptive, not >0.45R
    primary = min(0.45 * R, max(r_sin, r_e, 0.12 * R))
    cands = sorted(
        {
            round(x, 4)
            for x in (
                primary,
                min(0.35 * R, max(r_tan, r_e)),
                min(0.40 * R, 0.30 * edge_len),
                min(0.30 * R, max(r_sin * 1.5, 0.15)),
                0.20,
                0.25,
                0.30,
            )
            if 0.08 <= x <= 0.50
        }
    )
    return cands


def _rank_edges(cands: list[dict], *, prefer_near_centre: bool = True) -> list[dict]:
    """
    Prefer clean crotch edges: near cell centre (smaller r_mid), then longer.
    Absolute-longest edges far from origin often are wrong features (−Δm/bbox).
    """

    def key(d: dict) -> tuple:
        L = float(d["length_mm"])
        rm = float(d["r_mm"])
        ray = float(d["ray_dist"])
        plane = float(d["plane_dist"])
        if prefer_near_centre:
            # band bonus: r_mid in [1.0, 3.2] typical junction
            in_band = 1.0 if 1.0 <= rm <= 3.2 else 0.0
            return (-in_band, rm, -L, ray + plane)
        return (-L, ray + plane, rm)

    return sorted(cands, key=key)


def run_q(q: float, out_dir: str) -> dict:
    params = _loose_params(q)
    fp = ExpFilletParams(
        cell_size_mm=20.0,
        rod_d_mm=2.0,
        amplitude_mm=2.0,
        period_factor=float(q),
        n_segments=32,
    )
    print(f"\n######## LONG-EDGE Q={q:g} ########", flush=True)
    bare, m0, fuse_tag, _ = fuse_pipes_unitcell_bare_ladder(fp)
    span0 = _bbox_span(bare)
    max_span = 20.0 * 1.35
    slots = build_slots_for_params(params)

    inventory = []
    used_mids: set[tuple[float, float, float]] = set()
    selected: list[tuple] = []  # (slot, edge_info, open_deg)

    for slot in slots:
        g = _slot_z_group(slot)
        open_deg = min(float(slot.theta_deg), 180.0 - float(slot.theta_deg))
        raw = find_edges_for_slot(bare, slot, params)
        ranked = _rank_edges(raw)
        inventory.append(
            {
                "slot_id": slot.slot_id,
                "group": g,
                "theta": round(float(slot.theta_deg), 2),
                "open": round(open_deg, 2),
                "n_cands": len(ranked),
                "L_top3": [round(float(d["length_mm"]), 3) for d in ranked[:3]],
                "r_mid_top3": [round(float(d["r_mm"]), 3) for d in ranked[:3]],
            }
        )
        # Prefer bot/top; within slot take best near-centre then longest.
        # Also keep a "longest overall" alternate if distinct mid.
        pick = None
        pick_long = None
        ranked_long = _rank_edges(raw, prefer_near_centre=False)
        for d in ranked:
            key = _mid_key(d["mid"])
            if key in used_mids:
                continue
            if g == "cross" and float(d["length_mm"]) < 1.50:
                continue
            # near-centre primary
            if pick is None and 0.9 <= float(d["r_mm"]) <= 3.3:
                pick = d
            if pick_long is None:
                pick_long = d
        if pick is None:
            pick = pick_long
        if pick is None:
            print(
                f"  slot#{slot.slot_id:02d} {g:5s} open={open_deg:.1f}° "
                f"cands={len(ranked)} NO unique edge "
                f"Ltop={inventory[-1]['L_top3']}",
                flush=True,
            )
            continue
        used_mids.add(_mid_key(pick["mid"]))
        selected.append((slot, pick, open_deg))
        alt = ""
        if pick_long is not None and _mid_key(pick_long["mid"]) != _mid_key(pick["mid"]):
            alt = f" altLong L={pick_long['length_mm']:.3f}@r={pick_long['r_mm']:.2f}"
        print(
            f"  slot#{slot.slot_id:02d} {g:5s} open={open_deg:.1f}° "
            f"PICK L={pick['length_mm']:.3f} r_mid={pick['r_mm']:.2f} "
            f"ray={pick['ray_dist']:.2f} cands={len(ranked)} "
            f"Ltop={inventory[-1]['L_top3']}{alt}",
            flush=True,
        )

    # Sort selected by: prefer mid-length in band, then longer
    selected.sort(
        key=lambda t: (
            0 if 1.0 <= float(t[1]["r_mm"]) <= 2.8 else 1,
            -float(t[1]["length_mm"]),
        )
    )

    probes = []
    wins = []
    # Cap: top 5 slots × up to 3 near-centre edge cands × geom rf
    for slot, info0, open_deg in selected[:5]:
        ranked_nc = [
            d
            for d in _rank_edges(find_edges_for_slot(bare, slot, params))
            if 0.9 <= float(d["r_mm"]) <= 3.3
        ]
        if not ranked_nc:
            ranked_nc = [info0]
        edge_cands = ranked_nc[:3]
        print(
            f"\n  -- fillet slot#{slot.slot_id} open={open_deg:.1f}° "
            f"try {len(edge_cands)} near-centre edges "
            f"L={[round(float(d['length_mm']),3) for d in edge_cands]}",
            flush=True,
        )
        for ei, info in enumerate(edge_cands):
            L = float(info["length_mm"])
            rfs = _geom_rf(open_deg, L)
            # short edges: also try milder rf
            if L < 1.5:
                for extra in (0.08, 0.10, 0.12, 0.15, 0.18):
                    if extra not in rfs:
                        rfs.append(extra)
                rfs = sorted(set(round(x, 4) for x in rfs if 0.06 <= x <= 0.45))
            print(
                f"  cand#{ei} L={L:.3f} r_mid={info['r_mm']:.2f} rf={rfs}",
                flush=True,
            )
            for r in rfs:
                tag = (
                    f"long_q{str(q).replace('.', 'p')}_s{slot.slot_id}"
                    f"_c{ei}_L{str(round(L, 2)).replace('.', 'p')}"
                    f"_r{str(r).replace('.', 'p')}"
                )
                try:
                    src = BRepBuilderAPI_Copy(bare).Shape()
                    ranked2 = [
                        d
                        for d in _rank_edges(find_edges_for_slot(src, slot, params))
                        if 0.9 <= float(d["r_mm"]) <= 3.3
                    ]
                    if not ranked2:
                        ranked2 = _rank_edges(find_edges_for_slot(src, slot, params))
                    edge = None
                    target = _mid_key(info["mid"])
                    for d in ranked2:
                        if _mid_key(d["mid"]) == target:
                            edge = d["edge"]
                            L = float(d["length_mm"])
                            break
                    if edge is None and ei < len(ranked2):
                        edge = ranked2[ei]["edge"]
                        L = float(ranked2[ei]["length_mm"])
                    if edge is None:
                        print(f"    {tag} no edge on copy", flush=True)
                        continue
                    trial = _as_single_solid(
                        _try_fillet_per_edge(src, [(edge, float(r))])
                    )
                    m1 = float(ocp_mass(trial))
                    dm = m1 - float(m0)
                    sp = _bbox_span(trial)
                    topo = ocp_shape_topology(trial, check_brep=True)
                    row = {
                        "tag": tag,
                        "Q": q,
                        "slot_id": slot.slot_id,
                        "cand": ei,
                        "L": L,
                        "r_mid": float(info["r_mm"]),
                        "open": open_deg,
                        "r": r,
                        "mem_dm": dm,
                        "mem_valid": bool(topo.get("brep_valid")),
                    }
                    if dm < -0.5 or dm > 10.0:
                        print(f"    {tag} skip dm={dm:+.3f}", flush=True)
                        probes.append({**row, "hard_ok": False, "reason": "dm"})
                        continue
                    if max(sp) > max_span or any(
                        sp[k] > float(span0[k]) + 2.5 for k in range(3)
                    ):
                        print(f"    {tag} skip bbox", flush=True)
                        probes.append({**row, "hard_ok": False, "reason": "bbox"})
                        continue
                    if not bool(topo.get("brep_valid")):
                        print(f"    {tag} mem_dm={dm:+.3f} invalid_brep", flush=True)
                        probes.append({**row, "hard_ok": False, "reason": "invalid"})
                        continue
                    path = os.path.join(out_dir, f"{tag}.step")
                    try:
                        rb = _write_step_hard_solid(
                            trial,
                            path,
                            mass_ref=m1,
                            max_drift=1.0,
                            max_span_mm=max_span,
                        )
                        rbm = float(ocp_mass(rb))
                        rbt = ocp_shape_topology(rb, check_brep=True)
                        hard_ok = (
                            abs(rbm - m1) <= 1.0
                            and (rbm - float(m0)) > 0.05
                            and int(rbt.get("solids") or 0) == 1
                            and bool(rbt.get("brep_valid"))
                        )
                        print(
                            f"    {tag} mem_dm={dm:+.3f} valid HARD "
                            f"{'OK' if hard_ok else 'FAIL'} rb_dm={rbm - m0:+.3f}",
                            flush=True,
                        )
                        row.update(
                            {
                                "hard_ok": hard_ok,
                                "rb_dm": rbm - float(m0),
                                "rb_valid": bool(rbt.get("brep_valid")),
                                "path": path if hard_ok else None,
                            }
                        )
                        probes.append(row)
                        if hard_ok:
                            wins.append(row)
                    except Exception as exc:
                        print(
                            f"    {tag} mem_dm={dm:+.3f} valid hard FAIL {exc}",
                            flush=True,
                        )
                        probes.append({**row, "hard_ok": False, "error": str(exc)})
                except Exception as exc:
                    print(f"    {tag} ERR {exc}", flush=True)
                    probes.append(
                        {"tag": tag, "Q": q, "error": str(exc), "hard_ok": False}
                    )

    # Multi-edge oneshot on longest 2–4 edges that individually had +dm valid mem
    good_edges = [
        (s, i, o, r)
        for (s, i, o) in selected[:4]
        for r in _geom_rf(o, float(i["length_mm"]))[:2]
    ]
    # skip multi for now if no single wins — try anyway with geom primary r on 2 longest
    if len(selected) >= 2:
        s0, i0, o0 = selected[0]
        s1, i1, o1 = selected[1]
        r0 = _geom_rf(o0, float(i0["length_mm"]))[0]
        r1 = _geom_rf(o1, float(i1["length_mm"]))[0]
        tag = f"long_q{str(q).replace('.', 'p')}_pair_s{s0.slot_id}_{s1.slot_id}"
        print(f"\n  -- oneshot 2 longest r=({r0},{r1}) --", flush=True)
        try:
            src = BRepBuilderAPI_Copy(bare).Shape()
            e0 = _rank_edges(find_edges_for_slot(src, s0, params))[0]["edge"]
            e1 = _rank_edges(find_edges_for_slot(src, s1, params))[0]["edge"]
            trial = _as_single_solid(
                _try_fillet_per_edge(src, [(e0, float(r0)), (e1, float(r1))])
            )
            m1 = float(ocp_mass(trial))
            dm = m1 - float(m0)
            topo = ocp_shape_topology(trial, check_brep=True)
            print(
                f"    {tag} mem_dm={dm:+.3f} valid={topo.get('brep_valid')}",
                flush=True,
            )
            if bool(topo.get("brep_valid")) and 0.05 < dm < 12.0:
                path = os.path.join(out_dir, f"{tag}.step")
                rb = _write_step_hard_solid(
                    trial, path, mass_ref=m1, max_drift=1.0, max_span_mm=max_span
                )
                rbm = float(ocp_mass(rb))
                rbt = ocp_shape_topology(rb, check_brep=True)
                hard_ok = (
                    (rbm - float(m0)) > 0.05
                    and bool(rbt.get("brep_valid"))
                    and int(rbt.get("solids") or 0) == 1
                )
                print(f"    hard={'OK' if hard_ok else 'FAIL'} rb_dm={rbm-m0:+.3f}", flush=True)
                row = {
                    "tag": tag,
                    "Q": q,
                    "r": [r0, r1],
                    "mem_dm": dm,
                    "mem_valid": True,
                    "hard_ok": hard_ok,
                    "rb_dm": rbm - float(m0),
                    "path": path if hard_ok else None,
                }
                probes.append(row)
                if hard_ok:
                    wins.append(row)
        except Exception as exc:
            print(f"    {tag} FAIL {exc}", flush=True)

    return {
        "Q": q,
        "fuse": fuse_tag,
        "mass_bare": float(m0),
        "inventory": inventory,
        "n_selected": len(selected),
        "L_selected": [round(float(i["length_mm"]), 3) for _, i, _ in selected],
        "probes": probes,
        "wins": wins,
    }


def main() -> int:
    out = os.path.join(default_exp_out_dir(), "_fillet_long_edge")
    os.makedirs(out, exist_ok=True)
    reports = []
    all_wins = []
    for q in (1.0, 1.5):
        rep = run_q(q, out)
        reports.append(rep)
        all_wins.extend(rep["wins"])
        print(
            f"\nQ={q:g} selected_L={rep['L_selected']} wins={len(rep['wins'])}",
            flush=True,
        )

    man = os.path.join(out, "long_edge_geom_rf_report.json")
    with open(man, "w", encoding="utf-8") as f:
        json.dump({"reports": reports, "wins": all_wins}, f, indent=2)

    # Promote best win per Q to exp_ name
    for q in (1.0, 1.5):
        qw = [w for w in all_wins if abs(float(w["Q"]) - q) < 1e-9 and w.get("path")]
        if not qw:
            continue
        qw.sort(key=lambda w: -float(w.get("rb_dm") or w.get("mem_dm") or 0))
        best = qw[0]
        dest = os.path.join(
            default_exp_out_dir(),
            f"exp_longEdgeFillet_af2q{str(q).replace('.', 'p')}_L20_d2p0_1x1.step",
        )
        import shutil

        shutil.copy2(best["path"], dest)
        print(f"PROMOTED Q={q} → {dest} (from {best['tag']})", flush=True)

    print(f"\nmanifest: {man}", flush=True)
    print(f"total_wins={len(all_wins)}", flush=True)
    return 0 if all_wins else 1


if __name__ == "__main__":
    raise SystemExit(main())
