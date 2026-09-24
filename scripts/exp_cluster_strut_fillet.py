"""
Same-cluster / full-node G1 intersection fillet on analytic cylinders.

Extends the accepted two-strut tangent fillet: fuse 4 (±Z cluster) or 8
(start-dir) equal-R cylinders, then OCC MakeFillet on the long pipe–pipe
valleys. No hub sphere, no canal.

  py -3 scripts/exp_cluster_strut_fillet.py
  py -3 scripts/exp_cluster_strut_fillet.py --n 8 --rf 0.30
  py -3 scripts/exp_cluster_strut_fillet.py --q 0 --n 4 --rf 0.30
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
from src.export.exp_node_transition.bcc_scheme_b_blend import _cluster_indices
from src.export.exp_node_transition.centre_armpit_blend import _angle_deg, _unit
from src.export.ocp_unitcell_fuse import (
    ocp_fuse_pair,
    ocp_heal_fused_solid,
    ocp_mass,
    ocp_shape_topology,
    ocp_write_step,
)


def _start_dir(path_pts: tuple) -> np.ndarray:
    P = np.asarray(path_pts, dtype=float)
    return _unit(P[1] - P[0])


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
            raise RuntimeError(f"fuse solids={count_solids(acc)} after {i} cylinders")
    return ocp_heal_fused_solid(acc)


def main() -> int:
    p = argparse.ArgumentParser(description="Cluster analytic-cylinder G1 fillet")
    p.add_argument("--q", type=float, default=1.5)
    p.add_argument("--rf", type=float, default=0.30, help="fillet radius mm")
    p.add_argument("--s-end", type=float, default=8.0)
    p.add_argument("--n", type=int, choices=(4, 8), default=4)
    p.add_argument("--cluster", choices=("pos", "neg"), default="pos")
    args = p.parse_args()

    out_dir = os.path.join(
        default_exp_out_dir(), "_hard_cad_delivery", "_cluster_strut_tangent"
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
    if int(args.n) == 8:
        idxs = pos_i + neg_i
        site = "both"
    else:
        idxs = pos_i if args.cluster == "pos" else neg_i
        site = str(args.cluster)

    dirs = [_start_dir(parts[i][1]) for i in idxs]
    pair_angs = [
        round(_angle_deg(dirs[a], dirs[b]), 2)
        for a in range(len(dirs))
        for b in range(a + 1, len(dirs))
        if _angle_deg(dirs[a], dirs[b]) < 90.0
    ]
    r = 0.5 * float(fp.rod_d_mm)
    rf = float(args.rf)
    print(
        f"Q={args.q:g} n={args.n} site={site} idxs={idxs}  "
        f"R={r:g} fillet r={rf:.3f} mm",
        flush=True,
    )
    print(f"  acute pair angles {pair_angs}", flush=True)
    print("  G1 MakeFillet on pipe–pipe valleys — no canal, no sphere", flush=True)

    fused = _fuse_cylinders(dirs, radius=r, length=float(args.s_end))
    mass0 = float(ocp_mass(fused))
    print(
        f"  fused mass={mass0:.3f} topo={ocp_shape_topology(fused, check_brep=True)}",
        flush=True,
    )

    qtag = str(args.q).replace(".", "p")
    rtag = str(args.rf).replace(".", "p")
    slug = f"cluster{args.n}_{site}_q{qtag}_analytic"
    bare_path = os.path.join(out_dir, f"{slug}_bare.step")
    ocp_write_step(fused, bare_path)

    # Skip short far-end nubs (Q=1.5 L≈0.64 at r≈7.8)
    min_len = 2.0 if float(args.q) >= 1.25 else 1.2
    max_r = float(args.s_end) - 1.2
    result, fil_info = apply_tangent_intersection_fillet(
        fused,
        radius_mm=rf,
        mass0=mass0,
        min_edge_len_mm=min_len,
        max_r_mm=max_r,
    )
    print(
        f"  OCC fillet OK dmass={fil_info['dmass_mm3']:+.4f} "
        f"faces={fil_info['topology'].get('faces')}",
        flush=True,
    )

    blend_path = os.path.join(out_dir, f"{slug}_r{rtag}_ixFillet.step")
    ocp_write_step(result, blend_path)
    topo = ocp_shape_topology(result, check_brep=True)
    mass1 = float(ocp_mass(result))

    report: dict[str, Any] = {
        "experiment": "cluster_strut_tangent_intersection_fillet",
        "note": (
            "Analytic cylinders along SFBL start-dirs; Rational MakeFillet on "
            "long pipe–pipe valleys. G1 to both circular faces. No canal/sphere."
        ),
        "Q": float(args.q),
        "n_struts": int(args.n),
        "site": site,
        "idxs": idxs,
        "acute_pair_deg": pair_angs,
        "strut_r_mm": r,
        "fillet_r_mm": rf,
        "min_edge_len_mm": min_len,
        "method": "occ_makefillet_rational",
        "mass_bare_mm3": mass0,
        "mass_blend_mm3": mass1,
        "dmass_mm3": mass1 - mass0,
        "topology": topo,
        "fillet": fil_info,
        "bare_step": os.path.abspath(bare_path),
        "blend_step": os.path.abspath(blend_path),
    }
    man = os.path.join(out_dir, f"{slug}_r{rtag}_summary.json")
    with open(man, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    print(f"\nBare:  {bare_path}", flush=True)
    print(f"Fillet:{blend_path}", flush=True)
    print(f"Wrote {man}", flush=True)
    ok = int(topo.get("solids") or 0) == 1 and bool(topo.get("brep_valid"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
