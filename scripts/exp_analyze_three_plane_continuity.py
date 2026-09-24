"""Feasibility: 3 common planes → 3 continuous hub curves."""
from __future__ import annotations

import os
import sys
from collections import Counter, defaultdict

import numpy as np

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from src.export.exp_node_transition.acute_slot_fillet import (
    SlotFilletParams,
    _slot_z_group,
    build_slots_for_params,
)
from src.export.exp_node_transition.centre_edge_fillet import _edge_faces, _edge_length_mm
from src.export.exp_node_transition.plane_chain_edge_heal import (
    PlaneChainParams,
    _edge_endpoints_mm,
    chain_edges_by_endpoints,
    cluster_hub_edges_by_slot_planes,
    collect_hub_edges,
)
from src.export.ocp_paper_box_array_fuse import ocp_read_step_shape


def _face_id(face) -> int:
    # OCP TopoDS_Shape: use TShape pointer + location as stable-ish key
    try:
        from OCP.TopLoc import TopLoc_Location

        return hash((face.TShape().get(), str(face.Location().Transformation().TranslationPart())))
    except Exception:
        return id(face)


def analyze(q: float, step: str) -> None:
    shape = ocp_read_step_shape(step)
    params = PlaneChainParams(
        period_factor=q,
        hub_r_mm=5.0,
        max_edge_len_mm=3.5,
        gap_tol_mm=0.15,
        max_plane_dist_mm=1.6,
    )
    hub = collect_hub_edges(shape, params)
    cl = cluster_hub_edges_by_slot_planes(shape, params)
    slots = build_slots_for_params(SlotFilletParams(period_factor=q))

    print(f"\n==== Q={q:g} hub_edges={len(hub)} slots={len(slots)} ====")
    print("batch groups present:", sorted({_slot_z_group(s) for s in slots}))

    # Group by shared face-pair (true BRep 'common faces')
    pair_map: dict[tuple[int, int], list] = defaultdict(list)
    for info in hub:
        faces = info.get("faces") or _edge_faces(shape, info["edge"])
        if len(faces) != 2:
            continue
        a, b = _face_id(faces[0]), _face_id(faces[1])
        key = (min(a, b), max(a, b))
        pair_map[key].append(info)
    sizes = sorted((len(v) for v in pair_map.values()), reverse=True)
    print(f"unique face-pairs at hub: {len(pair_map)}  edge-counts/pair top: {sizes[:12]}")

    n_pairs_multi = sum(1 for v in pair_map.values() if len(v) >= 2)
    n_pairs_single = sum(1 for v in pair_map.values() if len(v) == 1)
    print(f"face-pairs with >=2 edge fragments: {n_pairs_multi}; singles: {n_pairs_single}")

    # Within each face-pair, endpoint gaps
    for i, (key, edges) in enumerate(
        sorted(pair_map.items(), key=lambda kv: -len(kv[1]))[:6]
    ):
        chains = chain_edges_by_endpoints(edges, gap_tol_mm=0.15)
        gaps = [round(c["max_gap_mm"], 3) for c in chains]
        print(
            f"  face-pair#{i} n={len(edges)} chains={len(chains)} "
            f"sizes={[c['n_edges'] for c in chains]} max_gaps={gaps}"
        )

    # Plane-group view
    for g in ("bot", "top", "cross"):
        edges = cl["clustered"].get(g) or []
        if not edges:
            print(f"  plane[{g}]: EMPTY")
            continue
        dists = [float(e.get("plane_dist", 0)) for e in edges]
        for gap in (0.05, 0.15, 0.5, 1.05):
            chains = chain_edges_by_endpoints(edges, gap_tol_mm=gap)
            print(
                f"  plane[{g}] gap={gap}: n={len(edges)} chains={len(chains)} "
                f"sizes={[c['n_edges'] for c in chains]} "
                f"plane_dist mean/max={np.mean(dists):.3f}/{np.max(dists):.3f}"
            )


def main() -> None:
    root = os.path.join(
        "output", "cad", "_exp_node_transition", "_hard_cad_delivery"
    )
    analyze(1.0, os.path.join(root, "exp_hardBare_af2q1p0_L20_d2p0_1x1.step"))
    analyze(1.5, os.path.join(root, "exp_hardBare_af2q1p5_L20_d2p0_1x1.step"))


if __name__ == "__main__":
    main()
