"""
Diagnose: why Q=0.5 MakeFillet is valid but Q=1.5 is not.
Also try: gmsh-heal bare THEN MakeFillet.

  py -3 scripts/exp_fillet_diagnose_q05_vs_q15.py
"""

from __future__ import annotations

import os
import sys
import tempfile

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from OCP.BRepBuilderAPI import BRepBuilderAPI_Copy
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.BRepCheck import BRepCheck_Status
from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_SHELL, TopAbs_SOLID
from OCP.TopExp import TopExp_Explorer
from OCP.TopoDS import TopoDS

from src.export.exp_node_transition.acute_slot_fillet import (
    SlotFilletParams,
    _as_single_solid,
    _assign_edge_for_slot,
    _bbox_span,
    _mid_key,
    _slot_z_group,
    _try_fillet_per_edge,
    _write_step_hard_solid,
    apply_slot_fillets,
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
from src.export.ocp_unitcell_fuse import (
    ocp_mass,
    ocp_shape_topology,
    ocp_write_step,
    ocp_write_step_via_gmsh_brep_heal,
)
from src.export.ocp_paper_box_array_fuse import ocp_read_step_shape


def _check_report(shape, label: str) -> dict:
    topo = ocp_shape_topology(shape, check_brep=True)
    ana = BRepCheck_Analyzer(shape)
    ok = bool(ana.IsValid())
    # sample a few failing statuses
    fails = []
    for typ, name in (
        (TopAbs_SOLID, "solid"),
        (TopAbs_SHELL, "shell"),
        (TopAbs_FACE, "face"),
        (TopAbs_EDGE, "edge"),
    ):
        exp = TopExp_Explorer(shape, typ)
        n = 0
        while exp.More() and n < 40:
            sub = exp.Current()
            exp.Next()
            n += 1
            res = ana.Result(sub)
            if res is None:
                continue
            # iterate statuses via StatusOnShape if available
            try:
                from OCP.BRepCheck import BRepCheck_ListIteratorOfListOfStatus

                it = BRepCheck_ListIteratorOfListOfStatus(res.Status())
                while it.More():
                    st = it.Value()
                    if int(st) != int(BRepCheck_Status.BRepCheck_NoError):
                        fails.append(f"{name}:{st}")
                        if len(fails) >= 12:
                            break
                    it.Next()
            except Exception:
                pass
            if len(fails) >= 12:
                break
    print(
        f"  [{label}] mass={ocp_mass(shape):.3f} valid={topo.get('brep_valid')} "
        f"ana={ok} solids={topo.get('solids')} fails={fails[:8]}",
        flush=True,
    )
    return {"valid": topo.get("brep_valid"), "ana": ok, "fails": fails}


def _gmsh_heal_roundtrip(shape, path_stem: str):
    """BREP→gmsh heal→STEP→read solid."""
    step = path_stem + ".step"
    ocp_write_step_via_gmsh_brep_heal(
        shape, step, heal_mm=0.05, skip_gmsh_heal=False, fast_readback=True
    )
    return ocp_read_step_shape(step)


def main() -> int:
    out = os.path.join(default_exp_out_dir(), "_fillet_diagnose")
    os.makedirs(out, exist_ok=True)

    # --- Q=0.5 reference (known good) ---
    print("\n=== Q=0.5 reference ===", flush=True)
    q = 0.5
    params = SlotFilletParams(period_factor=q, r_blend_factor=default_rf_for_q(q))
    fp = ExpFilletParams(
        cell_size_mm=20, rod_d_mm=2, amplitude_mm=2, period_factor=q, n_segments=32
    )
    bare05, m05, tag05, _ = fuse_pipes_unitcell_bare_ladder(fp)
    _check_report(bare05, "q0.5 bare")
    work = BRepBuilderAPI_Copy(bare05).Shape()
    final05, info05 = apply_slot_fillets(work, params)
    _check_report(final05, "q0.5 fillet")
    print(f"  mode={info05.get('mode')} n={info05.get('n_slots_filled')}", flush=True)

    # --- Q=1.5 ---
    print("\n=== Q=1.5 diagnose ===", flush=True)
    q = 1.5
    fp15 = ExpFilletParams(
        cell_size_mm=20, rod_d_mm=2, amplitude_mm=2, period_factor=q, n_segments=32
    )
    bare15, m15, tag15, _ = fuse_pipes_unitcell_bare_ladder(fp15)
    _check_report(bare15, "q1.5 bare")

    ip = IntersectionFilletParams(period_factor=q, select_radius_mm=5.5)
    cands = collect_intersection_edges(bare15, ip)
    print(f"  n_cand={len(cands)}", flush=True)

    # Try fillet on longest +Δm-friendly cand
    best = None
    for info in cands[:6]:
        for r in (0.04, 0.05):
            try:
                work = BRepBuilderAPI_Copy(bare15).Shape()
                # rebind
                c2 = collect_intersection_edges(work, ip)
                # match by length approx
                hit = min(c2, key=lambda d: abs(d["length_mm"] - info["length_mm"]))
                sh = _as_single_solid(_try_fillet_per_edge(work, [(hit["edge"], r)]))
                dm = float(ocp_mass(sh)) - m15
                sp = _bbox_span(sh)
                if max(sp) > 27 or abs(dm) > 5:
                    continue
                rep = _check_report(sh, f"q1.5 fillet L={info['length_mm']:.2f} r={r}")
                if best is None or (dm > 0 and dm > best[0]):
                    best = (dm, sh, r, info["length_mm"], rep)
            except Exception as exc:
                print(f"  skip L={info['length_mm']:.2f} r={r}: {exc}", flush=True)

    # --- gmsh-heal bare then fillet ---
    print("\n=== Q=1.5 gmsh-heal bare → fillet ===", flush=True)
    try:
        healed = _gmsh_heal_roundtrip(
            bare15, os.path.join(out, "q15_bare_gmshheal")
        )
        healed = _as_single_solid(healed)
        _check_report(healed, "q1.5 gmsh-healed bare")
        cands_h = collect_intersection_edges(healed, ip)
        print(f"  healed n_cand={len(cands_h)}", flush=True)
        wins = []
        for ci, info in enumerate(cands_h[:6]):
            for r in (0.04, 0.05, 0.06, 0.03):
                try:
                    work = BRepBuilderAPI_Copy(healed).Shape()
                    c2 = collect_intersection_edges(work, ip)
                    if ci >= len(c2):
                        break
                    sh = _as_single_solid(
                        _try_fillet_per_edge(work, [(c2[ci]["edge"], r)])
                    )
                    m1 = float(ocp_mass(sh))
                    dm = m1 - float(ocp_mass(healed))
                    sp = _bbox_span(sh)
                    topo = ocp_shape_topology(sh, check_brep=True)
                    print(
                        f"  heal+fillet c{ci} r={r}: dm={dm:+.3f} "
                        f"valid={topo.get('brep_valid')} span_ok={max(sp)<=27}",
                        flush=True,
                    )
                    if not topo.get("brep_valid") or max(sp) > 27 or dm < -0.05:
                        continue
                    path = os.path.join(out, f"q15_heal_fillet_c{ci}_r{r}.step".replace(".", "p"))
                    rb = _write_step_hard_solid(
                        sh,
                        path,
                        mass_ref=m1,
                        max_drift=0.8,
                        max_span_mm=27.0,
                    )
                    print(
                        f"  WIN heal+fillet c{ci} r={r} dm_rb={ocp_mass(rb)-m15:+.3f}",
                        flush=True,
                    )
                    wins.append(path)
                except Exception as exc:
                    print(f"  fail c{ci} r={r}: {exc}", flush=True)
        print(f"  heal wins={len(wins)}", flush=True)
    except Exception as exc:
        print(f"  gmsh-heal path fail: {exc}", flush=True)
        import traceback

        traceback.print_exc()

    # --- Q=1 centre_stub: gmsh heal then fillet ---
    print("\n=== Q=1 gmsh-heal bare → fillet ===", flush=True)
    try:
        fp1 = ExpFilletParams(
            cell_size_mm=20, rod_d_mm=2, amplitude_mm=2, period_factor=1.0, n_segments=32
        )
        bare1, m1b, tag1, _ = fuse_pipes_unitcell_bare_ladder(fp1)
        _check_report(bare1, "q1 bare")
        healed1 = _as_single_solid(
            _gmsh_heal_roundtrip(bare1, os.path.join(out, "q1_bare_gmshheal"))
        )
        _check_report(healed1, "q1 gmsh-healed bare")
        ip1 = IntersectionFilletParams(period_factor=1.0, select_radius_mm=5.0)
        c1 = collect_intersection_edges(healed1, ip1)
        print(f"  q1 healed n_cand={len(c1)}", flush=True)
        for ci, info in enumerate(c1[:6]):
            for r in (0.05, 0.06, 0.08, 0.04):
                try:
                    work = BRepBuilderAPI_Copy(healed1).Shape()
                    c2 = collect_intersection_edges(work, ip1)
                    if ci >= len(c2):
                        break
                    sh = _as_single_solid(
                        _try_fillet_per_edge(work, [(c2[ci]["edge"], r)])
                    )
                    topo = ocp_shape_topology(sh, check_brep=True)
                    dm = float(ocp_mass(sh)) - float(ocp_mass(healed1))
                    sp = _bbox_span(sh)
                    print(
                        f"  q1 heal+fillet c{ci} r={r}: dm={dm:+.3f} "
                        f"valid={topo.get('brep_valid')} span_ok={max(sp)<=27}",
                        flush=True,
                    )
                    if topo.get("brep_valid") and max(sp) <= 27 and dm >= -0.05:
                        path = os.path.join(
                            out, f"q1_heal_fillet_c{ci}_r{r}.step".replace(".", "p")
                        )
                        rb = _write_step_hard_solid(
                            sh, path, mass_ref=float(ocp_mass(sh)), max_drift=0.8, max_span_mm=27
                        )
                        print(f"  WIN q1 → {path} mass={ocp_mass(rb):.3f}", flush=True)
                except Exception as exc:
                    print(f"  q1 fail c{ci} r={r}: {exc}", flush=True)
    except Exception as exc:
        print(f"  q1 path fail: {exc}", flush=True)
        import traceback

        traceback.print_exc()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
