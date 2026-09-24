"""
Sweep centre_extension_mm for Q=1.5; try MakeFillet when junctions open up.

  py -3 scripts/exp_fillet_ext_sweep_probe.py
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
    load_fillet_pipe_parts,
)
from src.export.exp_node_transition.centre_edge_fillet import _try_fillet_timeout
from src.export.exp_node_transition.intersection_edge_fillet import (
    IntersectionFilletParams,
    collect_intersection_edges,
)
from src.export.ocp_paper_box_array_fuse import ocp_read_step_shape
from src.export.ocp_unitcell_fuse import (
    export_q1_ocp_glue_unitcell,
    ocp_mass,
    ocp_shape_topology,
)


def _fuse_with_ext(parts, *, centre_ext: float, corner_ext: float | None = None):
    corner_ext = centre_ext if corner_ext is None else corner_ext
    with tempfile.TemporaryDirectory(prefix="ext_fuse_") as td:
        path = os.path.join(td, "u.step")
        rep = export_q1_ocp_glue_unitcell(
            parts,
            path,
            cell_size_mm=20.0,
            strategy="sequential_glue_shift",
            fuzzy_mm=0.02,
            pipe_mode="both_end_extension",
            centre_extension_mm=float(centre_ext),
            corner_extension_mm=float(corner_ext),
        )
        mass = float(rep.get("merged_mass_mm3") or 0.0)
        if mass <= 0:
            raise RuntimeError("empty fuse")
        shape = ocp_read_step_shape(path)
        return shape, mass, rep


def _try_valid_fillet_step(bare, m0, edge_info, r, out_path, *, timeout_s=15.0):
    work = BRepBuilderAPI_Copy(bare).Shape()
    # rebind edge on copy
    ip = IntersectionFilletParams(period_factor=1.5, select_radius_mm=5.5)
    cands = collect_intersection_edges(work, ip)
    if not cands:
        raise RuntimeError("no cands on copy")
    hit = min(
        cands,
        key=lambda d: abs(d["length_mm"] - float(edge_info["length_mm"]))
        + 0.1 * abs(d["ndot"] - float(edge_info["ndot"])),
    )
    try:
        sh = _try_fillet_timeout(work, hit["edge"], r, timeout_s=timeout_s)
    except Exception:
        sh = _try_fillet_per_edge(work, [(hit["edge"], r)])
    solid = _as_single_solid(sh)
    m1 = float(ocp_mass(solid))
    dm = m1 - m0
    sp = _bbox_span(solid)
    topo = ocp_shape_topology(solid, check_brep=True)
    if not topo.get("brep_valid"):
        raise RuntimeError(f"invalid dm={dm:+.3f}")
    if max(sp) > 27:
        raise RuntimeError(f"bbox {sp}")
    if dm < -0.2 or dm > 5:
        raise RuntimeError(f"dmass {dm:+.3f}")
    rb = _write_step_hard_solid(
        solid, out_path, mass_ref=m1, max_drift=0.8, max_span_mm=27.0
    )
    return rb, float(ocp_mass(rb)) - m0, dm


def main() -> int:
    out = os.path.join(default_exp_out_dir(), "_fillet_ext_sweep")
    os.makedirs(out, exist_ok=True)

    fp = ExpFilletParams(
        cell_size_mm=20.0,
        rod_d_mm=2.0,
        amplitude_mm=2.0,
        period_factor=1.5,
        n_segments=32,
    )
    parts = load_fillet_pipe_parts(fp)
    ip = IntersectionFilletParams(period_factor=1.5, select_radius_mm=5.5)

    # Also compare Q=0.5 reference edge stats
    print("=== Q=0.5 reference edge stats ===", flush=True)
    fp05 = ExpFilletParams(
        cell_size_mm=20.0,
        rod_d_mm=2.0,
        amplitude_mm=2.0,
        period_factor=0.5,
        n_segments=32,
    )
    parts05 = load_fillet_pipe_parts(fp05)
    bare05, m05, _ = _fuse_with_ext(parts05, centre_ext=1.5)
    ip05 = IntersectionFilletParams(period_factor=0.5, select_radius_mm=5.5)
    c05 = collect_intersection_edges(bare05, ip05)
    if c05:
        nd = [c["ndot"] for c in c05]
        ln = [c["length_mm"] for c in c05]
        print(
            f"  n={len(c05)} L=[{min(ln):.2f},{max(ln):.2f}] "
            f"ndot=[{min(nd):.2f},{max(nd):.2f}] mean_ndot={sum(nd)/len(nd):.2f}",
            flush=True,
        )

    wins = []
    ext_list = [0.8, 1.0, 1.2, 1.5, 2.0, 2.5, 3.0, 3.5]
    # also asymmetric: short centre / long corner
    combos = [(e, e) for e in ext_list] + [
        (1.0, 2.5),
        (1.5, 3.0),
        (2.0, 1.0),
        (2.5, 1.5),
    ]

    for cext, kext in combos:
        tag = f"ce{cext}_ke{kext}".replace(".", "p")
        print(f"\n======== ext centre={cext} corner={kext} ========", flush=True)
        try:
            bare, m0, _ = _fuse_with_ext(parts, centre_ext=cext, corner_ext=kext)
        except Exception as exc:
            print(f"  fuse FAIL: {exc}", flush=True)
            continue
        topo0 = ocp_shape_topology(bare, check_brep=True)
        cands = collect_intersection_edges(bare, ip)
        if not cands:
            print(f"  mass={m0:.3f} valid={topo0.get('brep_valid')} n_cand=0", flush=True)
            continue
        nd = [c["ndot"] for c in cands]
        ln = [c["length_mm"] for c in cands]
        print(
            f"  mass={m0:.3f} valid={topo0.get('brep_valid')} n_cand={len(cands)} "
            f"L=[{min(ln):.2f},{max(ln):.2f}] "
            f"ndot=[{min(nd):.2f},{max(nd):.2f}] mean_ndot={sum(nd)/len(nd):.2f}",
            flush=True,
        )

        # Prefer longer edges with moderate ndot (more like Q=0.5)
        ranked = sorted(
            cands,
            key=lambda c: (
                -float(c["length_mm"]),
                abs(float(c["ndot"]) - 0.4),  # Q=0.5 often ~0.2–0.5
            ),
        )
        for ci, info in enumerate(ranked[:4]):
            for r in (0.04, 0.05, 0.06, 0.08, 0.03):
                path = os.path.join(out, f"{tag}_c{ci}_r{r}.step".replace(".", "p"))
                try:
                    rb, dm_rb, dm_mem = _try_valid_fillet_step(
                        bare, m0, info, r, path
                    )
                    print(
                        f"  WIN {tag} c{ci} L={info['length_mm']:.2f} "
                        f"ndot={info['ndot']:.2f} r={r} dm_mem={dm_mem:+.3f} "
                        f"dm_rb={dm_rb:+.3f}",
                        flush=True,
                    )
                    wins.append(
                        {
                            "centre_ext": cext,
                            "corner_ext": kext,
                            "ci": ci,
                            "L": info["length_mm"],
                            "ndot": info["ndot"],
                            "r": r,
                            "dm_mem": dm_mem,
                            "dm_rb": dm_rb,
                            "path": path,
                        }
                    )
                    break
                except Exception as exc:
                    msg = str(exc)
                    if "invalid" in msg or "dmass" in msg or "bbox" in msg:
                        if r == 0.04:
                            print(
                                f"  skip c{ci} L={info['length_mm']:.2f} "
                                f"r={r}: {msg}",
                                flush=True,
                            )
                    else:
                        print(
                            f"  fail c{ci} r={r}: {msg[:120]}",
                            flush=True,
                        )

    print("\n=== ALL WINS ===", flush=True)
    for w in wins:
        print(f"  {w}", flush=True)
    print(f"n_wins={len(wins)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
