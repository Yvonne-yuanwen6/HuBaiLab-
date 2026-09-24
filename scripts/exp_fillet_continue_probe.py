"""
Continue MakeFillet hunt: pristine bare copy + concave intersection edges
+ require brep_valid + hard STEP mass preserve.

  py -3 scripts/exp_fillet_continue_probe.py
"""

from __future__ import annotations

import os
import sys
import tempfile

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from OCP.BRepBuilderAPI import BRepBuilderAPI_Copy

from src.export.exp_node_transition.acute_slot_fillet import (
    _as_single_solid,
    _bbox_span,
    _try_fillet_per_edge,
    _write_step_hard_solid,
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
from src.export.ocp_paper_box_array_fuse import ocp_read_step_shape
from src.export.ocp_unitcell_fuse import ocp_mass, ocp_shape_topology, ocp_write_step


def _unify(shape):
    from OCP.ShapeUpgrade import ShapeUpgrade_UnifySameDomain

    un = ShapeUpgrade_UnifySameDomain(shape, True, True, True)
    un.Build()
    return un.Shape()


def _hard_ok(shape, m_mem, path, max_drift=0.8, max_span=27.0):
    rb = _write_step_hard_solid(
        shape,
        path,
        mass_ref=float(m_mem),
        max_drift=max_drift,
        max_span_mm=max_span,
    )
    rb_m = float(ocp_mass(rb))
    if abs(rb_m - float(m_mem)) > max_drift:
        raise RuntimeError(f"drift mem={m_mem:.3f} rb={rb_m:.3f}")
    return rb, rb_m


def probe_q(q: float, out_dir: str) -> list[dict]:
    print(f"\n======== Q={q} ========", flush=True)
    rf = {0.0: 0.35, 0.5: 0.28, 1.0: 0.18, 1.5: 0.12}.get(q, 0.12)
    fp = ExpFilletParams(
        cell_size_mm=20.0,
        rod_d_mm=2.0,
        amplitude_mm=2.0,
        period_factor=q,
        n_segments=32,
    )
    bare0, m0, tag, _ = fuse_pipes_unitcell_bare_ladder(fp)
    print(f"  fuse={tag} mass={m0:.3f}", flush=True)
    span0 = _bbox_span(bare0)
    wins: list[dict] = []

    seeds = [("raw", BRepBuilderAPI_Copy(bare0).Shape())]
    try:
        u = _as_single_solid(_unify(BRepBuilderAPI_Copy(bare0).Shape()))
        seeds.append(("unify", u))
        print(f"  unify mass={ocp_mass(u):.3f}", flush=True)
    except Exception as exc:
        print(f"  unify skip: {exc}", flush=True)

    ip = IntersectionFilletParams(
        period_factor=q,
        r_blend_factor=rf,
        select_radius_mm=5.5,
        max_edge_len_mm=6.0,
        min_edge_len_mm=0.35,
        normal_dot_max=0.9,
    )
    r0 = rf * 1.0  # strut R=1

    for seed_tag, seed in seeds:
        # work on a fresh copy each radius attempt chain
        cands = collect_intersection_edges(seed, ip)
        print(f"  [{seed_tag}] n_cand={len(cands)}", flush=True)
        if not cands:
            continue

        # --- single-edge sweep: require valid + hard STEP ---
        for ci in range(min(8, len(cands))):
            for r in (0.04, 0.05, 0.06, 0.08, 0.03, 0.10):
                tag = f"q{q}_{seed_tag}_1e_c{ci}_r{r}".replace(".", "p")
                try:
                    work = BRepBuilderAPI_Copy(seed).Shape()
                    c_now = collect_intersection_edges(work, ip)
                    if ci >= len(c_now):
                        break
                    info = c_now[ci]
                    sh = _as_single_solid(
                        _try_fillet_per_edge(work, [(info["edge"], r)])
                    )
                except Exception:
                    continue
                m1 = float(ocp_mass(sh))
                dm = m1 - m0
                sp = _bbox_span(sh)
                topo = ocp_shape_topology(sh, check_brep=True)
                valid = bool(topo.get("brep_valid"))
                if max(sp) > 27 or abs(dm) > 5:
                    continue
                print(
                    f"    {tag}: dm={dm:+.3f} valid={valid} "
                    f"L={info['length_mm']:.2f} ndot={info.get('ndot', float('nan')):.2f}",
                    flush=True,
                )
                if not valid or dm < -0.05:
                    continue
                path = os.path.join(out_dir, f"{tag}.step")
                try:
                    rb, rb_m = _hard_ok(sh, m1, path, max_drift=0.8)
                    print(
                        f"    WIN {tag} dm_rb={rb_m - m0:+.3f}",
                        flush=True,
                    )
                    wins.append(
                        {
                            "tag": tag,
                            "q": q,
                            "seed": seed_tag,
                            "n": 1,
                            "r": r,
                            "dm": dm,
                            "dm_rb": rb_m - m0,
                            "path": path,
                        }
                    )
                except Exception as exc:
                    print(f"    STEP fail {tag}: {exc}", flush=True)

        # --- sequential valid+STEP accumulate ---
        print(f"  [{seed_tag}] sequential accumulate...", flush=True)
        cur = BRepBuilderAPI_Copy(seed).Shape()
        m_cur = float(ocp_mass(cur))
        filled = 0
        for _pass_i in range(6):
            if filled >= 4:
                break
            cands2 = collect_intersection_edges(cur, ip)[:6]
            got = False
            for ci, info in enumerate(cands2):
                for r in (0.04, 0.035, 0.05, 0.03):
                    tag = (
                        f"q{q}_{seed_tag}_seq{filled}_c{ci}_r{r}".replace(
                            ".", "p"
                        )
                    )
                    try:
                        work = BRepBuilderAPI_Copy(cur).Shape()
                        # re-bind edge on the working copy
                        c_work = collect_intersection_edges(work, ip)
                        if ci >= len(c_work):
                            break
                        info_w = c_work[ci]
                        trial = _as_single_solid(
                            _try_fillet_per_edge(
                                work, [(info_w["edge"], r)]
                            )
                        )
                        m1 = float(ocp_mass(trial))
                        dm = m1 - m_cur
                        sp = _bbox_span(trial)
                        topo = ocp_shape_topology(trial, check_brep=True)
                        if (
                            not topo.get("brep_valid")
                            or max(sp) > 27
                            or dm < -0.05
                            or dm > 3.0
                        ):
                            continue
                        path = os.path.join(out_dir, f"{tag}.step")
                        rb, rb_m = _hard_ok(trial, m1, path, max_drift=0.8)
                        if rb_m < 0.95 * m0:
                            continue
                        cur = rb
                        m_cur = rb_m
                        filled += 1
                        got = True
                        print(
                            f"    SEQ WIN n={filled} {tag} "
                            f"dm_total={m_cur - m0:+.3f} valid=True",
                            flush=True,
                        )
                        wins.append(
                            {
                                "tag": tag,
                                "q": q,
                                "seed": seed_tag,
                                "n": filled,
                                "r": r,
                                "dm": m_cur - m0,
                                "dm_rb": m_cur - m0,
                                "path": path,
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
                out_dir, f"q{q}_{seed_tag}_seq_final.step".replace(".", "p")
            )
            ocp_write_step(cur, final)
            print(
                f"  [{seed_tag}] SEQ FINAL n={filled} mass={m_cur:.3f} → {final}",
                flush=True,
            )

    return wins


def main() -> int:
    out_dir = os.path.join(default_exp_out_dir(), "_fillet_continue_probe")
    os.makedirs(out_dir, exist_ok=True)
    print(f"out={out_dir}", flush=True)
    all_wins: list[dict] = []
    for q in (1.5, 1.0):
        try:
            all_wins.extend(probe_q(q, out_dir))
        except Exception as exc:
            print(f"PROBE FAIL Q={q}: {exc}", flush=True)
            import traceback

            traceback.print_exc()
    print("\n=== ALL TRUE WINS (valid + hard STEP mass OK) ===", flush=True)
    if not all_wins:
        print("  (none)", flush=True)
    for w in all_wins:
        print(f"  {w}", flush=True)
    print(f"n_wins={len(all_wins)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
