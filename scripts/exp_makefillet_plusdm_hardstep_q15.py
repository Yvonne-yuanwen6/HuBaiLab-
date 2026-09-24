"""Q=1.5: only accept MakeFillet with +Δm AND hard STEP (no chamfer/canal)."""
from __future__ import annotations

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from OCP.BRepBuilderAPI import BRepBuilderAPI_Copy
from OCP.ShapeFix import ShapeFix_Shape

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
from src.export.ocp_paper_box_array_fuse import ocp_read_step_shape
from src.export.ocp_unitcell_fuse import (
    ocp_mass,
    ocp_shape_topology,
    ocp_write_step_via_gmsh_brep_heal,
)


def main() -> int:
    out = os.path.join(default_exp_out_dir(), "_fillet_plusdm_probe")
    os.makedirs(out, exist_ok=True)
    q = 1.5
    params = SlotFilletParams(period_factor=q, r_blend_factor=default_rf_for_q(q))
    fp = ExpFilletParams(
        cell_size_mm=20.0,
        rod_d_mm=2.0,
        amplitude_mm=2.0,
        period_factor=q,
        n_segments=32,
    )
    bare, m0, _, _ = fuse_pipes_unitcell_bare_ladder(fp)
    span0 = _bbox_span(bare)
    print(f"bare mass={m0:.3f} span={tuple(round(x, 2) for x in span0)}", flush=True)

    used: set = set()
    pairs = []
    for s in build_slots_for_params(params):
        if _slot_z_group(s) not in ("bot", "top"):
            continue
        info = _assign_edge_for_slot(
            bare, s, params, used_mids=used, max_edge_len_mm=2.5
        )
        if info is None:
            continue
        used.add(_mid_key(info["mid"]))
        pairs.append((s, info))
    print(f"bot/top edges={len(pairs)}", flush=True)

    wins: list[tuple] = []
    for s, _info in pairs:
        g = _slot_z_group(s)
        for r in (0.025, 0.03, 0.035, 0.04, 0.045, 0.05, 0.055, 0.06):
            tag = f"q15_{g}_s{s.slot_id}_r{str(r).replace('.', 'p')}"
            try:
                src = BRepBuilderAPI_Copy(bare).Shape()
                info2 = _assign_edge_for_slot(
                    src, s, params, used_mids=set(), max_edge_len_mm=2.5
                )
                if info2 is None:
                    continue
                trial = _as_single_solid(
                    _try_fillet_per_edge(src, [(info2["edge"], float(r))])
                )
                m1 = float(ocp_mass(trial))
                dm = m1 - float(m0)
                sp = _bbox_span(trial)
                topo = ocp_shape_topology(trial, check_brep=True)
                if dm < 0.05 or dm > 8.0:
                    print(f"  {tag} skip dm={dm:+.3f}", flush=True)
                    continue
                if not bool(topo.get("brep_valid")):
                    print(f"  {tag} skip mem brep_valid=False dm={dm:+.3f}", flush=True)
                    continue
                if max(sp) > 27.0 or any(
                    sp[k] > float(span0[k]) + 2.5 for k in range(3)
                ):
                    print(f"  {tag} skip bbox {tuple(round(x, 2) for x in sp)}", flush=True)
                    continue
                print(
                    f"  {tag} mem_dm={dm:+.3f} valid={topo.get('brep_valid')}",
                    flush=True,
                )

                # direct hard
                p = os.path.join(out, f"{tag}_direct.step")
                try:
                    rb = _write_step_hard_solid(
                        trial, p, mass_ref=m1, max_drift=0.8, max_span_mm=27.0
                    )
                    rbm = float(ocp_mass(rb))
                    rbt = ocp_shape_topology(rb, check_brep=True)
                    ok = (rbm - float(m0)) > 0.05 and bool(rbt.get("brep_valid"))
                    print(
                        f"    direct {'OK' if ok else 'FAIL'} rb_dm={rbm - m0:+.3f} "
                        f"valid={rbt.get('brep_valid')}",
                        flush=True,
                    )
                    if ok:
                        wins.append((tag, "direct", rbm - m0, p))
                except Exception as exc:
                    print(f"    direct FAIL {exc}", flush=True)

                # ShapeFix then hard
                p = os.path.join(out, f"{tag}_fix.step")
                try:
                    sf = ShapeFix_Shape(trial)
                    sf.Perform()
                    fixed = sf.Shape()
                    fm = float(ocp_mass(fixed))
                    rb = _write_step_hard_solid(
                        fixed, p, mass_ref=fm, max_drift=0.8, max_span_mm=27.0
                    )
                    rbm = float(ocp_mass(rb))
                    rbt = ocp_shape_topology(rb, check_brep=True)
                    ok = (rbm - float(m0)) > 0.05 and bool(rbt.get("brep_valid"))
                    print(
                        f"    fix {'OK' if ok else 'FAIL'} rb_dm={rbm - m0:+.3f} "
                        f"valid={rbt.get('brep_valid')}",
                        flush=True,
                    )
                    if ok:
                        wins.append((tag, "fix", rbm - m0, p))
                except Exception as exc:
                    print(f"    fix FAIL {exc}", flush=True)

                # gmsh heal
                p = os.path.join(out, f"{tag}_gmsh.step")
                try:
                    ocp_write_step_via_gmsh_brep_heal(trial, p, fast_readback=True)
                    rb = ocp_read_step_shape(p)
                    rbm = float(ocp_mass(rb))
                    rbt = ocp_shape_topology(rb, check_brep=True)
                    ok = (
                        abs(rbm - m1) <= 0.8
                        and (rbm - float(m0)) > 0.05
                        and int(rbt.get("solids") or 0) == 1
                        and bool(rbt.get("brep_valid"))
                    )
                    print(
                        f"    gmsh {'OK' if ok else 'FAIL'} rb_dm={rbm - m0:+.3f} "
                        f"valid={rbt.get('brep_valid')}",
                        flush=True,
                    )
                    if ok:
                        wins.append((tag, "gmsh", rbm - m0, p))
                except Exception as exc:
                    print(f"    gmsh FAIL {exc}", flush=True)
            except Exception as exc:
                print(f"  {tag} ERR {exc}", flush=True)

    print("\n=== +dm AND hard STEP AND brep_valid WINS ===", flush=True)
    for w in wins:
        print(w, flush=True)
    print(f"n_wins={len(wins)}", flush=True)
    return 0 if wins else 1


if __name__ == "__main__":
    raise SystemExit(main())
