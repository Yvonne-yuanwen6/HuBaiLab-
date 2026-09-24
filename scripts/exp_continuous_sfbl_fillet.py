"""
Continuous SFBL unitcell with strut–strut intersection fillet (experiment).

Recipe (Q=1.5 proven path):
  1) Fuse ±Z analytic start-dir cylinders (equal R)
  2) OCC Rational MakeFillet on pipe–pipe valleys (approved G1)
  3) Join clusters; fuse SFBL outer arms from arc-s = s_arm (overlap into cyl)
  4) Periodic box clip only — no AABB hub clip, no canal, no sphere

  py -3 scripts/exp_continuous_sfbl_fillet.py
  py -3 scripts/exp_continuous_sfbl_fillet.py --rf 0.30 --s-cyl 5 --s-arm 3
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

import numpy as np

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from src.export.exp_node_transition.analytic_ix_fillet import (
    collect_pipe_intersection_edges,
    count_solids,
    cylinder_along,
    makefillet_rational,
)
from src.export.exp_node_transition.bcc_explicit_cores import default_exp_out_dir
from src.export.exp_node_transition.bcc_fillet_blend import (
    ExpFilletParams,
    load_fillet_pipe_parts,
)
from src.export.exp_node_transition.bcc_scheme_b_blend import (
    _cluster_indices,
    _point_at_arc_s,
)
from src.export.exp_node_transition.centre_armpit_blend import _unit
from src.export.ocp_unitcell_fuse import (
    ocp_clip_to_periodic_cell,
    ocp_fuse_pair,
    ocp_heal_fused_solid,
    ocp_mass,
    ocp_pipe_along_points,
    ocp_shape_topology,
    ocp_write_step,
)


def _start_dir(path_pts: tuple) -> np.ndarray:
    P = np.asarray(path_pts, dtype=float)
    return _unit(P[1] - P[0])


def _sfbl_outer_pts(
    path_pts: tuple,
    *,
    s0: float,
    n_samples: int = 50,
    min_step_mm: float = 0.06,
) -> tuple:
    P = np.asarray(path_pts, dtype=float)
    seg = np.linalg.norm(np.diff(P, axis=0), axis=1)
    cum = np.concatenate([[0.0], np.cumsum(seg)])
    total = float(cum[-1])
    out: list[tuple[float, float, float]] = []
    for s in np.linspace(float(s0), total, int(n_samples)):
        p = _point_at_arc_s(path_pts, float(s))
        t3 = (float(p[0]), float(p[1]), float(p[2]))
        if not out or np.linalg.norm(np.asarray(t3) - np.asarray(out[-1])) > min_step_mm:
            out.append(t3)
    return tuple(out)


def _fuse_cylinders(dirs: list[np.ndarray], *, radius: float, length: float) -> Any:
    acc = cylinder_along(dirs[0], radius=radius, length=length)
    for i, d in enumerate(dirs[1:], start=2):
        acc = ocp_fuse_pair(
            acc,
            cylinder_along(d, radius=radius, length=length),
            glue="off",
            fuzzy_mm=0.0,
            label=f"cluster-{i}",
            simplify=False,
        )
        if count_solids(acc) != 1:
            raise RuntimeError(f"fuse solids={count_solids(acc)} after {i}")
    return ocp_heal_fused_solid(acc)


def _fillet_valleys(
    shape: Any,
    *,
    rf: float,
    mass0: float,
    min_edge_len_mm: float,
    max_r_mm: float,
    ndot_max: float,
) -> tuple[Any, dict[str, Any]]:
    cands = collect_pipe_intersection_edges(
        shape,
        min_edge_len_mm=float(min_edge_len_mm),
        max_r_mm=float(max_r_mm),
        ndot_max=float(ndot_max),
    )
    print(
        "  cands "
        + ", ".join(
            f"L={c['length_mm']:.2f}/ndot={c['ndot']:.3f}/r={c['r_mm']:.2f}"
            for c in cands
        ),
        flush=True,
    )
    if not cands:
        raise RuntimeError("no pipe–pipe intersection edge")

    try:
        trial = makefillet_rational(shape, [c["edge"] for c in cands], float(rf))
        if count_solids(trial) == 1:
            m1 = float(ocp_mass(trial))
            topo = ocp_shape_topology(trial, check_brep=True)
            if bool(topo.get("brep_valid")) and m1 >= 0.95 * mass0:
                print(
                    f"  oneshot OK n={len(cands)} dmass={m1 - mass0:+.4f}",
                    flush=True,
                )
                return trial, {
                    "mode": "oneshot",
                    "n_edges": len(cands),
                    "dmass_mm3": m1 - mass0,
                    "topology": topo,
                }
    except Exception as exc:
        print(f"  oneshot fail: {exc}; sequential...", flush=True)

    cur = shape
    applied = 0
    last = float(mass0)
    for _ in range(20):
        cs = collect_pipe_intersection_edges(
            cur,
            min_edge_len_mm=float(min_edge_len_mm),
            max_r_mm=float(max_r_mm),
            ndot_max=float(ndot_max),
        )
        if not cs:
            break
        got = False
        for c in cs:
            try:
                trial = makefillet_rational(cur, [c["edge"]], float(rf))
                m1 = float(ocp_mass(trial))
                topo = ocp_shape_topology(trial, check_brep=True)
                if (
                    count_solids(trial) == 1
                    and bool(topo.get("brep_valid"))
                    and m1 >= 0.95 * mass0
                    and m1 >= last - 0.05
                ):
                    cur = trial
                    last = m1
                    applied += 1
                    got = True
                    print(
                        f"  + L={c['length_mm']:.2f} ndot={c['ndot']:.3f} "
                        f"dmass={m1 - mass0:+.4f}",
                        flush=True,
                    )
                    break
            except Exception:
                continue
        if not got:
            break
    if applied <= 0:
        raise RuntimeError("no safe fillet applied")
    return cur, {
        "mode": "sequential",
        "n_edges": applied,
        "dmass_mm3": last - mass0,
        "topology": ocp_shape_topology(cur, check_brep=True),
    }


def _fuse_arm(seed: Any, arm: Any, *, label: str, mass_floor: float) -> Any:
    last: Exception | None = None
    for glue in ("off", "shift"):
        for fz in (0.0, 0.02, 0.05, 0.08):
            try:
                trial = ocp_fuse_pair(
                    seed,
                    arm,
                    glue=glue,
                    fuzzy_mm=float(fz),
                    label=label,
                    simplify=False,
                )
                m = float(ocp_mass(trial))
                if count_solids(trial) != 1:
                    raise RuntimeError(f"solids={count_solids(trial)}")
                if m < float(mass_floor) - 0.5:
                    raise RuntimeError(f"mass collapse {m:.3f}")
                print(f"  {label} glue={glue} fz={fz:g} mass={m:.2f}", flush=True)
                return ocp_heal_fused_solid(trial)
            except Exception as exc:
                last = exc
    raise RuntimeError(f"{label} fuse failed: {last}")


def main() -> int:
    p = argparse.ArgumentParser(description="Continuous SFBL + cluster ix fillet")
    p.add_argument("--q", type=float, default=1.5)
    p.add_argument("--rf", type=float, default=0.30)
    p.add_argument("--s-cyl", type=float, default=5.0, help="analytic cylinder length")
    p.add_argument("--s-arm", type=float, default=3.0, help="SFBL arm start arc-s")
    p.add_argument("--cell", type=float, default=20.0)
    p.add_argument("--rod-d", type=float, default=2.0)
    p.add_argument("--af", type=float, default=2.0)
    p.add_argument("--ndot-max", type=float, default=0.95)
    p.add_argument("--min-edge", type=float, default=1.5)
    args = p.parse_args()

    out_dir = os.path.join(
        default_exp_out_dir(), "_hard_cad_delivery", "_continuous_sfbl_fillet"
    )
    os.makedirs(out_dir, exist_ok=True)

    fp = ExpFilletParams(
        period_factor=float(args.q),
        n_segments=32,
        amplitude_mm=float(args.af),
        rod_d_mm=float(args.rod_d),
        cell_size_mm=float(args.cell),
    )
    parts = load_fillet_pipe_parts(fp)
    pos_i, neg_i = _cluster_indices(parts)
    R = 0.5 * float(fp.rod_d_mm)
    s_cyl = float(args.s_cyl)
    s_arm = float(args.s_arm)
    rf = float(args.rf)

    print(
        f"Q={args.q:g} filletThenArm: cyl L={s_cyl:g}, SFBL from s={s_arm:g}, "
        f"R={R:g} rf={rf:.3f} (no AABB hub clip)",
        flush=True,
    )

    dirs = [_start_dir(pts) for _, pts, _ in parts]
    max_r = max(1.0, s_cyl - 0.5)

    pos_h = _fuse_cylinders([dirs[i] for i in pos_i], radius=R, length=s_cyl)
    neg_h = _fuse_cylinders([dirs[i] for i in neg_i], radius=R, length=s_cyl)
    print(f"  pos mass={ocp_mass(pos_h):.3f}  neg mass={ocp_mass(neg_h):.3f}", flush=True)

    pos_f, pos_info = _fillet_valleys(
        pos_h,
        rf=rf,
        mass0=float(ocp_mass(pos_h)),
        min_edge_len_mm=float(args.min_edge),
        max_r_mm=max_r,
        ndot_max=float(args.ndot_max),
    )
    neg_f, neg_info = _fillet_valleys(
        neg_h,
        rf=rf,
        mass0=float(ocp_mass(neg_h)),
        min_edge_len_mm=float(args.min_edge),
        max_r_mm=max_r,
        ndot_max=float(args.ndot_max),
    )

    hub = None
    last: Exception | None = None
    for glue in ("off", "shift"):
        for fz in (0.0, 0.02, 0.05):
            try:
                trial = ocp_fuse_pair(
                    pos_f,
                    neg_f,
                    glue=glue,
                    fuzzy_mm=float(fz),
                    label="pn",
                    simplify=False,
                )
                m = float(ocp_mass(trial))
                if count_solids(trial) == 1 and m > 20.0:
                    hub = ocp_heal_fused_solid(trial)
                    print(f"  join glue={glue} fz={fz:g} mass={m:.2f}", flush=True)
                    break
            except Exception as exc:
                last = exc
        if hub is not None:
            break
    if hub is None:
        raise RuntimeError(f"cluster join failed: {last}")

    cur = hub
    m_floor = float(ocp_mass(cur))
    for i, (_, pts, rad) in enumerate(parts):
        arm = ocp_pipe_along_points(_sfbl_outer_pts(pts, s0=s_arm), float(rad))
        cur = _fuse_arm(cur, arm, label=f"arm{i}", mass_floor=m_floor)
        m_floor = float(ocp_mass(cur))

    cell = ocp_heal_fused_solid(
        ocp_clip_to_periodic_cell(cur, (0.0, 0.0, 0.0), float(args.cell))
    )
    m1 = float(ocp_mass(cell))
    topo1 = ocp_shape_topology(cell, check_brep=True)
    print(f"CELL mass={m1:.3f} topo={topo1}", flush=True)

    qtag = str(args.q).replace(".", "p")
    rtag = str(rf).replace(".", "p")
    cyltag = str(s_cyl).replace(".", "p")
    armtag = str(s_arm).replace(".", "p")
    slug = (
        f"contSFBL_af{int(round(args.af))}q{qtag}"
        f"_filletThenArm_cyl{cyltag}_arm{armtag}_rf{rtag}_1x1"
    )
    step_path = os.path.join(out_dir, f"{slug}.step")
    hub_path = os.path.join(out_dir, f"{slug}_hub.step")
    ocp_write_step(cell, step_path)
    ocp_write_step(hub, hub_path)

    man = {
        "experiment": "cluster_fillet_then_sfbl_arms",
        "note": (
            "±Z analytic cylinders → MakeFillet valleys → join → SFBL arms "
            "from s_arm with overlap. Periodic box only. No AABB hub clip / "
            "canal / sphere."
        ),
        "Q": float(args.q),
        "fillet_r_mm": rf,
        "s_cyl": s_cyl,
        "s_arm": s_arm,
        "ndot_max": float(args.ndot_max),
        "mass_mm3": m1,
        "topology": topo1,
        "pos_fillet": pos_info,
        "neg_fillet": neg_info,
        "hub_step": os.path.abspath(hub_path),
        "step_path": os.path.abspath(step_path),
    }
    man_path = os.path.join(out_dir, f"{slug}_summary.json")
    with open(man_path, "w", encoding="utf-8") as f:
        json.dump(man, f, indent=2)

    print(f"\nHub:   {hub_path}", flush=True)
    print(f"Cell:  {step_path}", flush=True)
    print(f"Wrote {man_path}", flush=True)
    ok = int(topo1.get("solids") or 0) == 1 and bool(topo1.get("brep_valid"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
