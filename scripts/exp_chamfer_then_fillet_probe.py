"""
Chamfer-then-fillet: blunt acute junctions, then MakeFillet for true round.

  py -3 scripts/exp_chamfer_then_fillet_probe.py
"""

from __future__ import annotations

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from OCP.BRepBuilderAPI import BRepBuilderAPI_Copy

from src.export.exp_node_transition.acute_slot_fillet import (
    SlotFilletParams,
    _as_single_solid,
    _assign_edge_for_slot,
    _bbox_span,
    _ensure_written_solid,
    _mid_key,
    _slot_z_group,
    _try_fillet_per_edge,
    _try_slot_chamfer,
    _write_step_hard_solid,
    build_slots_for_params,
    default_rf_for_q,
)
from src.export.exp_node_transition.bcc_explicit_cores import default_exp_out_dir
from src.export.exp_node_transition.bcc_fillet_blend import (
    ExpFilletParams,
    fuse_pipes_unitcell_bare_ladder,
)
from src.export.exp_node_transition.intersection_edge_fillet import (
    IntersectionFilletParams,
    collect_intersection_edges,
)
from src.export.ocp_unitcell_fuse import ocp_mass, ocp_shape_topology, ocp_write_step


def _collect_bt(bare, params):
    used = set()
    pairs = []
    for slot in build_slots_for_params(params):
        if _slot_z_group(slot) not in ("bot", "top"):
            continue
        info = _assign_edge_for_slot(
            bare, slot, params, used_mids=used, max_edge_len_mm=2.5
        )
        if info is None:
            continue
        used.add(_mid_key(info["mid"]))
        pairs.append((slot, info))
    return pairs


def main() -> int:
    out = os.path.join(default_exp_out_dir(), "_chamfer_then_fillet_probe")
    os.makedirs(out, exist_ok=True)
    wins = []

    for q in (1.5, 1.0):
        print(f"\n======== Q={q} chamfer→fillet ========", flush=True)
        params = SlotFilletParams(
            period_factor=q, r_blend_factor=default_rf_for_q(q)
        )
        fp = ExpFilletParams(
            cell_size_mm=20,
            rod_d_mm=2,
            amplitude_mm=2,
            period_factor=q,
            n_segments=32,
        )
        bare, m0, tag, _ = fuse_pipes_unitcell_bare_ladder(fp)
        bare = BRepBuilderAPI_Copy(bare).Shape()
        print(f"  bare={m0:.3f} {tag}", flush=True)

        # 1) STEP-stable chamfer on slot edges
        if abs(q) > 1.2:
            pairs = _collect_bt(bare, params)
            d_ch = 0.04
        else:
            used = set()
            pairs = []
            for slot in build_slots_for_params(params):
                info = _assign_edge_for_slot(
                    bare, slot, params, used_mids=used
                )
                if info is None:
                    continue
                used.add(_mid_key(info["mid"]))
                pairs.append((slot, info))
            d_ch = 0.10

        if not pairs:
            print("  no chamfer pairs", flush=True)
            continue

        try:
            ch = _try_slot_chamfer(
                bare, pairs, d_mm=d_ch, m0=m0, max_span=27.0
            )
            ch = _ensure_written_solid(ch)
            ch_path = os.path.join(
                out, f"q{q}_chamfer.step".replace(".", "p")
            )
            ch = _write_step_hard_solid(
                ch,
                ch_path,
                mass_ref=float(ocp_mass(ch)),
                max_drift=1.2,
                max_span_mm=27.0,
            )
            m_ch = float(ocp_mass(ch))
            print(
                f"  chamfer OK n={len(pairs)} d={d_ch} mass={m_ch:.3f} "
                f"valid={ocp_shape_topology(ch, check_brep=True).get('brep_valid')}",
                flush=True,
            )
        except Exception as exc:
            print(f"  chamfer fail: {exc}", flush=True)
            continue

        # 2) Fillet on post-chamfer intersection edges
        ip = IntersectionFilletParams(
            period_factor=q,
            select_radius_mm=5.5,
            max_edge_len_mm=6.0,
            min_edge_len_mm=0.25,
            normal_dot_max=0.95,
        )
        cands = collect_intersection_edges(ch, ip)
        print(f"  post-chamfer n_cand={len(cands)}", flush=True)

        # oneshot: try 1–4 edges with small r
        for n_edges in (1, 2, 4):
            if len(cands) < n_edges:
                continue
            for r in (0.03, 0.04, 0.05, 0.06, 0.08):
                tag_f = f"q{q}_ch{d_ch}_n{n_edges}_r{r}".replace(".", "p")
                try:
                    work = BRepBuilderAPI_Copy(ch).Shape()
                    c2 = collect_intersection_edges(work, ip)
                    if len(c2) < n_edges:
                        continue
                    eprs = [(c2[i]["edge"], r) for i in range(n_edges)]
                    sh = _as_single_solid(_try_fillet_per_edge(work, eprs))
                    m1 = float(ocp_mass(sh))
                    dm = m1 - m_ch
                    sp = _bbox_span(sh)
                    topo = ocp_shape_topology(sh, check_brep=True)
                    print(
                        f"  {tag_f}: dm={dm:+.3f} valid={topo.get('brep_valid')} "
                        f"span_ok={max(sp)<=27}",
                        flush=True,
                    )
                    if (
                        not topo.get("brep_valid")
                        or max(sp) > 27
                        or dm < -0.3
                        or dm > 6
                    ):
                        continue
                    path = os.path.join(out, f"{tag_f}.step")
                    rb = _write_step_hard_solid(
                        sh,
                        path,
                        mass_ref=m1,
                        max_drift=0.8,
                        max_span_mm=27.0,
                    )
                    print(
                        f"  WIN {tag_f} mass={ocp_mass(rb):.3f} "
                        f"dm_vs_bare={ocp_mass(rb)-m0:+.3f}",
                        flush=True,
                    )
                    wins.append(
                        {
                            "tag": tag_f,
                            "q": q,
                            "path": path,
                            "n_edges": n_edges,
                            "r": r,
                            "dm_ch": dm,
                            "dm_bare": float(ocp_mass(rb)) - m0,
                        }
                    )
                except Exception as exc:
                    print(f"  fail {tag_f}: {exc}", flush=True)

        # 3) sequential 1-edge after chamfer
        print("  sequential fillet after chamfer...", flush=True)
        cur = BRepBuilderAPI_Copy(ch).Shape()
        m_cur = float(ocp_mass(cur))
        filled = 0
        for _ in range(6):
            if filled >= 4:
                break
            c2 = collect_intersection_edges(cur, ip)[:8]
            got = False
            for ci in range(len(c2)):
                for r in (0.03, 0.04, 0.05):
                    try:
                        work = BRepBuilderAPI_Copy(cur).Shape()
                        cw = collect_intersection_edges(work, ip)
                        if ci >= len(cw):
                            break
                        sh = _as_single_solid(
                            _try_fillet_per_edge(work, [(cw[ci]["edge"], r)])
                        )
                        m1 = float(ocp_mass(sh))
                        dm = m1 - m_cur
                        sp = _bbox_span(sh)
                        topo = ocp_shape_topology(sh, check_brep=True)
                        if (
                            not topo.get("brep_valid")
                            or max(sp) > 27
                            or dm < -0.2
                            or dm > 3
                        ):
                            continue
                        path = os.path.join(
                            out,
                            f"q{q}_seq{filled}_r{r}.step".replace(".", "p"),
                        )
                        rb = _write_step_hard_solid(
                            sh,
                            path,
                            mass_ref=m1,
                            max_drift=0.8,
                            max_span_mm=27.0,
                        )
                        cur = rb
                        m_cur = float(ocp_mass(cur))
                        filled += 1
                        got = True
                        print(
                            f"  SEQ WIN n={filled} r={r} "
                            f"dm_total={m_cur-m0:+.3f}",
                            flush=True,
                        )
                        wins.append(
                            {
                                "tag": f"q{q}_seq{filled}",
                                "q": q,
                                "path": path,
                                "n_edges": filled,
                                "r": r,
                                "dm_bare": m_cur - m0,
                                "seq": True,
                            }
                        )
                        break
                    except Exception:
                        continue
                if got:
                    break
            if not got:
                break
        if filled:
            final = os.path.join(
                out, f"q{q}_ch_then_fillet_final.step".replace(".", "p")
            )
            ocp_write_step(cur, final)
            print(f"  FINAL n={filled} mass={m_cur:.3f} → {final}", flush=True)

    print("\n=== WINS ===", flush=True)
    for w in wins:
        print(f"  {w}", flush=True)
    print(f"n_wins={len(wins)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
