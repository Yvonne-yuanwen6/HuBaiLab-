"""
Find Q=1.5 MakeFillet that is brep_valid AND STEP mass-stable.

  py -3 scripts/exp_slot_fillet_valid_step_probe.py
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


def _collect(bare, params):
    used: set = set()
    out = []
    for slot in build_slots_for_params(params):
        if _slot_z_group(slot) not in ("bot", "top"):
            continue
        info = _assign_edge_for_slot(
            bare, slot, params, used_mids=used, max_edge_len_mm=2.5
        )
        if info is None:
            continue
        used.add(_mid_key(info["mid"]))
        out.append((slot, info))
    return out


def _step_ok(shape, mem_mass, path, max_drift=0.8):
    ocp_write_step(shape, path)
    rb = ocp_read_step_shape(path)
    topo = ocp_shape_topology(rb, check_brep=True)
    rb_m = float(ocp_mass(rb))
    if int(topo.get("solids") or 0) != 1:
        raise RuntimeError(f"solids={topo.get('solids')}")
    if abs(rb_m - mem_mass) > max_drift:
        raise RuntimeError(f"drift mem={mem_mass:.3f} rb={rb_m:.3f}")
    return rb, rb_m, topo


def main() -> int:
    out_dir = os.path.join(default_exp_out_dir(), "_fillet_valid_probe")
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
    bare, m0, fuse_tag, _ = fuse_pipes_unitcell_bare_ladder(fp)
    span0 = _bbox_span(bare)
    print(f"bare mass={m0:.3f} fuse={fuse_tag} span={span0}", flush=True)
    pairs = _collect(bare, params)
    print(f"edges={len(pairs)}", flush=True)

    wins = []
    # dense single-edge radius sweep
    for slot, info in pairs:
        g = _slot_z_group(slot)
        for r in (
            0.015,
            0.02,
            0.025,
            0.03,
            0.035,
            0.04,
            0.045,
            0.05,
            0.055,
            0.06,
        ):
            tag = f"1e_s{slot.slot_id}_{g}_r{r:.3f}".replace(".", "p")
            try:
                sh = _as_single_solid(
                    _try_fillet_per_edge(bare, [(info["edge"], r)])
                )
            except Exception as exc:
                print(f"  {tag}: fillet fail {exc}", flush=True)
                continue
            m1 = float(ocp_mass(sh))
            dm = m1 - m0
            sp = _bbox_span(sh)
            topo = ocp_shape_topology(sh, check_brep=True)
            valid = bool(topo.get("brep_valid"))
            if max(sp) > 27.0:
                print(f"  {tag}: bbox explode dm={dm:+.3f} valid={valid}", flush=True)
                continue
            print(
                f"  {tag}: dm={dm:+.3f} valid={valid} solids={topo.get('solids')} "
                f"span={tuple(round(x,2) for x in sp)}",
                flush=True,
            )
            if not valid:
                continue
            # require mild +Δm (concave) or tiny change; reject large negative
            if dm < -0.15:
                continue
            path = os.path.join(out_dir, f"{tag}.step")
            try:
                rb, rb_m, rtopo = _step_ok(sh, m1, path, max_drift=0.8)
                print(
                    f"  WIN STEP {tag} dm_rb={rb_m-m0:+.3f} valid={rtopo.get('brep_valid')}",
                    flush=True,
                )
                wins.append({"tag": tag, "dm": dm, "dm_rb": rb_m - m0, "path": path})
            except Exception as exc:
                print(f"  STEP fail {tag}: {exc}", flush=True)
                # try gmsh heal route
                try:
                    gpath = os.path.join(out_dir, f"{tag}_gmsh.step")
                    ocp_write_step_via_gmsh_brep_heal(
                        sh, gpath, heal_mm=0.02, skip_gmsh_heal=False
                    )
                    rb = ocp_read_step_shape(gpath)
                    rb_m = float(ocp_mass(rb))
                    if abs(rb_m - m1) <= 0.8:
                        print(
                            f"  WIN GMSH {tag} dm_rb={rb_m-m0:+.3f}",
                            flush=True,
                        )
                        wins.append(
                            {
                                "tag": tag + "_gmsh",
                                "dm": dm,
                                "dm_rb": rb_m - m0,
                                "path": gpath,
                            }
                        )
                    else:
                        print(
                            f"  GMSH mass fail {tag}: mem={m1:.3f} rb={rb_m:.3f}",
                            flush=True,
                        )
                except Exception as exc2:
                    print(f"  GMSH fail {tag}: {exc2}", flush=True)

    # if any valid singles, try 2-edge combo of best
    if wins:
        print("\ntrying 2-edge from first win edge + another...", flush=True)

    # also try oneshot 2-edge with tiny r that stays valid
    bots = [p for p in pairs if _slot_z_group(p[0]) == "bot"]
    tops = [p for p in pairs if _slot_z_group(p[0]) == "top"]
    if bots and tops:
        for r in (0.02, 0.025, 0.03, 0.035):
            tag = f"2e_r{r:.3f}".replace(".", "p")
            try:
                sh = _as_single_solid(
                    _try_fillet_per_edge(
                        bare,
                        [(bots[0][1]["edge"], r), (tops[0][1]["edge"], r)],
                    )
                )
                m1 = float(ocp_mass(sh))
                dm = m1 - m0
                topo = ocp_shape_topology(sh, check_brep=True)
                sp = _bbox_span(sh)
                print(
                    f"  {tag}: dm={dm:+.3f} valid={topo.get('brep_valid')} "
                    f"span={tuple(round(x,2) for x in sp)}",
                    flush=True,
                )
                if not topo.get("brep_valid") or max(sp) > 27 or dm < -0.15:
                    continue
                path = os.path.join(out_dir, f"{tag}.step")
                rb, rb_m, _ = _step_ok(sh, m1, path, max_drift=0.8)
                print(f"  WIN 2e STEP {tag} dm_rb={rb_m-m0:+.3f}", flush=True)
                wins.append({"tag": tag, "dm": dm, "dm_rb": rb_m - m0, "path": path})
            except Exception as exc:
                print(f"  {tag}: {exc}", flush=True)

    print("\n=== WINS ===", flush=True)
    for w in wins:
        print(f"  {w}", flush=True)
    print(f"n_wins={len(wins)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
