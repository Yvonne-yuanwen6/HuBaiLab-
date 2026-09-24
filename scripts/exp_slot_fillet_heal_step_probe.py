"""
Heal + STEP preserve probe for Q=1.5 MakeFillet (opposite pair mem +Δm).

  py -3 scripts/exp_slot_fillet_heal_step_probe.py
"""

from __future__ import annotations

import os
import sys
import tempfile

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from src.export.exp_node_transition.acute_slot_fillet import (
    SlotFilletParams,
    _as_single_solid,
    _assign_edge_for_slot,
    _bbox_span,
    _ensure_written_solid,
    _mid_key,
    _slot_z_group,
    _try_fillet_per_edge,
    build_slots_for_params,
    default_rf_for_q,
)
from src.export.exp_node_transition.bcc_explicit_cores import default_exp_out_dir
from src.export.exp_node_transition.bcc_fillet_blend import (
    ExpFilletParams,
    fuse_pipes_unitcell_bare_ladder,
)
from src.export.ocp_paper_box_array_fuse import ocp_read_step_shape
from src.export.ocp_unitcell_fuse import ocp_mass, ocp_shape_topology, ocp_write_step


def _collect(bare, params):
    slots = build_slots_for_params(params)
    used: set = set()
    pairs = []
    for slot in slots:
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


def _heal_variants(shape):
    """Yield (tag, healed_shape) strategies."""
    yield "raw", shape

    try:
        from OCP.ShapeFix import ShapeFix_Shape

        fx = ShapeFix_Shape(shape)
        fx.Perform()
        yield "ShapeFix_Shape", fx.Shape()
    except Exception as exc:
        print(f"  ShapeFix_Shape skip: {exc}", flush=True)

    try:
        from OCP.ShapeFix import ShapeFix_Solid
        from OCP.TopAbs import TopAbs_SOLID
        from OCP.TopExp import TopExp_Explorer
        from OCP.TopoDS import TopoDS

        exp = TopExp_Explorer(shape, TopAbs_SOLID)
        if exp.More():
            sol = TopoDS.Solid_s(exp.Current())
            fx = ShapeFix_Solid(sol)
            fx.Perform()
            yield "ShapeFix_Solid", fx.Solid()
    except Exception as exc:
        print(f"  ShapeFix_Solid skip: {exc}", flush=True)

    try:
        from OCP.ShapeUpgrade import ShapeUpgrade_UnifySameDomain

        un = ShapeUpgrade_UnifySameDomain(shape, True, True, True)
        un.Build()
        yield "UnifySameDomain", un.Shape()
    except Exception as exc:
        print(f"  Unify skip: {exc}", flush=True)

    try:
        sew = _ensure_written_solid(shape)
        yield "ensure_solid", sew
    except Exception as exc:
        print(f"  ensure skip: {exc}", flush=True)

    try:
        from OCP.BRepBuilderAPI import BRepBuilderAPI_Copy

        yield "copy", BRepBuilderAPI_Copy(shape).Shape()
    except Exception as exc:
        print(f"  copy skip: {exc}", flush=True)

    # ShapeFix then Unify
    try:
        from OCP.ShapeFix import ShapeFix_Shape
        from OCP.ShapeUpgrade import ShapeUpgrade_UnifySameDomain

        fx = ShapeFix_Shape(shape)
        fx.Perform()
        un = ShapeUpgrade_UnifySameDomain(fx.Shape(), True, True, True)
        un.Build()
        yield "fix_then_unify", un.Shape()
    except Exception as exc:
        print(f"  fix+unify skip: {exc}", flush=True)


def _brep_roundtrip(shape):
    from OCP.BRepTools import BRepTools
    from OCP.BRep import BRep_Builder
    from OCP.TopoDS import TopoDS_Shape

    with tempfile.TemporaryDirectory(prefix="brep_rt_") as td:
        p = os.path.join(td, "t.brep")
        BRepTools.Write_s(shape, p)
        builder = BRep_Builder()
        sh = TopoDS_Shape()
        ok = BRepTools.Read_s(sh, p, builder)
        if not ok:
            raise RuntimeError("BREP read failed")
        return sh


def _try_step(path, shape, mem_mass, max_drift=1.2, max_span=27.0):
    ocp_write_step(shape, path)
    try:
        rb = ocp_read_step_shape(path)
    except Exception as exc:
        # soft reopen + ensure, but check vs ORIGINAL mem_mass
        from OCP.IFSelect import IFSelect_RetDone
        from OCP.STEPControl import STEPControl_Reader

        reader = STEPControl_Reader()
        st = reader.ReadFile(os.path.abspath(path))
        if int(st) != int(IFSelect_RetDone):
            raise RuntimeError(f"hard fail + soft reopen fail: {exc}") from exc
        reader.TransferRoots()
        raw = reader.OneShape()
        try:
            rb = _ensure_written_solid(raw)
        except Exception as e2:
            raise RuntimeError(f"0-solid + promote fail: {e2}; first={exc}") from exc
        ocp_write_step(rb, path)
        rb = ocp_read_step_shape(path)
        note = "promoted"
    else:
        note = "direct"

    topo = ocp_shape_topology(rb, check_brep=True)
    rb_mass = float(ocp_mass(rb))
    span = _bbox_span(rb)
    if int(topo.get("solids") or 0) != 1:
        raise RuntimeError(f"solids={topo.get('solids')} note={note}")
    if any(span[k] > max_span for k in range(3)):
        raise RuntimeError(f"bbox {span}")
    drift = abs(rb_mass - float(mem_mass))
    if drift > float(max_drift):
        raise RuntimeError(
            f"MASS LOST mem={mem_mass:.3f} rb={rb_mass:.3f} drift={drift:.3f} note={note}"
        )
    return rb, {
        "note": note,
        "rb_mass": rb_mass,
        "drift": drift,
        "brep_valid": topo.get("brep_valid"),
        "span": span,
    }


def _try_fillet_modes(shape, pairs):
    """Try default + ChFi3d fillet modes."""
    from OCP.BRepFilletAPI import BRepFilletAPI_MakeFillet
    from OCP.ChFi3d import ChFi3d_FilletShape

    modes = [("default", None)]
    for name, enum in (
        ("Rational", "ChFi3d_Rational"),
        ("QuasiAngular", "ChFi3d_QuasiAngular"),
        ("Polynomial", "ChFi3d_Polynomial"),
    ):
        try:
            modes.append((name, getattr(ChFi3d_FilletShape, enum)))
        except Exception:
            pass

    out = []
    for name, mode in modes:
        try:
            mk = BRepFilletAPI_MakeFillet(shape)
            if mode is not None:
                mk.SetFilletShape(mode)
            for edge, r in pairs:
                mk.Add(float(r), edge)
            mk.Build()
            if not mk.IsDone():
                print(f"  fillet mode={name} not done", flush=True)
                continue
            sh = mk.Shape()
            m = float(ocp_mass(sh))
            print(f"  fillet mode={name} mass={m:.3f}", flush=True)
            out.append((name, sh, m))
        except Exception as exc:
            print(f"  fillet mode={name} fail: {exc}", flush=True)
    return out


def main() -> int:
    out_dir = os.path.join(default_exp_out_dir(), "_fillet_heal_probe")
    os.makedirs(out_dir, exist_ok=True)

    q = 1.5
    params = SlotFilletParams(period_factor=q, r_blend_factor=default_rf_for_q(q))
    fp = ExpFilletParams(
        cell_size_mm=20.0,
        rod_d_mm=2.0,
        amplitude_mm=2.0,
        period_factor=q,
        n_segments=32,
    )
    print("=== bare fuse Q=1.5 ===", flush=True)
    bare, m0, tag, _ = fuse_pipes_unitcell_bare_ladder(fp)
    print(f"fuse={tag} mass={m0:.3f}", flush=True)
    pairs = _collect(bare, params)
    bots = [(s, i) for s, i in pairs if _slot_z_group(s) == "bot"]
    tops = [(s, i) for s, i in pairs if _slot_z_group(s) == "top"]
    if not bots or not tops:
        print("no bot/top", flush=True)
        return 1

    # known-ish good combo from prior probe: s1 + s6
    # fall back to first bot/top
    b = next((x for x in bots if x[0].slot_id == 1), bots[0])
    t = next((x for x in tops if x[0].slot_id == 6), tops[0])
    edge_pairs = [(b[1]["edge"], 0.04), (t[1]["edge"], 0.045)]
    print(
        f"edges slot {b[0].slot_id}+{t[0].slot_id} r=0.04/0.045",
        flush=True,
    )

    fillets = _try_fillet_modes(bare, edge_pairs)
    if not fillets:
        # fallback helper
        sh = _try_fillet_per_edge(bare, edge_pairs)
        fillets = [("helper", sh, float(ocp_mass(sh)))]

    wins = []
    for fmode, fshape, fmass in fillets:
        dm = fmass - m0
        print(f"\n## fillet={fmode} mass={fmass:.3f} dm={dm:+.3f}", flush=True)
        if dm < 0.2:
            print("  skip (need +Δm concave fill)", flush=True)
            continue
        span = _bbox_span(fshape)
        if max(span) > 27:
            print(f"  skip bbox {span}", flush=True)
            continue

        # optional BREP roundtrip first
        variants = list(_heal_variants(fshape))
        try:
            br = _brep_roundtrip(fshape)
            variants.append(("brep_rt", br))
        except Exception as exc:
            print(f"  brep_rt skip: {exc}", flush=True)

        for htag, hshape in variants:
            try:
                solid = _as_single_solid(hshape)
            except Exception:
                try:
                    solid = _ensure_written_solid(hshape)
                except Exception as exc:
                    print(f"  {htag}: not solid ({exc})", flush=True)
                    continue
            hm = float(ocp_mass(solid))
            if abs(hm - fmass) > 1.5:
                print(
                    f"  {htag}: heal mass drift f={fmass:.3f} h={hm:.3f}",
                    flush=True,
                )
                continue
            topo = ocp_shape_topology(solid, check_brep=True)
            path = os.path.join(
                out_dir, f"q15_{fmode}_{htag}.step".replace(" ", "_")
            )
            try:
                rb, info = _try_step(path, solid, mem_mass=hm, max_drift=1.2)
                print(
                    f"  WIN {htag} note={info['note']} drift={info['drift']:.3f} "
                    f"valid={info['brep_valid']} dm_rb={info['rb_mass']-m0:+.3f}",
                    flush=True,
                )
                wins.append(
                    {
                        "fillet": fmode,
                        "heal": htag,
                        **info,
                        "path": path,
                        "dm_mem": dm,
                        "dm_rb": info["rb_mass"] - m0,
                    }
                )
            except Exception as exc:
                print(f"  FAIL {htag}: {exc}", flush=True)

    print("\n=== TRUE WINS (mass preserved) ===", flush=True)
    if not wins:
        print("  (none)", flush=True)
    for w in wins:
        print(f"  {w}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
