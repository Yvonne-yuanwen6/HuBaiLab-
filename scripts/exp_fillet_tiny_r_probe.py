"""
Tiny-r MakeFillet on Q=1.5 long intersection edges (timeout-guarded).

  py -3 scripts/exp_fillet_tiny_r_probe.py
"""

from __future__ import annotations

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from OCP.BRepBuilderAPI import BRepBuilderAPI_Copy
from OCP.BRepFilletAPI import BRepFilletAPI_MakeFillet
from OCP.ChFi3d import ChFi3d_FilletShape

from src.export.exp_node_transition.acute_slot_fillet import (
    _as_single_solid,
    _bbox_span,
    _write_step_hard_solid,
)
from src.export.exp_node_transition.bcc_explicit_cores import default_exp_out_dir
from src.export.exp_node_transition.bcc_fillet_blend import (
    ExpFilletParams,
    fuse_pipes_unitcell_bare_ladder,
)
from src.export.exp_node_transition.centre_edge_fillet import _try_fillet_timeout
from src.export.exp_node_transition.intersection_edge_fillet import (
    IntersectionFilletParams,
    collect_intersection_edges,
)
from src.export.ocp_unitcell_fuse import ocp_mass, ocp_shape_topology


def _fillet_modes(shape, edge, r):
    """Yield (tag, shape) for default + QuasiAngular + params tweak."""
    # timeout helper
    try:
        sh = _try_fillet_timeout(shape, edge, r, timeout_s=12.0)
        yield "timeout_default", sh
    except Exception as exc:
        print(f"    timeout_default fail: {exc}", flush=True)

    for mode_name, mode in (
        ("QuasiAngular", ChFi3d_FilletShape.ChFi3d_QuasiAngular),
        ("Rational", ChFi3d_FilletShape.ChFi3d_Rational),
    ):
        try:
            work = BRepBuilderAPI_Copy(shape).Shape()
            # re-find similar edge by collecting again — use same edge on copy won't work
            # instead fillet on original shape copy with edge from collect on that copy
            yield from ()  # filled below
        except Exception:
            pass

    # Direct with SetParams on a fresh copy + rebound edge via mid match
    # (caller passes edge already on `shape`)
    for mode_name, mode in (
        ("QuasiAngular", ChFi3d_FilletShape.ChFi3d_QuasiAngular),
        ("Rational", ChFi3d_FilletShape.ChFi3d_Rational),
    ):
        try:
            mk = BRepFilletAPI_MakeFillet(shape)
            mk.SetFilletShape(mode)
            try:
                # ta, te, t0, t1 angular params (OCC docs)
                mk.SetParams(1e-4, 1e-4, 0.5, 0.2, 1e-3, 1e-3)
            except Exception:
                pass
            mk.Add(float(r), edge)
            mk.Build()
            if not mk.IsDone():
                print(f"    {mode_name} not done", flush=True)
                continue
            yield mode_name, mk.Shape()
        except Exception as exc:
            print(f"    {mode_name} fail: {exc}", flush=True)


def main() -> int:
    out = os.path.join(default_exp_out_dir(), "_fillet_tiny_r_probe")
    os.makedirs(out, exist_ok=True)
    q = 1.5
    fp = ExpFilletParams(
        cell_size_mm=20, rod_d_mm=2, amplitude_mm=2, period_factor=q, n_segments=32
    )
    bare, m0, tag, _ = fuse_pipes_unitcell_bare_ladder(fp)
    print(f"bare={m0:.3f} {tag}", flush=True)
    ip = IntersectionFilletParams(
        period_factor=q, select_radius_mm=5.5, max_edge_len_mm=8.0
    )
    # Prefer longer edges (Q=0.5 style)
    cands = [c for c in collect_intersection_edges(bare, ip) if c["length_mm"] >= 2.0]
    print(f"long cands={len(cands)}", flush=True)
    wins = []

    for ci, info0 in enumerate(cands[:4]):
        for r in (0.012, 0.015, 0.02, 0.025, 0.03):
            work = BRepBuilderAPI_Copy(bare).Shape()
            c2 = collect_intersection_edges(work, ip)
            # match by length
            info = min(c2, key=lambda d: abs(d["length_mm"] - info0["length_mm"]))
            print(
                f"\n-- c{ci} L={info['length_mm']:.2f} r={r} ndot={info['ndot']:.2f} --",
                flush=True,
            )
            for mode, sh in _fillet_modes(work, info["edge"], r):
                try:
                    solid = _as_single_solid(sh)
                except Exception as exc:
                    print(f"  {mode}: not solid {exc}", flush=True)
                    continue
                m1 = float(ocp_mass(solid))
                dm = m1 - m0
                sp = _bbox_span(solid)
                topo = ocp_shape_topology(solid, check_brep=True)
                print(
                    f"  {mode}: dm={dm:+.3f} valid={topo.get('brep_valid')} "
                    f"span_ok={max(sp)<=27}",
                    flush=True,
                )
                if not topo.get("brep_valid") or max(sp) > 27:
                    continue
                if dm < -0.15 or dm > 4:
                    continue
                path = os.path.join(
                    out, f"q15_c{ci}_{mode}_r{r}.step".replace(".", "p")
                )
                try:
                    rb = _write_step_hard_solid(
                        solid,
                        path,
                        mass_ref=m1,
                        max_drift=0.8,
                        max_span_mm=27.0,
                    )
                    print(
                        f"  WIN {mode} r={r} dm_rb={ocp_mass(rb)-m0:+.3f} → {path}",
                        flush=True,
                    )
                    wins.append(
                        {"mode": mode, "r": r, "ci": ci, "path": path, "dm": dm}
                    )
                except Exception as exc:
                    print(f"  STEP fail: {exc}", flush=True)

    print(f"\n=== WINS n={len(wins)} ===", flush=True)
    for w in wins:
        print(f"  {w}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
