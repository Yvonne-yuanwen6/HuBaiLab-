"""
Diagnose +Δm but BRep-invalid MakeFillet; try heal routes → hard STEP.

  py -3 scripts/exp_fillet_brep_heal_hardstep.py
"""
from __future__ import annotations

import json
import os
import sys
from typing import Any

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
from src.export.ocp_paper_box_array_fuse import ocp_read_step_shape
from src.export.ocp_unitcell_fuse import (
    ocp_heal_fused_solid,
    ocp_mass,
    ocp_shape_topology,
    ocp_write_step,
    ocp_write_step_via_gmsh_brep_heal,
)


def _loose(q: float) -> SlotFilletParams:
    return SlotFilletParams(
        period_factor=float(q),
        r_blend_factor=float(default_rf_for_q(q)),
        amplitude_mm=2.0,
        rod_d_mm=2.0,
        cell_size_mm=20.0,
        n_segments=32,
        min_edge_len_mm=0.50,
        max_edge_len_mm=8.0,
        r_band_min_mm=0.70,
        r_band_max_mm=5.5,
        max_ray_dist_mm=1.80,
        max_plane_dist_mm=1.80,
        normal_dot_max=0.92,
    )


def _brepcheck_report(shape: Any, *, max_items: int = 8) -> dict[str, Any]:
    """Lightweight validity report — avoid deep Status iterators (OCC crash risk)."""
    from OCP.BRepCheck import BRepCheck_Analyzer
    from OCP.TopAbs import TopAbs_FACE, TopAbs_EDGE
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS

    try:
        ana = BRepCheck_Analyzer(shape)
        ok = bool(ana.IsValid())
    except Exception as exc:
        return {"valid": False, "faults": [f"analyzer:{exc}"]}
    if ok:
        return {"valid": True, "faults": []}
    faults: list[str] = []
    for typ, cast, label in (
        (TopAbs_FACE, TopoDS.Face_s, "face"),
        (TopAbs_EDGE, TopoDS.Edge_s, "edge"),
    ):
        exp = TopExp_Explorer(shape, typ)
        i = 0
        while exp.More() and len(faults) < max_items:
            sub = cast(exp.Current())
            exp.Next()
            i += 1
            try:
                if not ana.IsValid(sub):
                    faults.append(f"{label}#{i}")
            except Exception:
                faults.append(f"{label}#{i}:check_err")
    return {"valid": False, "n_fault_samples": len(faults), "faults": faults}


def _fillet_with_diag(shape: Any, edge: Any, r: float) -> tuple[Any, dict[str, Any]]:
    from OCP.BRepFilletAPI import BRepFilletAPI_MakeFillet

    src = BRepBuilderAPI_Copy(shape).Shape()
    mk = BRepFilletAPI_MakeFillet(src)
    mk.Add(float(r), edge)
    mk.Build()
    diag: dict[str, Any] = {"r": float(r), "IsDone": bool(mk.IsDone())}
    if not mk.IsDone():
        # fault queries only after failed/done build
        for name in ("NbFaultyContours", "NbFaultyVertices", "NbContours"):
            try:
                diag[name] = int(getattr(mk, name)())
            except Exception:
                pass
        try:
            n = int(mk.NbContours()) if hasattr(mk, "NbContours") else 0
            sts = []
            for i in range(1, min(n, 6) + 1):
                try:
                    sts.append(str(mk.StripeStatus(i)).split(".")[-1])
                except Exception:
                    break
            if sts:
                diag["StripeStatus"] = sts
        except Exception:
            pass
        raise RuntimeError(f"MakeFillet not done diag={diag}")
    for name in ("NbContours", "NbSurfaces"):
        try:
            diag[name] = int(getattr(mk, name)())
        except Exception:
            pass
    out = _as_single_solid(mk.Shape())
    return out, diag


def _heal_ladder(shape: Any, m0: float, span0: tuple[float, float, float]):
    """Yield (tag, shape) heal attempts that keep span/mass sane."""
    max_span = 20.0 * 1.35
    variants: list[tuple[str, Any]] = [("raw", shape)]

    try:
        from OCP.ShapeFix import ShapeFix_Shape

        fx = ShapeFix_Shape(shape)
        fx.Perform()
        variants.append(("ShapeFix_Shape", fx.Shape()))
    except Exception as exc:
        print(f"  heal skip ShapeFix_Shape: {exc}", flush=True)

    try:
        from OCP.ShapeFix import ShapeFix_Solid
        from OCP.TopAbs import TopAbs_SOLID
        from OCP.TopExp import TopExp_Explorer
        from OCP.TopoDS import TopoDS

        exp = TopExp_Explorer(shape, TopAbs_SOLID)
        if exp.More():
            fx = ShapeFix_Solid(TopoDS.Solid_s(exp.Current()))
            fx.Perform()
            variants.append(("ShapeFix_Solid", fx.Solid()))
    except Exception as exc:
        print(f"  heal skip ShapeFix_Solid: {exc}", flush=True)

    try:
        variants.append(("ocp_heal_fused", ocp_heal_fused_solid(shape)))
    except Exception as exc:
        print(f"  heal skip ocp_heal_fused: {exc}", flush=True)

    try:
        variants.append(("ensure_written_solid", _ensure_written_solid(shape)))
    except Exception as exc:
        print(f"  heal skip ensure_written_solid: {exc}", flush=True)

    try:
        from OCP.ShapeUpgrade import ShapeUpgrade_UnifySameDomain
        from OCP.ShapeFix import ShapeFix_Shape

        # Unify can crash / collapse fillets — keep last and skip by default
        if os.environ.get("FILLET_HEAL_UNIFY", "").strip() in ("1", "true", "yes"):
            u = ShapeUpgrade_UnifySameDomain(shape, True, True, True)
            u.Build()
            fx = ShapeFix_Shape(u.Shape())
            fx.Perform()
            variants.append(("Unify+ShapeFix", fx.Shape()))
    except Exception as exc:
        print(f"  heal skip Unify: {exc}", flush=True)

    for tag, sh in variants:
        try:
            solid = _as_single_solid(sh)
        except Exception:
            # try promote
            try:
                solid = _ensure_written_solid(sh)
                solid = _as_single_solid(solid)
            except Exception as exc:
                print(f"  {tag}: not solid ({exc})", flush=True)
                continue
        m = float(ocp_mass(solid))
        sp = _bbox_span(solid)
        if m < 0.9 * float(m0) or m > float(m0) + 15.0:
            print(f"  {tag}: bad mass {m:.3f}", flush=True)
            continue
        if max(sp) > max_span or any(sp[k] > span0[k] + 3.0 for k in range(3)):
            print(f"  {tag}: bad bbox {tuple(round(x,2) for x in sp)}", flush=True)
            continue
        yield tag, solid


def _pick_plusdm_candidates(q: float, bare, params) -> list[tuple]:
    """Find (slot, edge_info, r) with memory +Δm on near-centre edges."""
    m0 = float(ocp_mass(bare))
    span0 = _bbox_span(bare)
    out = []
    slots = build_slots_for_params(params)
    used: set = set()
    for slot in slots:
        if _slot_z_group(slot) not in ("bot", "top"):
            continue
        cands = [
            d
            for d in find_edges_for_slot(bare, slot, params)
            if 0.9 <= float(d["r_mm"]) <= 3.8
        ]
        cands.sort(key=lambda d: (float(d["r_mm"]), -float(d["length_mm"])))
        for d in cands[:2]:
            key = _mid_key(d["mid"])
            if key in used:
                continue
            L = float(d["length_mm"])
            # radii: short-edge mild + geom mid
            rs = [0.08, 0.10, 0.12, 0.15, 0.18, 0.20, 0.22, 0.25, 0.30]
            if L >= 1.5:
                rs = [0.15, 0.20, 0.25, 0.30, 0.35]
            for r in rs:
                try:
                    src = BRepBuilderAPI_Copy(bare).Shape()
                    # remap edge on copy
                    c2 = [
                        x
                        for x in find_edges_for_slot(src, slot, params)
                        if _mid_key(x["mid"]) == key
                    ]
                    if not c2:
                        continue
                    trial = _as_single_solid(
                        _try_fillet_per_edge(src, [(c2[0]["edge"], float(r))])
                    )
                    dm = float(ocp_mass(trial)) - m0
                    sp = _bbox_span(trial)
                    if dm < 0.05 or dm > 8.0:
                        continue
                    if max(sp) > 27 or any(sp[k] > span0[k] + 2.5 for k in range(3)):
                        continue
                    # light diag only on accepted +Δm
                    try:
                        _, diag = _fillet_with_diag(
                            BRepBuilderAPI_Copy(bare).Shape(), c2[0]["edge"], r
                        )
                    except Exception as dex:
                        diag = {"note": f"diag_skip:{dex}"}
                    used.add(key)
                    out.append((slot, c2[0], float(r), trial, diag, dm))
                    print(
                        f"  +Δm cand Q={q:g} slot#{slot.slot_id} L={L:.3f} "
                        f"r={r:.3f} dm={dm:+.3f} diag={diag}",
                        flush=True,
                    )
                    break
                except Exception:
                    continue
            if len(out) >= 4:
                return out
    return out


def _try_hard_routes(
    solid: Any,
    *,
    tag: str,
    m0: float,
    out_dir: str,
) -> list[dict[str, Any]]:
    results = []
    max_span = 20.0 * 1.35
    mem_m = float(ocp_mass(solid))
    topo0 = ocp_shape_topology(solid, check_brep=True)
    chk = _brepcheck_report(solid)

    # A: direct hard
    path = os.path.join(out_dir, f"{tag}_direct.step")
    try:
        rb = _write_step_hard_solid(
            solid, path, mass_ref=mem_m, max_drift=1.0, max_span_mm=max_span
        )
        rbm = float(ocp_mass(rb))
        rbt = ocp_shape_topology(rb, check_brep=True)
        ok = (
            (rbm - m0) > 0.05
            and abs(rbm - mem_m) <= 1.0
            and bool(rbt.get("brep_valid"))
            and int(rbt.get("solids") or 0) == 1
        )
        results.append(
            {
                "route": "direct",
                "ok": ok,
                "rb_dm": rbm - m0,
                "rb_valid": bool(rbt.get("brep_valid")),
                "path": path if ok else None,
                "mem_valid": bool(topo0.get("brep_valid")),
                "check": chk,
            }
        )
        print(
            f"    direct {'OK' if ok else 'FAIL'} rb_dm={rbm-m0:+.3f} "
            f"valid={rbt.get('brep_valid')}",
            flush=True,
        )
    except Exception as exc:
        results.append({"route": "direct", "ok": False, "error": str(exc), "check": chk})
        print(f"    direct FAIL {exc}", flush=True)

    # B: gmsh heal write
    path = os.path.join(out_dir, f"{tag}_gmsh.step")
    try:
        ocp_write_step_via_gmsh_brep_heal(solid, path, fast_readback=True)
        rb = ocp_read_step_shape(path)
        rbm = float(ocp_mass(rb))
        rbt = ocp_shape_topology(rb, check_brep=True)
        ok = (
            (rbm - m0) > 0.05
            and abs(rbm - mem_m) <= 1.2
            and bool(rbt.get("brep_valid"))
            and int(rbt.get("solids") or 0) == 1
        )
        results.append(
            {
                "route": "gmsh",
                "ok": ok,
                "rb_dm": rbm - m0,
                "rb_valid": bool(rbt.get("brep_valid")),
                "path": path if ok else None,
            }
        )
        print(
            f"    gmsh {'OK' if ok else 'FAIL'} rb_dm={rbm-m0:+.3f} "
            f"valid={rbt.get('brep_valid')}",
            flush=True,
        )
    except Exception as exc:
        results.append({"route": "gmsh", "ok": False, "error": str(exc)})
        print(f"    gmsh FAIL {exc}", flush=True)

    # C: step_heal_for_cae if available
    try:
        from src.export.step_heal_for_cae import heal_step_for_cae

        raw = os.path.join(out_dir, f"{tag}_preheal.step")
        ocp_write_step(solid, raw)
        heal_dir = os.path.join(out_dir, f"{tag}_caeheal_dir")
        healed_path, rep = heal_step_for_cae(
            raw, heal_dir, basename=f"{tag}_cae", timeout_s=120.0, preset_timeout_s=60.0
        )
        rb = ocp_read_step_shape(healed_path)
        rbm = float(ocp_mass(rb))
        rbt = ocp_shape_topology(rb, check_brep=True)
        ok = (
            (rbm - m0) > 0.05
            and abs(rbm - mem_m) <= 1.5
            and bool(rbt.get("brep_valid"))
            and int(rbt.get("solids") or 0) == 1
        )
        results.append(
            {
                "route": "caeheal",
                "ok": ok,
                "rb_dm": rbm - m0,
                "rb_valid": bool(rbt.get("brep_valid")),
                "path": healed_path if ok else None,
                "heal_rep_keys": list(rep)[:12] if isinstance(rep, dict) else [],
            }
        )
        print(
            f"    caeheal {'OK' if ok else 'FAIL'} rb_dm={rbm-m0:+.3f} "
            f"valid={rbt.get('brep_valid')}",
            flush=True,
        )
    except Exception as exc:
        results.append({"route": "caeheal", "ok": False, "error": str(exc)})
        print(f"    caeheal FAIL {exc}", flush=True)

    return results


def run_q(q: float, out_dir: str) -> dict:
    params = _loose(q)
    fp = ExpFilletParams(
        cell_size_mm=20.0,
        rod_d_mm=2.0,
        amplitude_mm=2.0,
        period_factor=float(q),
        n_segments=32,
    )
    print(f"\n######## BREP-HEAL Q={q:g} ########", flush=True)
    bare, m0, fuse_tag, _ = fuse_pipes_unitcell_bare_ladder(fp)
    span0 = _bbox_span(bare)
    print(f"  bare mass={m0:.3f} fuse={fuse_tag}", flush=True)

    cands = _pick_plusdm_candidates(q, bare, params)
    print(f"  +Δm candidates={len(cands)}", flush=True)

    rows = []
    wins = []
    for i, (slot, info, r, trial, diag, dm) in enumerate(cands):
        topo = ocp_shape_topology(trial, check_brep=True)
        chk = _brepcheck_report(trial)
        print(
            f"\n  cand#{i} slot#{slot.slot_id} r={r} dm={dm:+.3f} "
            f"topo_valid={topo.get('brep_valid')} check={chk}",
            flush=True,
        )
        print(f"    fillet_diag={diag}", flush=True)

        for heal_tag, healed in _heal_ladder(trial, float(m0), span0):
            h_topo = ocp_shape_topology(healed, check_brep=True)
            h_chk = _brepcheck_report(healed)
            h_dm = float(ocp_mass(healed)) - float(m0)
            print(
                f"  heal={heal_tag} dm={h_dm:+.3f} valid={h_topo.get('brep_valid')} "
                f"check_valid={h_chk.get('valid')} faults={h_chk.get('faults')[:4]}",
                flush=True,
            )
            tag = f"heal_q{str(q).replace('.', 'p')}_s{slot.slot_id}_r{str(r).replace('.', 'p')}_{heal_tag}"
            route_rows = _try_hard_routes(
                healed, tag=tag, m0=float(m0), out_dir=out_dir
            )
            row = {
                "Q": q,
                "slot_id": slot.slot_id,
                "r": r,
                "mem_dm0": dm,
                "fillet_diag": diag,
                "heal": heal_tag,
                "heal_dm": h_dm,
                "heal_valid": bool(h_topo.get("brep_valid")),
                "heal_check": h_chk,
                "routes": route_rows,
            }
            rows.append(row)
            for rr in route_rows:
                if rr.get("ok") and rr.get("path"):
                    wins.append({**row, "win_route": rr["route"], "path": rr["path"]})

    return {
        "Q": q,
        "fuse": fuse_tag,
        "mass_bare": float(m0),
        "n_cands": len(cands),
        "rows": rows,
        "wins": wins,
    }


def main() -> int:
    out = os.path.join(default_exp_out_dir(), "_fillet_brep_heal")
    os.makedirs(out, exist_ok=True)
    # Optional: --q 1.5 to run one Q in this process
    qs = [1.0, 1.5]
    if len(sys.argv) >= 2 and sys.argv[1] in ("1", "1.0", "1.5"):
        qs = [float(sys.argv[1])]

    all_wins = []
    reports = []
    for q in qs:
        try:
            rep = run_q(q, out)
        except Exception as exc:
            print(f"Q={q} ABORT {exc}", flush=True)
            rep = {"Q": q, "error": str(exc), "wins": [], "rows": []}
        reports.append(rep)
        all_wins.extend(rep.get("wins") or [])
        print(f"\nQ={q:g} wins={len(rep.get('wins') or [])}", flush=True)

    man = os.path.join(out, "brep_heal_report.json")
    with open(man, "w", encoding="utf-8") as f:
        json.dump({"reports": reports, "wins": all_wins}, f, indent=2)

    for q in qs:
        qw = [w for w in all_wins if abs(float(w["Q"]) - q) < 1e-9]
        if not qw:
            continue
        import shutil

        dest = os.path.join(
            default_exp_out_dir(),
            f"exp_filletHeal_af2q{str(q).replace('.', 'p')}_L20_d2p0_1x1.step",
        )
        shutil.copy2(qw[0]["path"], dest)
        print(f"PROMOTED Q={q} → {dest}", flush=True)

    print(f"manifest={man}", flush=True)
    print(f"total_wins={len(all_wins)}", flush=True)
    return 0 if all_wins else 1


if __name__ == "__main__":
    raise SystemExit(main())
