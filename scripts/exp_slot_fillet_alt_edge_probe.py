"""
Q=1.5: try alternate edges (no max_elen, multi-cand, intersection) for valid MakeFillet.

  py -3 scripts/exp_slot_fillet_alt_edge_probe.py
"""

from __future__ import annotations

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from src.export.exp_node_transition.acute_slot_fillet import (
    SlotFilletParams,
    _as_single_solid,
    _bbox_span,
    _mid_key,
    _slot_z_group,
    _try_fillet_per_edge,
    adaptive_slot_radius_mm,
    build_slots_for_params,
    default_rf_for_q,
    find_edges_for_slot,
)
from src.export.exp_node_transition.bcc_explicit_cores import default_exp_out_dir
from src.export.exp_node_transition.bcc_fillet_blend import (
    ExpFilletParams,
    fuse_pipes_unitcell_bare_ladder,
)
from src.export.ocp_paper_box_array_fuse import ocp_read_step_shape
from src.export.ocp_unitcell_fuse import ocp_mass, ocp_shape_topology, ocp_write_step


def _edge_len(edge):
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from OCP.GCPnts import GCPnts_AbscissaPoint

    c = BRepAdaptor_Curve(edge)
    return float(GCPnts_AbscissaPoint.Length_s(c))


def _try_one(bare, m0, span0, edge, r, tag, out_dir):
    try:
        sh = _as_single_solid(_try_fillet_per_edge(bare, [(edge, r)]))
    except Exception as exc:
        return f"fillet_fail:{exc}"
    m1 = float(ocp_mass(sh))
    dm = m1 - m0
    sp = _bbox_span(sh)
    topo = ocp_shape_topology(sh, check_brep=True)
    valid = bool(topo.get("brep_valid"))
    if max(sp) > 27.0:
        return f"bbox dm={dm:+.3f} valid={valid}"
    if not valid:
        return f"invalid dm={dm:+.3f} span={tuple(round(x,2) for x in sp)}"
    if dm < -0.2:
        return f"neg_dm={dm:+.3f} valid"
    path = os.path.join(out_dir, f"{tag}.step")
    try:
        ocp_write_step(sh, path)
        rb = ocp_read_step_shape(path)
        rb_m = float(ocp_mass(rb))
        if abs(rb_m - m1) > 0.8:
            return f"valid_STEP_mass_lost mem={m1:.3f} rb={rb_m:.3f}"
        return {
            "ok": True,
            "dm": dm,
            "dm_rb": rb_m - m0,
            "path": path,
            "r": r,
            "tag": tag,
        }
    except Exception as exc:
        return f"valid_STEP_fail:{exc}"


def main() -> int:
    out_dir = os.path.join(default_exp_out_dir(), "_fillet_alt_edge_probe")
    os.makedirs(out_dir, exist_ok=True)
    q = 1.5
    params = SlotFilletParams(period_factor=q, r_blend_factor=default_rf_for_q(q))
    # loosen like apply_slot_fillets
    params.r_band_max_mm = 5.0
    params.r_band_min_mm = 0.8
    params.max_ray_dist_mm = 1.6
    params.max_plane_dist_mm = 1.6
    params.normal_dot_max = 0.9
    params.max_edge_len_mm = 8.0

    fp = ExpFilletParams(
        cell_size_mm=20.0,
        rod_d_mm=2.0,
        amplitude_mm=2.0,
        period_factor=q,
        n_segments=32,
    )
    bare, m0, fuse_tag, _ = fuse_pipes_unitcell_bare_ladder(fp)
    span0 = _bbox_span(bare)
    print(f"bare={m0:.3f} fuse={fuse_tag}", flush=True)

    slots = build_slots_for_params(params)
    wins = []
    seen_mids: set = set()
    n_try = 0

    for slot in slots:
        cands = find_edges_for_slot(bare, slot, params)
        print(
            f"slot#{slot.slot_id:02d} [{_slot_z_group(slot)}] "
            f"theta={slot.theta_deg:.1f} n_cand={len(cands)}",
            flush=True,
        )
        for ci, info in enumerate(cands[:5]):  # top 5 per slot
            midk = _mid_key(info["mid"])
            if midk in seen_mids:
                continue
            seen_mids.add(midk)
            elen = float(info["length_mm"])
            for r in (0.03, 0.04, 0.05, 0.06, 0.08):
                tag = (
                    f"s{slot.slot_id}_c{ci}_L{elen:.2f}_r{r:.3f}".replace(".", "p")
                )
                n_try += 1
                res = _try_one(bare, m0, span0, info["edge"], r, tag, out_dir)
                if isinstance(res, dict) and res.get("ok"):
                    print(f"  WIN {res}", flush=True)
                    wins.append(res)
                    break
                else:
                    if "valid" in str(res) and "invalid" not in str(res):
                        print(f"  {tag}: {res}", flush=True)
                    elif n_try <= 30 or "STEP" in str(res):
                        print(f"  {tag}: {res}", flush=True)

    # Also: short edges by |mid| near origin (centre cluster), not slot-filtered
    print("\n-- centre-prox edges by length --", flush=True)
    from OCP.TopAbs import TopAbs_EDGE
    from OCP.TopExp import TopExp_Explorer
    from OCP.BRep import BRep_Tool
    from OCP.TopoDS import TopoDS
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from OCP.gp import gp_Pnt
    import numpy as np

    edges = []
    exp = TopExp_Explorer(bare, TopAbs_EDGE)
    while exp.More():
        e = TopoDS.Edge_s(exp.Current())
        exp.Next()
        try:
            c = BRepAdaptor_Curve(e)
            u0, u1 = c.FirstParameter(), c.LastParameter()
            p0 = c.Value(u0)
            p1 = c.Value(u1)
            mid = np.array(
                [0.5 * (p0.X() + p1.X()), 0.5 * (p0.Y() + p1.Y()), 0.5 * (p0.Z() + p1.Z())]
            )
            from OCP.GCPnts import GCPnts_AbscissaPoint

            L = float(GCPnts_AbscissaPoint.Length_s(c))
        except Exception:
            continue
        rmid = float(np.linalg.norm(mid))
        if L < 0.4 or L > 3.0:
            continue
        if rmid > 4.0:
            continue
        edges.append((L, rmid, mid, e))
    edges.sort(key=lambda x: (x[1], x[0]))
    print(f"centre-prox short edges={len(edges)}", flush=True)
    for i, (L, rmid, mid, e) in enumerate(edges[:12]):
        for r in (0.03, 0.04, 0.05):
            tag = f"cen_i{i}_L{L:.2f}_rm{rmid:.2f}_r{r:.3f}".replace(".", "p")
            res = _try_one(bare, m0, span0, e, r, tag, out_dir)
            print(f"  {tag}: {res if not isinstance(res, dict) else 'WIN '+str(res)}", flush=True)
            if isinstance(res, dict) and res.get("ok"):
                wins.append(res)
                break

    print(f"\n=== WINS n={len(wins)} tried~{n_try} ===", flush=True)
    for w in wins:
        print(f"  {w}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
