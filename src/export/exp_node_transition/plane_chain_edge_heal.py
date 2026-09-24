"""
Plane-chain hub edge heal (experiment isolation).

Idea: Q>=1 bare fuse fragments crotch loops into short edges. Group hub edges
onto AcuteSlot bot/top/cross pair-planes, chain by endpoint proximity, then
UnifySameDomain / FuseEdges / planar BSpline reconnect under hard STEP gates.

Does not deliver mesh, faceted STEP, or chamfer-as-fillet.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np

from src.export.exp_node_transition.acute_slot_fillet import (
    AcuteSlot,
    SlotFilletParams,
    _fillet_batches_for_slots,
    _q_slug,
    _slot_z_group,
    build_slots_for_params,
)
from src.export.exp_node_transition.bcc_explicit_cores import default_exp_out_dir
from src.export.exp_node_transition.bcc_fillet_blend import _edge_midpoint_mm
from src.export.exp_node_transition.centre_edge_fillet import (
    _bbox_span,
    _edge_faces,
    _edge_length_mm,
    _unit,
)
from src.export.exp_node_transition.intersection_edge_fillet import (
    _dihedral_normals,
)
from src.export.ocp_paper_box_array_fuse import ocp_read_step_shape
from src.export.ocp_unitcell_fuse import (
    ocp_heal_fused_solid,
    ocp_mass,
    ocp_shape_topology,
    ocp_write_step,
)


@dataclass
class PlaneChainParams:
    cell_size_mm: float = 20.0
    rod_d_mm: float = 2.0
    amplitude_mm: float = 2.0
    period_factor: float = 1.0
    n_segments: int = 32
    hub_r_mm: float = 5.0
    min_edge_len_mm: float = 0.12
    max_edge_len_mm: float = 3.5
    max_plane_dist_mm: float = 1.60
    gap_tol_mm: float = 0.12
    max_mass_drift_mm3: float = 1.5
    max_span_factor: float = 1.35


PLANE_GROUPS = ("bot", "top", "cross")


def _edge_endpoints_mm(edge: Any) -> tuple[np.ndarray, np.ndarray] | None:
    from OCP.BRep import BRep_Tool
    from OCP.TopExp import TopExp
    from OCP.TopoDS import TopoDS

    try:
        v0 = TopExp.FirstVertex_s(edge)
        v1 = TopExp.LastVertex_s(edge)
        p0 = BRep_Tool.Pnt_s(v0)
        p1 = BRep_Tool.Pnt_s(v1)
        a = np.array([float(p0.X()), float(p0.Y()), float(p0.Z())], dtype=float)
        b = np.array([float(p1.X()), float(p1.Y()), float(p1.Z())], dtype=float)
        return a, b
    except Exception:
        return None


def _point_to_ray_dist(p: np.ndarray, ray_dir: np.ndarray) -> float:
    t = float(np.dot(p, ray_dir))
    if t < 0.0:
        return float(np.linalg.norm(p))
    return float(np.linalg.norm(p - t * ray_dir))


def _is_hub_candidate(
    shape: Any,
    edge: Any,
    *,
    hub_r_mm: float,
    min_len: float,
    max_len: float,
) -> dict[str, Any] | None:
    mid = _edge_midpoint_mm(edge)
    if mid is None:
        return None
    rr = float(np.linalg.norm(mid))
    if rr > float(hub_r_mm) or rr < 0.35:
        return None
    elen = float(_edge_length_mm(edge))
    if elen < float(min_len) or elen > float(max_len):
        return None
    faces = _edge_faces(shape, edge)
    if len(faces) != 2:
        return None
    dih = _dihedral_normals(shape, edge)
    ndot = float(dih[2]) if dih is not None else 1.0
    # Keep moderate+acute junctions; drop near-parallel face pairs
    if ndot > 0.92:
        return None
    ends = _edge_endpoints_mm(edge)
    if ends is None:
        return None
    return {
        "edge": edge,
        "mid": mid,
        "length_mm": elen,
        "r_mm": rr,
        "ndot": ndot,
        "p0": ends[0],
        "p1": ends[1],
        "faces": faces,
    }


def collect_hub_edges(
    shape: Any,
    params: PlaneChainParams,
) -> list[dict[str, Any]]:
    from OCP.TopAbs import TopAbs_EDGE
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS

    seen: set[tuple[float, float, float]] = set()
    out: list[dict[str, Any]] = []
    exp = TopExp_Explorer(shape, TopAbs_EDGE)
    while exp.More():
        edge = TopoDS.Edge_s(exp.Current())
        exp.Next()
        info = _is_hub_candidate(
            shape,
            edge,
            hub_r_mm=params.hub_r_mm,
            min_len=params.min_edge_len_mm,
            max_len=params.max_edge_len_mm,
        )
        if info is None:
            continue
        mid = info["mid"]
        key = (
            round(float(mid[0]), 4),
            round(float(mid[1]), 4),
            round(float(mid[2]), 4),
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(info)
    return out


def cluster_hub_edges_by_slot_planes(
    shape: Any,
    params: PlaneChainParams,
) -> dict[str, Any]:
    """
    Assign each hub edge to the best AcuteSlot (plane_n + bisector), then
    bucket into bot/top/cross. Avoids collapsing groups that share a mean normal.
    """
    slot_params = SlotFilletParams(
        cell_size_mm=params.cell_size_mm,
        rod_d_mm=params.rod_d_mm,
        amplitude_mm=params.amplitude_mm,
        period_factor=params.period_factor,
        n_segments=params.n_segments,
        max_plane_dist_mm=params.max_plane_dist_mm,
        min_edge_len_mm=params.min_edge_len_mm,
        max_edge_len_mm=params.max_edge_len_mm,
        r_band_min_mm=0.35,
        r_band_max_mm=params.hub_r_mm,
        max_ray_dist_mm=2.0,
    )
    slots = build_slots_for_params(slot_params)
    batches = _fillet_batches_for_slots(slots, float(params.period_factor))
    group_names = [_slot_z_group(b[0]) for b in batches if b]

    hub = collect_hub_edges(shape, params)
    clustered: dict[str, list[dict[str, Any]]] = {g: [] for g in PLANE_GROUPS}
    unassigned: list[dict[str, Any]] = []
    plane_ns: dict[str, list[list[float]]] = {g: [] for g in PLANE_GROUPS}

    for info in hub:
        mid = np.asarray(info["mid"], dtype=float)
        best: tuple[float, AcuteSlot, float, float] | None = None
        for slot in slots:
            plane_d = abs(float(np.dot(mid, slot.plane_n)))
            if plane_d > float(params.max_plane_dist_mm):
                continue
            ray_d = _point_to_ray_dist(mid, slot.bisector)
            if ray_d > 2.2:
                continue
            score = plane_d + 0.75 * ray_d
            if best is None or score < best[0]:
                best = (score, slot, plane_d, ray_d)
        if best is None:
            unassigned.append(
                {
                    "length_mm": info["length_mm"],
                    "r_mm": info["r_mm"],
                    "mid": [float(x) for x in mid],
                }
            )
            continue
        _score, slot, plane_d, ray_d = best
        g = _slot_z_group(slot)
        n = [float(x) for x in np.asarray(slot.plane_n, dtype=float)]
        plane_ns[g].append(n)
        clustered[g].append(
            {
                **info,
                "plane_group": g,
                "slot_id": int(slot.slot_id),
                "plane_dist": float(plane_d),
                "ray_dist": float(ray_d),
                "plane_n": n,
            }
        )

    # Representative normal per group (first slot in group)
    rep_n: dict[str, list[float]] = {}
    for s in slots:
        g = _slot_z_group(s)
        if g not in rep_n:
            rep_n[g] = [float(x) for x in np.asarray(s.plane_n, dtype=float)]

    return {
        "slots_n": len(slots),
        "batch_groups": group_names,
        "plane_normals": rep_n,
        "n_hub_edges": len(hub),
        "clustered": clustered,
        "unassigned": unassigned,
        "n_unassigned": len(unassigned),
    }


def chain_edges_by_endpoints(
    edges: list[dict[str, Any]],
    *,
    gap_tol_mm: float,
) -> list[dict[str, Any]]:
    """
    Union-find / graph chain: connect edges if any endpoints within gap_tol.
    Returns ordered chains with gap stats (edge objects kept).
    """
    n = len(edges)
    if n == 0:
        return []

    # Build endpoint list: 2n points
    pts: list[np.ndarray] = []
    edge_of: list[int] = []
    for i, e in enumerate(edges):
        pts.append(np.asarray(e["p0"], dtype=float))
        pts.append(np.asarray(e["p1"], dtype=float))
        edge_of.extend([i, i])

    adj: list[set[int]] = [set() for _ in range(n)]
    gaps: list[float] = []
    for a in range(len(pts)):
        for b in range(a + 1, len(pts)):
            ia, ib = edge_of[a], edge_of[b]
            if ia == ib:
                continue
            d = float(np.linalg.norm(pts[a] - pts[b]))
            if d <= float(gap_tol_mm):
                adj[ia].add(ib)
                adj[ib].add(ia)
                gaps.append(d)

    visited = [False] * n
    chains: list[dict[str, Any]] = []
    for i in range(n):
        if visited[i]:
            continue
        stack = [i]
        visited[i] = True
        members: list[int] = []
        while stack:
            u = stack.pop()
            members.append(u)
            for v in adj[u]:
                if not visited[v]:
                    visited[v] = True
                    stack.append(v)
        # Order along chain by greedy nearest-neighbour from an endpoint degree-1
        deg = {m: len(adj[m] & set(members)) for m in members}
        starts = [m for m in members if deg[m] <= 1]
        start = starts[0] if starts else members[0]
        ordered = [start]
        used = {start}
        while len(ordered) < len(members):
            cur = ordered[-1]
            nbrs = [v for v in adj[cur] if v in members and v not in used]
            if not nbrs:
                # disconnected leftover in component (shouldn't happen)
                rest = [m for m in members if m not in used]
                if not rest:
                    break
                ordered.append(rest[0])
                used.add(rest[0])
                continue
            # pick geometrically nearest endpoint link
            def _link_dist(v: int) -> float:
                best = 1e9
                for pa in (edges[cur]["p0"], edges[cur]["p1"]):
                    for pb in (edges[v]["p0"], edges[v]["p1"]):
                        best = min(best, float(np.linalg.norm(pa - pb)))
                return best

            nbrs.sort(key=_link_dist)
            ordered.append(nbrs[0])
            used.add(nbrs[0])

        segs = [edges[j] for j in ordered]
        total_len = float(sum(float(s["length_mm"]) for s in segs))
        # max internal gap along ordered chain
        max_gap = 0.0
        for a, b in zip(segs, segs[1:]):
            best = 1e9
            for pa in (a["p0"], a["p1"]):
                for pb in (b["p0"], b["p1"]):
                    best = min(best, float(np.linalg.norm(pa - pb)))
            max_gap = max(max_gap, best)
        # closed if first/last endpoints close
        closed = False
        if len(segs) >= 3:
            best = 1e9
            for pa in (segs[0]["p0"], segs[0]["p1"]):
                for pb in (segs[-1]["p0"], segs[-1]["p1"]):
                    best = min(best, float(np.linalg.norm(pa - pb)))
            closed = best <= float(gap_tol_mm)

        chains.append(
            {
                "n_edges": len(segs),
                "total_length_mm": total_len,
                "max_gap_mm": float(max_gap),
                "closed": bool(closed),
                "edges": segs,
                "mids": [[float(x) for x in s["mid"]] for s in segs],
                "lengths_mm": [float(s["length_mm"]) for s in segs],
            }
        )

    chains.sort(key=lambda c: (-int(c["n_edges"]), -float(c["total_length_mm"])))
    return chains


def diagnose_plane_chains(
    shape: Any,
    params: PlaneChainParams,
) -> dict[str, Any]:
    clustered = cluster_hub_edges_by_slot_planes(shape, params)
    group_reports: dict[str, Any] = {}
    multi_groups = 0
    for g in PLANE_GROUPS:
        edges = clustered["clustered"].get(g) or []
        # strip heavy OCC objects for chaining copy
        light = edges
        chains = chain_edges_by_endpoints(light, gap_tol_mm=params.gap_tol_mm)
        n_multi = sum(1 for c in chains if int(c["n_edges"]) >= 2)
        mean_n = (
            float(np.mean([c["n_edges"] for c in chains])) if chains else 0.0
        )
        if mean_n >= 2.0 - 1e-9 and chains:
            multi_groups += 1
        elif n_multi >= 1:
            # count group if at least one multi-edge chain
            multi_groups += 1
        group_reports[g] = {
            "n_edges": len(edges),
            "n_chains": len(chains),
            "n_multi_chains": n_multi,
            "mean_edges_per_chain": mean_n,
            "chains": [
                {
                    "n_edges": c["n_edges"],
                    "total_length_mm": c["total_length_mm"],
                    "max_gap_mm": c["max_gap_mm"],
                    "closed": c["closed"],
                    "lengths_mm": c["lengths_mm"],
                    "mids": c["mids"],
                }
                for c in chains
            ],
        }

    return {
        "params": asdict(params),
        "slots_n": clustered["slots_n"],
        "batch_groups": clustered["batch_groups"],
        "plane_normals": clustered["plane_normals"],
        "n_hub_edges": clustered["n_hub_edges"],
        "n_unassigned": clustered["n_unassigned"],
        "unassigned": clustered["unassigned"],
        "groups": group_reports,
        "n_groups_with_multi_chain": multi_groups,
        "hypothesis_ok": multi_groups >= 2,
    }


def _try_fuse_edges(shape: Any) -> Any:
    try:
        from OCP.BRepLib import BRepLib_FuseEdges
    except Exception:
        return shape
    try:
        fuse = BRepLib_FuseEdges(shape)
        if hasattr(fuse, "SetConcatBSpl"):
            fuse.SetConcatBSpl(True)
        if hasattr(fuse, "Perform"):
            fuse.Perform()
        return fuse.Shape()
    except Exception:
        return shape


def _sample_edge_points(edge: Any, n: int = 8) -> list[np.ndarray]:
    from OCP.BRepAdaptor import BRepAdaptor_Curve

    ad = BRepAdaptor_Curve(edge)
    u0 = float(ad.FirstParameter())
    u1 = float(ad.LastParameter())
    pts = []
    for i in range(n):
        t = u0 + (u1 - u0) * (i / max(n - 1, 1))
        p = ad.Value(t)
        pts.append(np.array([float(p.X()), float(p.Y()), float(p.Z())], dtype=float))
    return pts


def _project_to_plane(p: np.ndarray, n: np.ndarray) -> np.ndarray:
    n = _unit(n)
    return p - float(np.dot(p, n)) * n


def _try_rebuild_chain_wire(
    chain: dict[str, Any],
    plane_n: np.ndarray,
) -> Any | None:
    """Build a single BSpline edge from planar-projected chain samples."""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge
    from OCP.GeomAPI import GeomAPI_PointsToBSpline
    from OCP.TColgp import TColgp_Array1OfPnt
    from OCP.gp import gp_Pnt

    samples: list[np.ndarray] = []
    for seg in chain["edges"]:
        samples.extend(_sample_edge_points(seg["edge"], n=6))
    if len(samples) < 4:
        return None
    cleaned: list[np.ndarray] = []
    for p in samples:
        q = _project_to_plane(p, plane_n)
        if cleaned and float(np.linalg.norm(q - cleaned[-1])) < 1e-4:
            continue
        cleaned.append(q)
    if len(cleaned) < 4:
        return None
    arr = TColgp_Array1OfPnt(1, len(cleaned))
    for i, p in enumerate(cleaned, start=1):
        arr.SetValue(i, gp_Pnt(float(p[0]), float(p[1]), float(p[2])))
    try:
        builder = GeomAPI_PointsToBSpline(arr)
        if hasattr(builder, "IsDone") and not builder.IsDone():
            return None
        curve = builder.Curve()
        mk = BRepBuilderAPI_MakeEdge(curve)
        if not mk.IsDone():
            return None
        return mk.Edge()
    except Exception:
        return None


def _count_hub_edges(shape: Any, params: PlaneChainParams) -> int:
    return len(collect_hub_edges(shape, params))


def _try_unify_edges_only(shape: Any) -> Any:
    """Unify continuous edges without aggressive face merge."""
    from OCP.ShapeFix import ShapeFix_Shape
    from OCP.ShapeUpgrade import ShapeUpgrade_UnifySameDomain

    # UnifyEdges=True, UnifyFaces=False, ConcatBSplines=True
    unified = ShapeUpgrade_UnifySameDomain(shape, True, False, True)
    unified.Build()
    fixed = ShapeFix_Shape(unified.Shape())
    fixed.Perform()
    return fixed.Shape()


def _gate_shape(
    candidate: Any,
    *,
    m0: float,
    params: PlaneChainParams,
) -> tuple[bool, dict[str, Any]]:
    m = float(ocp_mass(candidate))
    topo = ocp_shape_topology(candidate, check_brep=True)
    span = _bbox_span(candidate)
    span_ok = all(
        float(span[i]) <= float(params.cell_size_mm) * float(params.max_span_factor)
        for i in range(3)
    )
    ok = (
        int(topo.get("solids") or 0) == 1
        and bool(topo.get("brep_valid"))
        and abs(m - m0) <= float(params.max_mass_drift_mm3)
        and span_ok
    )
    return ok, {
        "mass_mm3": m,
        "mass_drift": abs(m - m0),
        "brep_valid": topo.get("brep_valid"),
        "solids": topo.get("solids"),
        "accepted": bool(ok),
    }


def heal_plane_chains(
    shape: Any,
    params: PlaneChainParams,
) -> tuple[Any, dict[str, Any]]:
    """
    Heal fragmented hub edges under hard STEP gates.

    Priority:
      1) UnifyEdges-only (no face collapse)
      2) BRepLib_FuseEdges
      3) Full UnifySameDomain+ShapeFix
      4) Fall back to original if none accepted
    """
    m0 = float(ocp_mass(shape))
    topo0 = ocp_shape_topology(shape, check_brep=True)
    n0 = _count_hub_edges(shape, params)
    diag0 = diagnose_plane_chains(shape, params)

    report: dict[str, Any] = {
        "mass0_mm3": m0,
        "n_hub0": n0,
        "topo0": topo0,
        "diagnose0": {
            "hypothesis_ok": diag0.get("hypothesis_ok"),
            "n_groups_with_multi_chain": diag0.get("n_groups_with_multi_chain"),
            "groups": {
                g: {
                    "n_edges": diag0["groups"][g]["n_edges"],
                    "n_chains": diag0["groups"][g]["n_chains"],
                    "n_multi_chains": diag0["groups"][g]["n_multi_chains"],
                    "mean_edges_per_chain": diag0["groups"][g]["mean_edges_per_chain"],
                }
                for g in PLANE_GROUPS
                if g in diag0["groups"]
            },
        },
        "steps": [],
        "rebuild_wires": [],
        "fallback_original": False,
    }

    clustered = cluster_hub_edges_by_slot_planes(shape, params)
    plane_ns = {
        g: np.asarray(v, dtype=float)
        for g, v in (clustered.get("plane_normals") or {}).items()
    }
    for g in PLANE_GROUPS:
        edges = clustered["clustered"].get(g) or []
        chains = chain_edges_by_endpoints(edges, gap_tol_mm=params.gap_tol_mm)
        nvec = plane_ns.get(g)
        if nvec is None:
            continue
        for ci, ch in enumerate(chains):
            if int(ch["n_edges"]) < 2:
                continue
            wire_edge = _try_rebuild_chain_wire(ch, nvec)
            report["rebuild_wires"].append(
                {
                    "group": g,
                    "chain_index": ci,
                    "n_edges": ch["n_edges"],
                    "total_length_mm": ch["total_length_mm"],
                    "bspline_edge_ok": wire_edge is not None,
                }
            )

    work = shape
    # Defensive copy: Unify/FuseEdges may mutate the underlying BRep in place.
    try:
        from OCP.BRepBuilderAPI import BRepBuilderAPI_Copy

        work = BRepBuilderAPI_Copy(shape).Shape()
        original = BRepBuilderAPI_Copy(shape).Shape()
    except Exception:
        original = shape
        work = shape

    ops: list[tuple[str, Any]] = [
        ("UnifyEdges_only", _try_unify_edges_only),
        ("BRepLib_FuseEdges", _try_fuse_edges),
        ("UnifySameDomain+ShapeFix", ocp_heal_fused_solid),
    ]
    for name, fn in ops:
        try:
            # Always start from last accepted solid (copy again)
            from OCP.BRepBuilderAPI import BRepBuilderAPI_Copy

            seed = BRepBuilderAPI_Copy(work).Shape()
            cand = fn(seed)
            ok, meta = _gate_shape(cand, m0=m0, params=params)
            meta = {
                "op": name,
                "n_hub": _count_hub_edges(cand, params) if ok else None,
                **meta,
            }
            report["steps"].append(meta)
            if ok:
                work = cand
        except Exception as exc:
            report["steps"].append(
                {"op": name, "error": str(exc)[:300], "accepted": False}
            )

    ok_final, meta_final = _gate_shape(work, m0=m0, params=params)
    if not ok_final:
        work = original
        report["fallback_original"] = True
        ok_final, meta_final = _gate_shape(work, m0=m0, params=params)

    n1 = _count_hub_edges(work, params)
    m1 = float(ocp_mass(work))
    topo1 = ocp_shape_topology(work, check_brep=True)
    diag1 = diagnose_plane_chains(work, params)
    report.update(
        {
            "mass1_mm3": m1,
            "n_hub1": n1,
            "topo1": topo1,
            "hub_reduction": int(n0) - int(n1),
            "diagnose1": {
                "hypothesis_ok": diag1.get("hypothesis_ok"),
                "n_groups_with_multi_chain": diag1.get("n_groups_with_multi_chain"),
                "groups": {
                    g: {
                        "n_edges": diag1["groups"][g]["n_edges"],
                        "n_chains": diag1["groups"][g]["n_chains"],
                        "n_multi_chains": diag1["groups"][g]["n_multi_chains"],
                        "mean_edges_per_chain": diag1["groups"][g][
                            "mean_edges_per_chain"
                        ],
                    }
                    for g in PLANE_GROUPS
                    if g in diag1["groups"]
                },
            },
            "ok": bool(ok_final),
            "final_gate": meta_final,
        }
    )
    return work, report


def export_plane_chain_for_q(
    *,
    period_factor: float,
    step_in: str,
    out_dir: str,
    diagnose_only: bool = False,
    force: bool = False,
    params: PlaneChainParams | None = None,
) -> dict[str, Any]:
    q = float(period_factor)
    params = params or PlaneChainParams(period_factor=q)
    params.period_factor = q
    os.makedirs(out_dir, exist_ok=True)
    slug = f"exp_planeChain_af2q{_q_slug(q)}_L20_d2p0_1x1"
    diag_path = os.path.join(out_dir, f"{slug}_diagnose.json")
    step_out = os.path.join(out_dir, f"{slug}.step")
    man_path = os.path.join(out_dir, f"{slug}_manifest.json")

    print(f"  [planeChain] load {step_in}", flush=True)
    shape = ocp_read_step_shape(step_in)
    print(f"  [planeChain] diagnose Q={q:g} ...", flush=True)
    diag = diagnose_plane_chains(shape, params)
    with open(diag_path, "w", encoding="utf-8") as f:
        json.dump(diag, f, indent=2)
    # Compact chain targets for SW midpoint matching (metres not needed; mm)
    chain_targets = []
    for g in PLANE_GROUPS:
        for ci, ch in enumerate(diag["groups"][g]["chains"]):
            if int(ch["n_edges"]) < 1:
                continue
            chain_targets.append(
                {
                    "group": g,
                    "chain_index": ci,
                    "n_edges": ch["n_edges"],
                    "total_length_mm": ch["total_length_mm"],
                    "mids_mm": ch["mids"],
                }
            )
    targets_path = os.path.join(out_dir, f"{slug}_chain_targets.json")
    with open(targets_path, "w", encoding="utf-8") as f:
        json.dump(chain_targets, f, indent=2)
    print(
        f"  [planeChain] hub={diag['n_hub_edges']} multi_groups="
        f"{diag['n_groups_with_multi_chain']} hypothesis_ok={diag['hypothesis_ok']}"
        f" → {diag_path}",
        flush=True,
    )

    man: dict[str, Any] = {
        "experiment": "plane_chain_edge_heal",
        "period_factor": q,
        "slug": slug,
        "step_in": os.path.abspath(step_in),
        "diagnose_path": os.path.abspath(diag_path),
        "chain_targets_path": os.path.abspath(targets_path),
        "diagnose": {
            "n_hub_edges": diag["n_hub_edges"],
            "n_groups_with_multi_chain": diag["n_groups_with_multi_chain"],
            "hypothesis_ok": diag["hypothesis_ok"],
            "groups": {
                g: {
                    "n_edges": diag["groups"][g]["n_edges"],
                    "n_multi_chains": diag["groups"][g]["n_multi_chains"],
                    "mean_edges_per_chain": diag["groups"][g]["mean_edges_per_chain"],
                }
                for g in PLANE_GROUPS
            },
        },
    }

    if diagnose_only:
        with open(man_path, "w", encoding="utf-8") as f:
            json.dump(man, f, indent=2)
        return man

    if (
        not force
        and os.path.isfile(step_out)
        and os.path.getsize(step_out) > 1000
        and os.path.isfile(man_path)
    ):
        with open(man_path, encoding="utf-8") as f:
            return json.load(f)

    print(f"  [planeChain] heal Q={q:g} ...", flush=True)
    healed, heal_rep = heal_plane_chains(shape, params)
    if not heal_rep.get("ok"):
        raise RuntimeError(f"heal failed gates: {heal_rep.get('steps')}")
    ocp_write_step(healed, step_out)
    # readback gate
    rb = ocp_read_step_shape(step_out)
    topo = ocp_shape_topology(rb, check_brep=True)
    if int(topo.get("solids") or 0) != 1 or not bool(topo.get("brep_valid")):
        raise RuntimeError(f"healed STEP invalid topo={topo}")
    mass = float(ocp_mass(rb))
    man.update(
        {
            "step_path": os.path.abspath(step_out),
            "mass_mm3": mass,
            "topology": topo,
            "heal": heal_rep,
            "ok": True,
        }
    )
    with open(man_path, "w", encoding="utf-8") as f:
        json.dump(man, f, indent=2)
    print(
        f"  [planeChain] healed n_hub {heal_rep['n_hub0']}→{heal_rep['n_hub1']} "
        f"mass={mass:.2f} → {step_out}",
        flush=True,
    )
    return man


def default_plane_chain_out_dir() -> str:
    path = os.path.join(
        default_exp_out_dir(), "_hard_cad_delivery", "_plane_chain_heal"
    )
    os.makedirs(path, exist_ok=True)
    return path
