"""
Mild centre-taper → hard STEP for Q=1 / Q=1.5 (build-time concave fill).
Optionally try MakeFillet on post-taper edges.

  py -3 scripts/exp_mild_taper_fillet_probe.py
"""

from __future__ import annotations

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from OCP.BRepBuilderAPI import BRepBuilderAPI_Copy

from src.export.exp_node_transition.acute_slot_fillet import (
    _as_single_solid,
    _bbox_span,
    _write_step_hard_solid,
)
from src.export.exp_node_transition.bcc_explicit_cores import default_exp_out_dir
from src.export.exp_node_transition.centre_edge_fillet import _try_fillet_timeout
from src.export.exp_node_transition.centre_taper_pipe import (
    CentreTaperParams,
    export_centre_taper_unitcell,
)
from src.export.exp_node_transition.intersection_edge_fillet import (
    IntersectionFilletParams,
    collect_intersection_edges,
)
from src.export.ocp_paper_box_array_fuse import ocp_read_step_shape
from src.export.ocp_unitcell_fuse import ocp_mass, ocp_shape_topology


def main() -> int:
    out = os.path.join(default_exp_out_dir(), "_mild_taper_probe")
    os.makedirs(out, exist_ok=True)
    wins = []

    # (Q, taper_mm, taper_scale)
    configs = [
        (1.5, 2.5, 1.20),
        (1.5, 3.0, 1.30),
        (1.5, 3.5, 1.45),
        (1.0, 2.5, 1.20),
        (1.0, 3.0, 1.30),
        (1.0, 3.5, 1.40),
    ]

    for q, tmm, tsc in configs:
        tag = f"q{q}_t{tmm}_s{tsc}".replace(".", "p")
        print(f"\n======== {tag} ========", flush=True)
        params = CentreTaperParams(
            cell_size_mm=20.0,
            rod_d_mm=2.0,
            amplitude_mm=2.0,
            period_factor=float(q),
            n_segments=32,
            taper_mm=float(tmm),
            taper_scale=float(tsc),
        )
        try:
            man = export_centre_taper_unitcell(
                params, out_dir=out, force=True
            )
        except Exception as exc:
            print(f"  taper export FAIL: {exc}", flush=True)
            continue

        step = man.get("step_path")
        used_bare = man.get("used_bare_fallback")
        mass = man.get("mass_mm3")
        topo = man.get("topology") or {}
        rb = man.get("step_readback") or {}
        print(
            f"  taper STEP fallback={used_bare} mass={mass} "
            f"valid={topo.get('brep_valid')} "
            f"rb_mass={rb.get('mass_mm3')} write={man.get('step_write')}",
            flush=True,
        )
        if used_bare or not step or not os.path.isfile(str(step)):
            continue

        # Hard re-read with our gate
        try:
            shape = ocp_read_step_shape(str(step))
            shape = _as_single_solid(shape)
            m = float(ocp_mass(shape))
            sp = _bbox_span(shape)
            t2 = ocp_shape_topology(shape, check_brep=True)
            if int(t2.get("solids") or 0) != 1 or not t2.get("brep_valid"):
                raise RuntimeError(f"topo {t2}")
            if max(sp) > 27:
                raise RuntimeError(f"bbox {sp}")
            hard = os.path.join(out, f"{tag}_hard.step")
            rb_s = _write_step_hard_solid(
                shape, hard, mass_ref=m, max_drift=1.2, max_span_mm=27.0
            )
            print(
                f"  HARD STEP OK mass={ocp_mass(rb_s):.3f} → {hard}",
                flush=True,
            )
            wins.append(
                {
                    "kind": "taper_only",
                    "tag": tag,
                    "q": q,
                    "taper_mm": tmm,
                    "taper_scale": tsc,
                    "mass": float(ocp_mass(rb_s)),
                    "path": hard,
                }
            )
        except Exception as exc:
            print(f"  hard gate FAIL: {exc}", flush=True)
            continue

        # Optional: tiny MakeFillet on post-taper edges (timeout)
        try:
            ip = IntersectionFilletParams(
                period_factor=float(q), select_radius_mm=5.0
            )
            cands = collect_intersection_edges(shape, ip)
            print(f"  post-taper n_cand={len(cands)}", flush=True)
            for ci, info0 in enumerate(cands[:3]):
                for r in (0.03, 0.04, 0.05):
                    try:
                        work = BRepBuilderAPI_Copy(shape).Shape()
                        c2 = collect_intersection_edges(work, ip)
                        if ci >= len(c2):
                            break
                        sh = _as_single_solid(
                            _try_fillet_timeout(
                                work, c2[ci]["edge"], r, timeout_s=12.0
                            )
                        )
                        topo_f = ocp_shape_topology(sh, check_brep=True)
                        dm = float(ocp_mass(sh)) - m
                        sp = _bbox_span(sh)
                        print(
                            f"  fillet c{ci} r={r}: dm={dm:+.3f} "
                            f"valid={topo_f.get('brep_valid')} "
                            f"span_ok={max(sp)<=27}",
                            flush=True,
                        )
                        if (
                            not topo_f.get("brep_valid")
                            or max(sp) > 27
                            or dm < -0.2
                            or dm > 4
                        ):
                            continue
                        fpath = os.path.join(
                            out, f"{tag}_fillet_c{ci}_r{r}.step".replace(".", "p")
                        )
                        rb_f = _write_step_hard_solid(
                            sh,
                            fpath,
                            mass_ref=float(ocp_mass(sh)),
                            max_drift=0.8,
                            max_span_mm=27.0,
                        )
                        print(
                            f"  WIN taper+fillet → {fpath} "
                            f"mass={ocp_mass(rb_f):.3f}",
                            flush=True,
                        )
                        wins.append(
                            {
                                "kind": "taper_fillet",
                                "tag": tag,
                                "q": q,
                                "r": r,
                                "path": fpath,
                                "mass": float(ocp_mass(rb_f)),
                            }
                        )
                        break
                    except Exception as exc:
                        print(f"  fillet skip c{ci} r={r}: {exc}", flush=True)
        except Exception as exc:
            print(f"  post-taper fillet skip: {exc}", flush=True)

    print("\n=== WINS ===", flush=True)
    for w in wins:
        print(f"  {w}", flush=True)
    print(f"n_wins={len(wins)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
