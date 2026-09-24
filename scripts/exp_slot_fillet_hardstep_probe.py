"""
Probe: can MakeFillet for Q=1 / Q=1.5 survive hard STEP via promote-rewrite?

  py -3 scripts/exp_slot_fillet_hardstep_probe.py
"""

from __future__ import annotations

import os
import sys
import tempfile
import traceback

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from src.export.exp_node_transition.acute_slot_fillet import (
    SlotFilletParams,
    _as_single_solid,
    _assign_edge_for_slot,
    _bbox_span,
    _mid_key,
    _slot_z_group,
    _try_fillet_per_edge,
    _write_step_hard_solid,
    build_slots_for_params,
    default_rf_for_q,
)
from src.export.exp_node_transition.bcc_explicit_cores import default_exp_out_dir
from src.export.exp_node_transition.bcc_fillet_blend import (
    ExpFilletParams,
    fuse_pipes_unitcell_bare_ladder,
)
from src.export.ocp_unitcell_fuse import ocp_mass, ocp_shape_topology, ocp_write_step


def _collect_pairs(bare, params, *, only_bot_top: bool, max_elen: float | None):
    slots = build_slots_for_params(params)
    used: set[tuple[float, float, float]] = set()
    pairs = []
    for slot in slots:
        if only_bot_top and _slot_z_group(slot) not in ("bot", "top"):
            continue
        info = _assign_edge_for_slot(
            bare, slot, params, used_mids=used, max_edge_len_mm=max_elen
        )
        if info is None:
            continue
        used.add(_mid_key(info["mid"]))
        pairs.append((slot, info))
    return pairs


def _gate_mem(shape, m0, span0, max_span, *, dm_lo=-0.5, dm_hi=8.0):
    solid = _as_single_solid(shape)
    m1 = float(ocp_mass(solid))
    dm = m1 - float(m0)
    sp = _bbox_span(solid)
    if max(sp) > max_span:
        raise RuntimeError(f"bbox {sp}")
    for k in range(3):
        if sp[k] > float(span0[k]) + 2.5:
            raise RuntimeError(f"span_grow[{k}] {span0[k]:.2f}->{sp[k]:.2f}")
    if dm < dm_lo or dm > dm_hi:
        raise RuntimeError(f"dmass {dm:+.3f}")
    return solid, m1, dm, sp


def _try_hard_step(shape, tag, m0, out_dir):
    path = os.path.join(out_dir, f"_probe_{tag}.step")
    try:
        rb = _write_step_hard_solid(
            shape,
            path,
            mass_ref=float(ocp_mass(shape)),
            max_drift=1.2,
            max_span_mm=20.0 * 1.35,
        )
        topo = ocp_shape_topology(rb, check_brep=True)
        m = float(ocp_mass(rb))
        print(
            f"  HARD STEP OK {tag} mass={m:.3f} dm={m - m0:+.3f} "
            f"valid={topo.get('brep_valid')} solids={topo.get('solids')} "
            f"→ {path}",
            flush=True,
        )
        return True, rb, path
    except Exception as exc:
        print(f"  HARD STEP FAIL {tag}: {exc}", flush=True)
        return False, None, path


def probe_q15(out_dir: str) -> list[dict]:
    q = 1.5
    rf = default_rf_for_q(q)
    params = SlotFilletParams(period_factor=q, r_blend_factor=rf)
    fp = ExpFilletParams(
        cell_size_mm=20.0,
        rod_d_mm=2.0,
        amplitude_mm=2.0,
        period_factor=q,
        n_segments=32,
    )
    print(f"\n=== PROBE Q={q} bare fuse ===", flush=True)
    bare, m0, fuse_tag, _ = fuse_pipes_unitcell_bare_ladder(fp)
    span0 = _bbox_span(bare)
    max_span = 20.0 * 1.35
    print(f"  fuse={fuse_tag} mass={m0:.3f} span={span0}", flush=True)

    pairs = _collect_pairs(bare, params, only_bot_top=True, max_elen=2.5)
    print(f"  unique bot/top edges={len(pairs)}", flush=True)
    results: list[dict] = []

    # 1) single-edge ladder
    print("\n-- single-edge MakeFillet --", flush=True)
    singles_ok: list[tuple] = []
    for slot, info in pairs:
        g = _slot_z_group(slot)
        for r in (0.03, 0.04, 0.05, 0.06):
            tag = f"q15_1e_{g}_s{slot.slot_id}_r{r:.3f}".replace(".", "p")
            try:
                trial = _try_fillet_per_edge(bare, [(info["edge"], r)])
                solid, m1, dm, sp = _gate_mem(trial, m0, span0, max_span)
                ok, _, path = _try_hard_step(solid, tag, m0, out_dir)
                row = {
                    "tag": tag,
                    "n": 1,
                    "r": r,
                    "dm": dm,
                    "hard": ok,
                    "path": path if ok else None,
                }
                results.append(row)
                if ok:
                    singles_ok.append((slot, info, r, solid, dm))
                    print(f"  WIN single {tag} dm={dm:+.3f}", flush=True)
                    break
            except Exception as exc:
                print(f"  skip {tag}: {exc}", flush=True)

    # 2) opposite bot+top oneshot (best dm singles if available)
    print("\n-- opposite bot+top oneshot --", flush=True)
    bots = [(s, i) for s, i in pairs if _slot_z_group(s) == "bot"]
    tops = [(s, i) for s, i in pairs if _slot_z_group(s) == "top"]
    if bots and tops:
        # prefer scored +Δm
        def score(s, i):
            best = None
            for r in (0.05, 0.04, 0.035, 0.045):
                try:
                    t = _try_fillet_per_edge(bare, [(i["edge"], r)])
                    solid, m1, dm, sp = _gate_mem(t, m0, span0, max_span)
                    if best is None or dm > best[0]:
                        best = (dm, r)
                except Exception:
                    continue
            return best

        sb = [(s, i, score(s, i)) for s, i in bots]
        st = [(s, i, score(s, i)) for s, i in tops]
        sb = [x for x in sb if x[2]]
        st = [x for x in st if x[2]]
        sb.sort(key=lambda x: -x[2][0])
        st.sort(key=lambda x: -x[2][0])
        combos = []
        if sb and st:
            combos.append((sb[0], st[0]))
        # also try first assigned edges
        if bots and tops:
            combos.append(
                ((bots[0][0], bots[0][1], (0.0, 0.04)), (tops[0][0], tops[0][1], (0.0, 0.04)))
            )
        seen = set()
        for (s1, i1, sc1), (s2, i2, sc2) in combos:
            r1, r2 = float(sc1[1]), float(sc2[1])
            key = (s1.slot_id, s2.slot_id, r1, r2)
            if key in seen:
                continue
            seen.add(key)
            tag = f"q15_opp_s{s1.slot_id}_{s2.slot_id}_r{r1:.3f}_{r2:.3f}".replace(
                ".", "p"
            )
            try:
                trial = _try_fillet_per_edge(
                    bare, [(i1["edge"], r1), (i2["edge"], r2)]
                )
                solid, m1, dm, sp = _gate_mem(trial, m0, span0, max_span)
                print(
                    f"  mem OK {tag} dm={dm:+.3f} span={tuple(round(x,2) for x in sp)}",
                    flush=True,
                )
                ok, _, path = _try_hard_step(solid, tag, m0, out_dir)
                results.append(
                    {"tag": tag, "n": 2, "r": (r1, r2), "dm": dm, "hard": ok, "path": path if ok else None}
                )
                if ok:
                    print(f"  WIN opposite {tag}", flush=True)
            except Exception as exc:
                print(f"  skip {tag}: {exc}", flush=True)

    # 3) sequential 1-edge accumulate with hard STEP after each
    print("\n-- sequential 1-edge accumulate + hard STEP --", flush=True)
    cur = bare
    m_cur = float(m0)
    span_cur = span0
    filled = 0
    for slot, info in pairs:
        g = _slot_z_group(slot)
        applied = False
        for r in (0.04, 0.035, 0.03, 0.05):
            tag = f"q15_seq{filled}_{g}_s{slot.slot_id}_r{r:.3f}".replace(".", "p")
            try:
                # re-assign edge on current shape mid proximity
                info2 = _assign_edge_for_slot(
                    cur,
                    slot,
                    params,
                    used_mids=set(),
                    max_edge_len_mm=2.5,
                )
                edge = info2["edge"] if info2 is not None else info["edge"]
                trial = _try_fillet_per_edge(cur, [(edge, r)])
                solid, m1, dm, sp = _gate_mem(
                    trial, m_cur, span_cur, max_span, dm_lo=-0.8, dm_hi=4.0
                )
                ok, rb, path = _try_hard_step(solid, tag, m0, out_dir)
                if not ok:
                    continue
                cur = rb
                m_cur = float(ocp_mass(cur))
                span_cur = _bbox_span(cur)
                filled += 1
                applied = True
                results.append(
                    {
                        "tag": tag,
                        "n": filled,
                        "r": r,
                        "dm": m_cur - m0,
                        "hard": True,
                        "path": path,
                    }
                )
                print(
                    f"  SEQ OK n={filled} {tag} mass={m_cur:.3f} dm_total={m_cur-m0:+.3f}",
                    flush=True,
                )
                break
            except Exception as exc:
                print(f"  seq skip {tag}: {exc}", flush=True)
        if not applied:
            print(f"  seq stop at slot {slot.slot_id} ({g})", flush=True)
            # continue trying other slots
            continue

    if filled:
        final_path = os.path.join(out_dir, "_probe_q15_seq_final.step")
        ocp_write_step(cur, final_path)
        print(f"  SEQ FINAL filled={filled} mass={m_cur:.3f} → {final_path}", flush=True)

    return results


def probe_q1(out_dir: str) -> list[dict]:
    q = 1.0
    rf = default_rf_for_q(q)
    params = SlotFilletParams(period_factor=q, r_blend_factor=rf)
    fp = ExpFilletParams(
        cell_size_mm=20.0,
        rod_d_mm=2.0,
        amplitude_mm=2.0,
        period_factor=q,
        n_segments=32,
    )
    print(f"\n=== PROBE Q={q} bare fuse ===", flush=True)
    bare, m0, fuse_tag, _ = fuse_pipes_unitcell_bare_ladder(fp)
    span0 = _bbox_span(bare)
    max_span = 20.0 * 1.35
    print(f"  fuse={fuse_tag} mass={m0:.3f} span={span0}", flush=True)

    pairs = _collect_pairs(bare, params, only_bot_top=False, max_elen=None)
    print(f"  unique edges={len(pairs)}", flush=True)
    results: list[dict] = []

    # Does any single edge MakeFillet IsDone?
    print("\n-- Q=1 single-edge IsDone / hard STEP --", flush=True)
    for slot, info in pairs[:8]:
        g = _slot_z_group(slot)
        for r in (0.08, 0.06, 0.05, 0.04, 0.03, 0.02):
            tag = f"q1_1e_{g}_s{slot.slot_id}_r{r:.3f}".replace(".", "p")
            try:
                trial = _try_fillet_per_edge(bare, [(info["edge"], r)])
                solid, m1, dm, sp = _gate_mem(
                    trial, m0, span0, max_span, dm_lo=-1.0, dm_hi=6.0
                )
                print(
                    f"  mem OK {tag} dm={dm:+.3f} span={tuple(round(x,2) for x in sp)}",
                    flush=True,
                )
                ok, _, path = _try_hard_step(solid, tag, m0, out_dir)
                results.append(
                    {"tag": tag, "n": 1, "r": r, "dm": dm, "hard": ok, "path": path if ok else None}
                )
                if ok:
                    print(f"  WIN Q1 {tag}", flush=True)
                    break
            except Exception as exc:
                print(f"  skip {tag}: {exc}", flush=True)

    # UnifySameDomain then fillet one edge
    print("\n-- Q=1 UnifySameDomain + single fillet --", flush=True)
    try:
        from OCP.ShapeUpgrade import ShapeUpgrade_UnifySameDomain

        un = ShapeUpgrade_UnifySameDomain(bare, True, True, True)
        un.Build()
        u_shape = un.Shape()
        u_solid = _as_single_solid(u_shape)
        print(f"  unify mass={ocp_mass(u_solid):.3f}", flush=True)
        upairs = _collect_pairs(u_solid, params, only_bot_top=False, max_elen=None)
        print(f"  unify unique edges={len(upairs)}", flush=True)
        for slot, info in upairs[:6]:
            for r in (0.06, 0.04, 0.03):
                tag = f"q1_uni_s{slot.slot_id}_r{r:.3f}".replace(".", "p")
                try:
                    trial = _try_fillet_per_edge(u_solid, [(info["edge"], r)])
                    solid, m1, dm, sp = _gate_mem(
                        trial, m0, span0, max_span, dm_lo=-1.0, dm_hi=6.0
                    )
                    ok, _, path = _try_hard_step(solid, tag, m0, out_dir)
                    results.append(
                        {
                            "tag": tag,
                            "n": 1,
                            "r": r,
                            "dm": dm,
                            "hard": ok,
                            "path": path if ok else None,
                        }
                    )
                    if ok:
                        print(f"  WIN Q1 unify {tag} dm={dm:+.3f}", flush=True)
                        break
                except Exception as exc:
                    print(f"  skip {tag}: {exc}", flush=True)
    except Exception as exc:
        print(f"  unify path fail: {exc}", flush=True)
        traceback.print_exc()

    return results


def main() -> int:
    out_dir = os.path.join(default_exp_out_dir(), "_fillet_hardstep_probe")
    os.makedirs(out_dir, exist_ok=True)
    print(f"out_dir={out_dir}", flush=True)

    r15 = probe_q15(out_dir)
    r1 = probe_q1(out_dir)

    print("\n=== WINS ===", flush=True)
    wins = [r for r in (r15 + r1) if r.get("hard")]
    if not wins:
        print("  (none)", flush=True)
    for w in wins:
        print(f"  {w}", flush=True)
    print(f"\nn_wins={len(wins)} / tried={len(r15)+len(r1)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
