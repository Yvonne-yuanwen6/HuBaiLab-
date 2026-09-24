"""
Hub fillet then SFBL arm extend (experiment).

1) Analytic-cylinder ±Z clusters → G1 MakeFillet (same as approved 4-strut)
2) Join clusters; AABB-clip hub (no sphere) to drop long start-dir spurs
3) Fuse equal-R SFBL outer arms from arc s0 to path end
4) Periodic box clip → 1×1 STEP

Does not change hard CAD delivery defaults.

  py -3 scripts/exp_hub_fillet_extend.py
  py -3 scripts/exp_hub_fillet_extend.py --rf 0.30 --hub-box 5.5 --arm-s0 3.0
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
    apply_tangent_intersection_fillet,
    count_solids,
    cylinder_along,
)
from src.export.exp_node_transition.bcc_explicit_cores import default_exp_out_dir
from src.export.exp_node_transition.bcc_fillet_blend import (
    ExpFilletParams,
    load_fillet_pipe_parts,
)
from src.export.exp_node_transition.bcc_scheme_b_blend import (
    _cluster_indices,
    _point_at_arc_s,
    _remelt_to_one,
)
from src.export.exp_node_transition.centre_armpit_blend import _unit
from src.export.ocp_unitcell_fuse import (
    _box_from_bounds,
    ocp_clip_to_periodic_cell,
    ocp_common,
    ocp_fuse_pair,
    ocp_heal_fused_solid,
    ocp_mass,
    ocp_pipe_along_points,
    ocp_shape_topology,
    ocp_write_step,
)


def _slice_arc(
    path_pts: tuple,
    s0_mm: float,
    s1_mm: float | None = None,
) -> tuple[tuple[float, float, float], ...]:
    P = np.asarray(path_pts, dtype=float)
    seg = np.linalg.norm(np.diff(P, axis=0), axis=1)
    cum = np.concatenate([[0.0], np.cumsum(seg)])
    total = float(cum[-1])
    a = max(0.0, min(float(s0_mm), total))
    b = total if s1_mm is None else max(a + 0.1, min(float(s1_mm), total))
    pts = [_point_at_arc_s(path_pts, a)]
    for i in range(1, len(P) - 1):
        if a < float(cum[i]) < b:
            pts.append(P[i].copy())
    pts.append(_point_at_arc_s(path_pts, b))
    out: list[tuple[float, float, float]] = []
    for p in pts:
        t = (float(p[0]), float(p[1]), float(p[2]))
        if not out or float(np.linalg.norm(np.asarray(t) - np.asarray(out[-1]))) > 0.05:
            out.append(t)
    if len(out) < 3:
        mid = _point_at_arc_s(path_pts, 0.5 * (a + b))
        out = [out[0], (float(mid[0]), float(mid[1]), float(mid[2])), out[-1]]
    return tuple(out)


def _fuse_cyl_cluster(
    parts: list[tuple[str, tuple, float]],
    idxs: list[int],
    *,
    radius: float,
    length: float,
) -> Any:
    dirs = [
        _unit(
            np.asarray(parts[i][1], dtype=float)[1]
            - np.asarray(parts[i][1], dtype=float)[0]
        )
        for i in idxs
    ]
    acc = cylinder_along(dirs[0], radius=radius, length=length)
    for d in dirs[1:]:
        acc = ocp_fuse_pair(
            acc,
            cylinder_along(d, radius=radius, length=length),
            glue="off",
            fuzzy_mm=0.0,
            label="hub-cyl",
            simplify=False,
        )
        if count_solids(acc) != 1:
            raise RuntimeError(f"cluster fuse solids={count_solids(acc)}")
    return ocp_heal_fused_solid(acc)


def _fillet_cluster(shape: Any, *, radius_mm: float) -> tuple[Any, dict[str, Any]]:
    m0 = float(ocp_mass(shape))
    return apply_tangent_intersection_fillet(
        shape,
        radius_mm=radius_mm,
        mass0=m0,
        min_edge_len_mm=2.0,
        max_r_mm=6.8,
    )


def _fuse_arm(cell: Any, arm: Any, *, label: str) -> Any:
    last: Exception | None = None
    for fz in (0.02, 0.05, 0.08, 0.12):
        try:
            trial = ocp_fuse_pair(
                cell, arm, glue="off", fuzzy_mm=fz, label=label, simplify=False
            )
            if count_solids(trial) > 1:
                trial = _remelt_to_one(trial, fuzzy_mm=max(0.10, fz), label=f"{label}-r")
            if count_solids(trial) != 1:
                raise RuntimeError(f"solids={count_solids(trial)}")
            return trial
        except Exception as exc:  # noqa: BLE001
            last = exc
    raise RuntimeError(f"{label} fuse failed ({last})")


def main() -> int:
    p = argparse.ArgumentParser(description="Hub G1 fillet + SFBL arm extend")
    p.add_argument("--q", type=float, default=1.5)
    p.add_argument("--rf", type=float, default=0.30, help="fillet radius mm")
    p.add_argument("--hub-len", type=float, default=8.0, help="analytic hub cylinder L")
    p.add_argument(
        "--hub-box",
        type=float,
        default=5.5,
        help="AABB half-extent to clip hub (mm); 0 disables",
    )
    p.add_argument("--arm-s0", type=float, default=3.0, help="arm arc start from centre")
    args = p.parse_args()

    out_dir = os.path.join(
        default_exp_out_dir(), "_hard_cad_delivery", "_hub_fillet_extend"
    )
    os.makedirs(out_dir, exist_ok=True)

    fp = ExpFilletParams(
        period_factor=float(args.q),
        n_segments=32,
        amplitude_mm=2.0,
        rod_d_mm=2.0,
        cell_size_mm=20.0,
    )
    parts = load_fillet_pipe_parts(fp)
    pos_i, neg_i = _cluster_indices(parts)
    r = 0.5 * float(fp.rod_d_mm)
    rf = float(args.rf)
    Lhub = float(args.hub_len)
    print(
        f"Q={args.q:g} hubL={Lhub:g} rf={rf:.3f} hub_box=±{args.hub_box:g} "
        f"arm_s0={args.arm_s0:g}",
        flush=True,
    )
    print("  analytic hub fillet → AABB clip → SFBL arms → box cut", flush=True)

    print("  fillet +Z cluster...", flush=True)
    pos_f, pos_info = _fillet_cluster(
        _fuse_cyl_cluster(parts, pos_i, radius=r, length=Lhub), radius_mm=rf
    )
    print("  fillet -Z cluster...", flush=True)
    neg_f, neg_info = _fillet_cluster(
        _fuse_cyl_cluster(parts, neg_i, radius=r, length=Lhub), radius_mm=rf
    )
    hub = ocp_heal_fused_solid(
        ocp_fuse_pair(pos_f, neg_f, glue="off", fuzzy_mm=0.05, label="hub-pn", simplify=False)
    )
    mass_hub0 = float(ocp_mass(hub))
    print(f"  hub joined mass={mass_hub0:.3f}", flush=True)

    hub_box_half = float(args.hub_box)
    if hub_box_half > 1e-9:
        h = hub_box_half
        hub = ocp_heal_fused_solid(
            ocp_common(hub, _box_from_bounds((-h, h, -h, h, -h, h)))
        )
        if count_solids(hub) != 1:
            raise RuntimeError(f"hub clip solids={count_solids(hub)}")
        print(
            f"  hub AABB-clipped mass={ocp_mass(hub):.3f} "
            f"topo={ocp_shape_topology(hub, check_brep=True)}",
            flush=True,
        )

    qtag = str(args.q).replace(".", "p")
    rtag = str(args.rf).replace(".", "p")
    btag = str(args.hub_box).replace(".", "p")
    slug = f"hubExt_af2q{qtag}_rf{rtag}_box{btag}_s{str(args.arm_s0).replace('.', 'p')}"
    hub_step = os.path.join(out_dir, f"{slug}_hub.step")
    ocp_write_step(hub, hub_step)

    print(f"  fuse {len(parts)} SFBL arms from s={args.arm_s0:g}...", flush=True)
    cell = hub
    arm_rows: list[dict[str, Any]] = []
    for i, (_k, pts, _rr) in enumerate(parts):
        path = _slice_arc(pts, float(args.arm_s0))
        arm = ocp_pipe_along_points(path, r)
        cell = _fuse_arm(cell, arm, label=f"arm{i}")
        arm_rows.append({"index": i, "n_pts": len(path), "mass_after": float(ocp_mass(cell))})
        print(f"    arm{i} mass={ocp_mass(cell):.2f}", flush=True)

    cell = ocp_heal_fused_solid(cell)
    cut = ocp_heal_fused_solid(ocp_clip_to_periodic_cell(cell, (0.0, 0.0, 0.0), 20.0))
    topo = ocp_shape_topology(cut, check_brep=True)
    mass = float(ocp_mass(cut))
    if int(topo.get("solids") or 0) != 1 or not topo.get("brep_valid"):
        raise RuntimeError(f"final bad topo={topo}")

    step_path = os.path.join(out_dir, f"{slug}_1x1.step")
    ocp_write_step(cut, step_path)
    man = {
        "experiment": "hub_fillet_extend_sfbl_arms",
        "note": (
            "Near-node: analytic cylinders + Rational MakeFillet (G1), AABB-clipped "
            "(no sphere). Outer arms: true SFBL pipes. Mass above bare SFBL is expected "
            "from the local straight-cylinder hub approximation."
        ),
        "Q": float(args.q),
        "fillet_r_mm": rf,
        "hub_len_mm": Lhub,
        "hub_box_half_mm": hub_box_half,
        "arm_s0_mm": float(args.arm_s0),
        "mass_hub_joined_mm3": mass_hub0,
        "mass_mm3": mass,
        "topology": topo,
        "pos_fillet": pos_info,
        "neg_fillet": neg_info,
        "arms": arm_rows,
        "hub_step": os.path.abspath(hub_step),
        "step_path": os.path.abspath(step_path),
    }
    man_path = os.path.join(out_dir, f"{slug}_1x1_summary.json")
    with open(man_path, "w", encoding="utf-8") as f:
        json.dump(man, f, indent=2)
    print(f"\nHub:  {hub_step}", flush=True)
    print(f"Cell: {step_path}  mass={mass:.3f}", flush=True)
    print(f"Wrote {man_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
