"""
Can gmsh BREP→STEP (no heal) preserve Q=1.5 invalid MakeFillet mass?

  py -3 scripts/exp_slot_fillet_gmsh_step_probe.py
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
    _assign_edge_for_slot,
    _bbox_span,
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
from src.export.ocp_unitcell_fuse import (
    ocp_mass,
    ocp_shape_topology,
    ocp_write_step,
    ocp_write_step_via_gmsh_brep_heal,
)


def main() -> int:
    out = os.path.join(default_exp_out_dir(), "_fillet_gmsh_step_probe")
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
    bare, m0, tag, _ = fuse_pipes_unitcell_bare_ladder(fp)
    print(f"bare={m0:.3f} {tag}", flush=True)

    used = set()
    pairs = []
    for slot in build_slots_for_params(params):
        if _slot_z_group(slot) not in ("bot", "top"):
            continue
        info = _assign_edge_for_slot(
            bare, slot, params, used_mids=used, max_edge_len_mm=2.5
        )
        if info:
            used.add(_mid_key(info["mid"]))
            pairs.append((slot, info))

    bots = [p for p in pairs if _slot_z_group(p[0]) == "bot"]
    tops = [p for p in pairs if _slot_z_group(p[0]) == "top"]

    def _safe_dm(edge, r):
        sh = _as_single_solid(_try_fillet_per_edge(bare, [(edge, r)]))
        dm = float(ocp_mass(sh)) - m0
        sp = _bbox_span(sh)
        if max(sp) > 27 or abs(dm) > 5.0:
            return None
        return dm, sh

    # Prefer known-good-ish: bot s1 @0.04 (+Δm), top s6 @0.045
    edge_pairs = None
    b = next((p for p in bots if p[0].slot_id == 1), bots[0] if bots else None)
    t = next((p for p in tops if p[0].slot_id == 6), tops[0] if tops else None)
    if b and t:
        for rb, rt in ((0.04, 0.045), (0.04, 0.04), (0.05, 0.05), (0.035, 0.035)):
            try:
                sh = _as_single_solid(
                    _try_fillet_per_edge(
                        bare, [(b[1]["edge"], rb), (t[1]["edge"], rt)]
                    )
                )
                dm = float(ocp_mass(sh)) - m0
                sp = _bbox_span(sh)
                if max(sp) <= 27 and 0.2 <= dm <= 5.0:
                    edge_pairs = [(b[1]["edge"], rb), (t[1]["edge"], rt)]
                    print(
                        f"combo s{b[0].slot_id}+s{t[0].slot_id} "
                        f"r={rb}/{rt} dm={dm:+.3f}",
                        flush=True,
                    )
                    break
            except Exception as exc:
                print(f"  combo try fail r={rb}/{rt}: {exc}", flush=True)

    if edge_pairs is None:
        print("no combo", flush=True)
        return 1

    sh = _as_single_solid(_try_fillet_per_edge(bare, edge_pairs))
    m1 = float(ocp_mass(sh))
    topo = ocp_shape_topology(sh, check_brep=True)
    print(
        f"mem mass={m1:.3f} dm={m1-m0:+.3f} valid={topo.get('brep_valid')} "
        f"span={_bbox_span(sh)}",
        flush=True,
    )

    routes = []
    # 1 direct OCP
    p1 = os.path.join(out, "direct.step")
    try:
        ocp_write_step(sh, p1)
        rb = ocp_read_step_shape(p1)
        routes.append(("direct", float(ocp_mass(rb)), p1))
    except Exception as exc:
        routes.append(("direct", f"FAIL {exc}", p1))

    # 2 gmsh no heal
    p2 = os.path.join(out, "gmsh_noheal.step")
    try:
        ocp_write_step_via_gmsh_brep_heal(
            sh, p2, heal_mm=0.02, skip_gmsh_heal=True, fast_readback=True
        )
        rb = ocp_read_step_shape(p2)
        routes.append(("gmsh_noheal", float(ocp_mass(rb)), p2))
    except Exception as exc:
        routes.append(("gmsh_noheal", f"FAIL {exc}", p2))

    # 3 gmsh heal tiny
    for heal in (0.01, 0.02, 0.05):
        p = os.path.join(out, f"gmsh_heal_{heal}.step".replace(".", "p"))
        try:
            ocp_write_step_via_gmsh_brep_heal(
                sh, p, heal_mm=heal, skip_gmsh_heal=False, fast_readback=True
            )
            rb = ocp_read_step_shape(p)
            routes.append((f"gmsh_heal_{heal}", float(ocp_mass(rb)), p))
        except Exception as exc:
            routes.append((f"gmsh_heal_{heal}", f"FAIL {exc}", p))

    # 4 Interface_Static precision tweaks + direct write
    try:
        from OCP.Interface import Interface_Static
        from OCP.STEPControl import STEPControl_AsIs, STEPControl_Writer

        for schema, prec in (("AP214IS", 0.0001), ("AP203", 0.0001)):
            Interface_Static.SetCVal_s("write.step.schema", schema)
            Interface_Static.SetRVal_s("write.precision.val", prec)
            Interface_Static.SetIVal_s("write.precision.mode", 1)
            p = os.path.join(out, f"schema_{schema}.step")
            w = STEPControl_Writer()
            w.Transfer(sh, STEPControl_AsIs)
            w.Write(p)
            rb = ocp_read_step_shape(p)
            routes.append((f"schema_{schema}", float(ocp_mass(rb)), p))
    except Exception as exc:
        routes.append(("schema", f"FAIL {exc}", ""))

    print(f"\nmem={m1:.3f} dm={m1-m0:+.3f}", flush=True)
    print("=== routes ===", flush=True)
    for name, mass, path in routes:
        if isinstance(mass, float):
            drift = mass - m1
            ok = abs(drift) <= 0.8
            print(
                f"  {name}: rb={mass:.3f} drift={drift:+.3f} "
                f"{'KEEP' if ok else 'LOST'} dm_vs_bare={mass-m0:+.3f}",
                flush=True,
            )
        else:
            print(f"  {name}: {mass}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
