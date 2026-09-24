"""
Read-only strut-angle detection + node-level classification (experiment).

Measures pairwise tangent angles from SFBL S centreline polylines, classifies
unitcell junctions (spine / ±Z clusters / Q=0 star), and suggests a *single*
blend radius per node (simple adaptive granularity).

Does not fuse, fillet, or touch batch / paper_box defaults.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np

from src.export.exp_node_transition.adaptive_fillet import (
    AdaptiveFilletConfig,
    AdaptiveNodeSpec,
    NodeClass,
    adaptive_r_blend_mm,
)
from src.export.exp_node_transition.bcc_explicit_cores import (
    _ocp_sphere,
    default_exp_out_dir,
)
from src.export.exp_node_transition.bcc_fillet_blend import (
    ExpFilletParams,
    load_fillet_pipe_parts,
)
from src.export.ocp_unitcell_fuse import ocp_fuse_pair, ocp_write_step


@dataclass
class AngleClassifyParams:
    cell_size_mm: float = 20.0
    rod_d_mm: float = 2.0
    amplitude_mm: float = 2.0
    period_factor: float = 1.5
    n_segments: int = 32
    # Sample arc length from cell centre for cluster tangents (mm)
    cluster_sample_s_mm: float = 3.5
    # If |t_z| above this near centre → treat as Q>0 spine/cluster layout
    spine_tz_abs_min: float = 0.85
    # Cluster mutual angles below this → INTERIOR_CLUSTER (deg)
    cluster_theta_max_deg: float = 35.0
    # Adaptive radius knobs (node-level suggestion only)
    k_blend: float = 0.50
    k_blend_acute: float = 0.12
    acute_theta_deg: float = 25.0
    k_angle: float = 0.35


@dataclass
class StrutTangentInfo:
    index: int
    key: str
    t_centre: tuple[float, float, float]
    t_sample: tuple[float, float, float]
    p_sample_mm: tuple[float, float, float]
    tz_centre: float
    cluster: str  # "posZ" | "negZ" | "mixed"


@dataclass
class PairAngle:
    i: int
    j: int
    angle_deg: float
    location: str  # "centre" | "cluster_posZ" | "cluster_negZ"


@dataclass
class ClassifiedNode:
    node_id: str
    node_class: str
    xyz_mm: tuple[float, float, float]
    valence: int
    theta_min_deg: float
    theta_mean_deg: float
    theta_max_deg: float
    member_struts: list[int]
    r_blend_suggest_mm: float
    skip_fillet: bool
    notes: str = ""


@dataclass
class AngleClassifyReport:
    params: dict[str, Any]
    strut_tangents: list[dict[str, Any]] = field(default_factory=list)
    pair_angles: list[dict[str, Any]] = field(default_factory=list)
    nodes: list[dict[str, Any]] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)
    marker_step: str | None = None
    json_path: str | None = None


def _unit(v: np.ndarray) -> np.ndarray:
    n = float(np.linalg.norm(v))
    if n < 1e-12:
        raise ValueError("zero tangent")
    return v / n


def _point_at_arc_s(path_pts: tuple, s_mm: float) -> np.ndarray:
    P = np.asarray(path_pts, dtype=float)
    if len(P) < 2:
        raise ValueError("path too short")
    seg = np.linalg.norm(np.diff(P, axis=0), axis=1)
    cum = np.concatenate([[0.0], np.cumsum(seg)])
    total = float(cum[-1])
    s = min(max(float(s_mm), 0.0), total)
    i = int(np.searchsorted(cum, s, side="right") - 1)
    i = max(0, min(i, len(P) - 2))
    t0, t1 = float(cum[i]), float(cum[i + 1])
    if t1 <= t0 + 1e-12:
        return P[i].copy()
    a = (s - t0) / (t1 - t0)
    return (1.0 - a) * P[i] + a * P[i + 1]


def _tangent_at_arc_s(path_pts: tuple, s_mm: float) -> np.ndarray:
    P = np.asarray(path_pts, dtype=float)
    seg = np.linalg.norm(np.diff(P, axis=0), axis=1)
    cum = np.concatenate([[0.0], np.cumsum(seg)])
    total = float(cum[-1])
    s = min(max(float(s_mm), 0.0), total)
    i = int(np.searchsorted(cum, s, side="right") - 1)
    i = max(0, min(i, len(P) - 2))
    return _unit(P[i + 1] - P[i])


def _angle_deg(a: np.ndarray, b: np.ndarray) -> float:
    c = float(np.clip(np.dot(_unit(a), _unit(b)), -1.0, 1.0))
    return float(np.degrees(np.arccos(c)))


def measure_strut_tangents(
    parts: list[tuple[str, tuple, float]],
    params: AngleClassifyParams,
) -> list[StrutTangentInfo]:
    out: list[StrutTangentInfo] = []
    s = float(params.cluster_sample_s_mm)
    for i, (key, pts, _r) in enumerate(parts):
        # near-centre: first polyline segment (junction tangents)
        P = np.asarray(pts, dtype=float)
        tc = _unit(P[1] - P[0])
        ts = _tangent_at_arc_s(pts, s)
        ps = _point_at_arc_s(pts, s)
        tz = float(tc[2])
        if tz >= float(params.spine_tz_abs_min):
            cluster = "posZ"
        elif tz <= -float(params.spine_tz_abs_min):
            cluster = "negZ"
        else:
            cluster = "mixed"
        out.append(
            StrutTangentInfo(
                index=i,
                key=str(key),
                t_centre=(float(tc[0]), float(tc[1]), float(tc[2])),
                t_sample=(float(ts[0]), float(ts[1]), float(ts[2])),
                p_sample_mm=(float(ps[0]), float(ps[1]), float(ps[2])),
                tz_centre=tz,
                cluster=cluster,
            )
        )
    return out


def pairwise_angles(
    tangents: list[StrutTangentInfo],
    *,
    use_sample: bool,
    location: str,
    indices: list[int] | None = None,
) -> list[PairAngle]:
    """
    Pairwise tangent angles.

    For cluster θ (acute ~11–15° at Q=1.5): use *centre* tangents among
    same-cluster members (``use_sample=False``). Sample tangents at s≈3–4 mm
    have already flared and are only for node XYZ placement.
    """
    idxs = list(indices) if indices is not None else [t.index for t in tangents]
    by_i = {t.index: t for t in tangents}
    pairs: list[PairAngle] = []
    for a in range(len(idxs)):
        for b in range(a + 1, len(idxs)):
            ia, ib = idxs[a], idxs[b]
            ta = np.asarray(
                by_i[ia].t_sample if use_sample else by_i[ia].t_centre, dtype=float
            )
            tb = np.asarray(
                by_i[ib].t_sample if use_sample else by_i[ib].t_centre, dtype=float
            )
            pairs.append(
                PairAngle(
                    i=ia,
                    j=ib,
                    angle_deg=_angle_deg(ta, tb),
                    location=location,
                )
            )
    return pairs


def _stats(angles: list[float]) -> tuple[float, float, float]:
    if not angles:
        return (float("nan"), float("nan"), float("nan"))
    a = np.asarray(angles, dtype=float)
    return float(np.min(a)), float(np.mean(a)), float(np.max(a))


def classify_unitcell_nodes(
    tangents: list[StrutTangentInfo],
    pair_angles: list[PairAngle],
    params: AngleClassifyParams,
) -> list[ClassifiedNode]:
    """Simple node-level classification from measured angles."""
    r = 0.5 * float(params.rod_d_mm)
    cfg = AdaptiveFilletConfig(
        k_blend=float(params.k_blend),
        k_blend_acute=float(params.k_blend_acute),
        acute_theta_deg=float(params.acute_theta_deg),
        k_angle=float(params.k_angle),
    )
    pos = [t for t in tangents if t.cluster == "posZ"]
    neg = [t for t in tangents if t.cluster == "negZ"]
    mixed = [t for t in tangents if t.cluster == "mixed"]
    n_spine_like = len(pos) + len(neg)
    q_gt0 = n_spine_like >= 6 and len(mixed) <= 2

    nodes: list[ClassifiedNode] = []

    def _suggest(
        node_class: NodeClass,
        xyz: tuple[float, float, float],
        valence: int,
        theta_min: float,
        skip: bool,
        members: list[int],
        nid: str,
        notes: str,
        theta_mean: float,
        theta_max: float,
    ) -> ClassifiedNode:
        spec = AdaptiveNodeSpec(
            node_id=nid,
            xyz_mm=xyz,
            node_class=node_class,
            valence=valence,
            r_min_strut_mm=r,
            theta_min_deg=float(theta_min),
            skip_fillet=skip,
        )
        rb = 0.0 if skip else adaptive_r_blend_mm(spec, cfg)
        return ClassifiedNode(
            node_id=nid,
            node_class=node_class.value,
            xyz_mm=xyz,
            valence=valence,
            theta_min_deg=float(theta_min),
            theta_mean_deg=float(theta_mean),
            theta_max_deg=float(theta_max),
            member_struts=members,
            r_blend_suggest_mm=float(rb),
            skip_fillet=skip,
            notes=notes,
        )

    if not q_gt0:
        # Q≈0 style: one centre star from centre tangents
        angs = [p.angle_deg for p in pair_angles if p.location == "centre"]
        tmin, tmean, tmax = _stats(angs)
        nodes.append(
            _suggest(
                NodeClass.INTERIOR_CELL,
                (0.0, 0.0, 0.0),
                len(tangents),
                tmin,
                False,
                [t.index for t in tangents],
                "centre_star",
                "Q≈0-like: measured centre pairwise angles",
                tmean,
                tmax,
            )
        )
        return nodes

    # Q>0: spine at origin (skip large fillet) + ±Z clusters
    # Spine θ from all centre pairs (includes ~180° opposite); min ≈ same-cluster acute.
    centre_angs = [p.angle_deg for p in pair_angles if p.location == "centre"]
    tmin_c, tmean_c, tmax_c = _stats(centre_angs)
    nodes.append(
        _suggest(
            NodeClass.INTERIOR_SPINE,
            (0.0, 0.0, 0.0),
            len(tangents),
            tmin_c,
            True,
            [t.index for t in tangents],
            "centre_spine",
            "Q>0 Z-spine: skip large centre fillet; use clusters / armpits",
            tmean_c,
            tmax_c,
        )
    )

    for lab, members, loc in (
        ("posZ", pos, "cluster_posZ"),
        ("negZ", neg, "cluster_negZ"),
    ):
        if len(members) < 2:
            continue
        # Acute cluster angles from centre same-cluster tangents (not sample s).
        angs = [p.angle_deg for p in pair_angles if p.location == loc]
        tmin, tmean, tmax = _stats(angs)
        pts = np.asarray([m.p_sample_mm for m in members], dtype=float)
        xyz = tuple(float(x) for x in np.mean(pts, axis=0))
        skip = False
        if not (tmin < float(params.cluster_theta_max_deg)):
            notes = (
                f"{lab} mutual angles large (min={tmin:.1f}° at centre); "
                "may not be a tight cluster"
            )
        else:
            notes = (
                f"{lab} 4-rod cluster; θ from centre same-cluster tangents "
                f"θ_min={tmin:.1f}°; node XYZ at s≈{params.cluster_sample_s_mm:g} mm"
            )
        nodes.append(
            _suggest(
                NodeClass.INTERIOR_CLUSTER,
                xyz,  # type: ignore[arg-type]
                len(members),
                tmin,
                skip,
                [m.index for m in members],
                f"cluster_{lab}",
                notes,
                tmean,
                tmax,
            )
        )

    return nodes


def run_angle_classify(
    params: AngleClassifyParams | None = None,
) -> tuple[list[StrutTangentInfo], list[PairAngle], list[ClassifiedNode]]:
    params = params or AngleClassifyParams()
    parts = load_fillet_pipe_parts(
        ExpFilletParams(
            cell_size_mm=params.cell_size_mm,
            rod_d_mm=params.rod_d_mm,
            amplitude_mm=params.amplitude_mm,
            period_factor=params.period_factor,
            n_segments=params.n_segments,
        )
    )
    tangents = measure_strut_tangents(parts, params)
    pairs: list[PairAngle] = []
    pairs.extend(
        pairwise_angles(tangents, use_sample=False, location="centre")
    )
    pos_i = [t.index for t in tangents if t.cluster == "posZ"]
    neg_i = [t.index for t in tangents if t.cluster == "negZ"]
    # Cluster θ: centre tangents among same-cluster members (~11–15° at Q=1.5)
    if len(pos_i) >= 2:
        pairs.extend(
            pairwise_angles(
                tangents,
                use_sample=False,
                location="cluster_posZ",
                indices=pos_i,
            )
        )
    if len(neg_i) >= 2:
        pairs.extend(
            pairwise_angles(
                tangents,
                use_sample=False,
                location="cluster_negZ",
                indices=neg_i,
            )
        )
    nodes = classify_unitcell_nodes(tangents, pairs, params)
    return tangents, pairs, nodes


def _marker_spheres(
    nodes: list[ClassifiedNode],
    tangents: list[StrutTangentInfo],
    *,
    strut_r: float,
) -> list[Any]:
    """Spheres sized to show node class (for STL / optional host fuse)."""
    shapes: list[Any] = []
    for nd in nodes:
        if nd.node_class == NodeClass.INTERIOR_SPINE.value:
            rad = 1.35 * strut_r
        elif nd.node_class == NodeClass.INTERIOR_CLUSTER.value:
            rad = 1.20 * strut_r
        else:
            rad = 1.25 * strut_r
        shapes.append(_ocp_sphere(nd.xyz_mm, rad))
    for t in tangents:
        shapes.append(_ocp_sphere(t.p_sample_mm, 0.55 * strut_r))
    return shapes


def _make_compound(shapes: list[Any]) -> Any:
    from OCP.BRep import BRep_Builder
    from OCP.TopoDS import TopoDS_Compound

    if not shapes:
        raise ValueError("no shapes")
    builder = BRep_Builder()
    comp = TopoDS_Compound()
    builder.MakeCompound(comp)
    for sh in shapes:
        builder.Add(comp, sh)
    return comp


def write_classify_markers_stl(
    nodes: list[ClassifiedNode],
    tangents: list[StrutTangentInfo],
    out_stl: str,
    *,
    strut_r: float,
    deflection_mm: float = 0.15,
) -> str:
    """
    One STL file with all marker spheres (compound → single mesh file).

    Prefer this over markers-only STEP: SW opens one window; disconnected
    spheres as STEP often become an assembly with many windows.
    """
    from OCP.BRepMesh import BRepMesh_IncrementalMesh
    from OCP.StlAPI import StlAPI_Writer

    shapes = _marker_spheres(nodes, tangents, strut_r=strut_r)
    comp = _make_compound(shapes)
    os.makedirs(os.path.dirname(out_stl) or ".", exist_ok=True)
    BRepMesh_IncrementalMesh(comp, float(deflection_mm))
    ok = bool(StlAPI_Writer().Write(comp, os.path.abspath(out_stl)))
    if not ok or not os.path.isfile(out_stl) or os.path.getsize(out_stl) < 100:
        raise RuntimeError(f"marker STL write failed: {out_stl}")
    return out_stl


def fuse_markers_onto_host(
    host: Any,
    nodes: list[ClassifiedNode],
    tangents: list[StrutTangentInfo],
    *,
    strut_r: float,
) -> Any:
    """Best-effort fuse of markers into host; require final solids==1."""
    from src.export.ocp_unitcell_fuse import ocp_shape_topology

    cur = host
    n_ok = 0
    for i, sph in enumerate(
        _marker_spheres(nodes, tangents, strut_r=strut_r), start=1
    ):
        fused = None
        for glue, fz in (("off", 0.05), ("off", 0.12), ("shift", 0.08)):
            try:
                cand = ocp_fuse_pair(
                    cur,
                    sph,
                    glue=glue,  # type: ignore[arg-type]
                    fuzzy_mm=fz,
                    label=f"classify-marker-{i}",
                    simplify=False,
                )
                if int(ocp_shape_topology(cand).get("solids") or 0) != 1:
                    continue
                fused = cand
                break
            except Exception:
                continue
        if fused is None:
            continue
        cur = fused
        n_ok += 1
    if n_ok == 0:
        raise RuntimeError("no marker fused onto host")
    topo = ocp_shape_topology(cur)
    if int(topo.get("solids") or 0) != 1:
        raise RuntimeError(f"classify preview solids={topo.get('solids')}")
    return cur


def write_classify_preview_step(
    host: Any,
    nodes: list[ClassifiedNode],
    tangents: list[StrutTangentInfo],
    out_step: str,
    *,
    strut_r: float,
) -> str:
    """Optional single-solid STEP preview (bare + markers). May fail on BOP."""
    solid = fuse_markers_onto_host(host, nodes, tangents, strut_r=strut_r)
    os.makedirs(os.path.dirname(out_step) or ".", exist_ok=True)
    ocp_write_step(solid, out_step)
    return out_step


def export_angle_classify_case(
    params: AngleClassifyParams | None = None,
    *,
    out_dir: str | None = None,
    write_markers: bool = True,
) -> AngleClassifyReport:
    """
    JSON report + optional marker STL (one file / one SW window).

    Never writes markers-only STEP (multi-body assembly → many SW windows).
    """
    params = params or AngleClassifyParams()
    out_dir = out_dir or default_exp_out_dir()
    os.makedirs(out_dir, exist_ok=True)

    q = float(params.period_factor)
    q_tag = str(q).replace(".", "p")
    slug = (
        f"exp_angleClass_af{int(round(params.amplitude_mm))}q{q_tag}"
        f"_L{int(round(params.cell_size_mm))}"
        f"_d{str(params.rod_d_mm).replace('.', 'p')}"
    )

    tangents, pairs, nodes = run_angle_classify(params)
    marker_step = None
    if write_markers:
        stl_path = os.path.join(out_dir, f"{slug}_markers.stl")
        try:
            write_classify_markers_stl(
                nodes,
                tangents,
                stl_path,
                strut_r=0.5 * float(params.rod_d_mm),
            )
            marker_step = os.path.abspath(stl_path)
            print(f"  markers STL (1 window): {marker_step}", flush=True)
        except Exception as exc:
            print(f"  marker STL warn: {exc}", flush=True)
            marker_step = None

    pos_n = sum(1 for t in tangents if t.cluster == "posZ")
    neg_n = sum(1 for t in tangents if t.cluster == "negZ")
    summary = {
        "layout": "spine_clusters" if pos_n + neg_n >= 6 else "centre_star",
        "n_posZ": pos_n,
        "n_negZ": neg_n,
        "n_mixed": sum(1 for t in tangents if t.cluster == "mixed"),
        "n_nodes": len(nodes),
        "node_classes": [n.node_class for n in nodes],
        "r_blend_by_node": {
            n.node_id: n.r_blend_suggest_mm for n in nodes
        },
    }

    report = AngleClassifyReport(
        params=asdict(params),
        strut_tangents=[asdict(t) for t in tangents],
        pair_angles=[asdict(p) for p in pairs],
        nodes=[asdict(n) for n in nodes],
        summary=summary,
        marker_step=marker_step,
    )
    json_path = os.path.join(out_dir, f"{slug}_report.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(asdict(report), f, indent=2)
    report.json_path = json_path

    print(f"\n=== ANGLE CLASSIFY Q={q:g} ===", flush=True)
    print(f"  layout={summary['layout']} posZ={pos_n} negZ={neg_n}", flush=True)
    for n in nodes:
        print(
            f"  node {n.node_id}: {n.node_class} valence={n.valence} "
            f"θ=[{n.theta_min_deg:.1f}, {n.theta_mean_deg:.1f}, {n.theta_max_deg:.1f}]° "
            f"Rf_suggest={n.r_blend_suggest_mm:.3f} mm skip={n.skip_fillet}",
            flush=True,
        )
        print(f"    {n.notes}", flush=True)
    print(f"  report: {json_path}", flush=True)
    if marker_step:
        print(f"  markers: {marker_step}", flush=True)
    return report
