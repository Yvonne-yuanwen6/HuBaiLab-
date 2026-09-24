"""
Analytic-cylinder intersection fillet (experiment).

Fuse equal-R cylinders along strut start-dirs, then OCC MakeFillet on the
pipe–pipe valley edges. Fillet faces are G1 to both circular rod surfaces.
No hub sphere, no canal fill.

Used by two-strut / cluster demo scripts only; not a batch default.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from src.export.exp_node_transition.centre_armpit_blend import _unit
from src.export.exp_node_transition.centre_edge_fillet import (
    _edge_faces,
    _edge_length_mm,
    _edge_midpoint_mm,
    _face_normal_at_edge_mid,
)
from src.export.ocp_unitcell_fuse import ocp_mass, ocp_shape_topology


def count_solids(shape: Any) -> int:
    from OCP.TopAbs import TopAbs_SOLID
    from OCP.TopExp import TopExp_Explorer

    n = 0
    exp = TopExp_Explorer(shape, TopAbs_SOLID)
    while exp.More():
        n += 1
        exp.Next()
    return n


def is_plane_face(face: Any) -> bool:
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_Plane

    try:
        return int(BRepAdaptor_Surface(face).GetType()) == int(GeomAbs_Plane)
    except Exception:
        return False


def cylinder_along(direction: np.ndarray, *, radius: float, length: float) -> Any:
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeCylinder
    from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt

    d = _unit(np.asarray(direction, dtype=float))
    ax = gp_Ax2(
        gp_Pnt(0.0, 0.0, 0.0),
        gp_Dir(float(d[0]), float(d[1]), float(d[2])),
    )
    return BRepPrimAPI_MakeCylinder(ax, float(radius), float(length)).Shape()


def collect_pipe_intersection_edges(
    shape: Any,
    *,
    min_edge_len_mm: float = 0.40,
    max_edge_len_mm: float = 20.0,
    min_r_mm: float = 0.25,
    max_r_mm: float | None = None,
    ndot_max: float = 0.85,
) -> list[dict[str, Any]]:
    """2-face pipe–pipe valleys (skip endcaps, generators, origin piercing)."""
    from OCP.TopAbs import TopAbs_EDGE
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS

    seen: set[tuple[float, float, float]] = set()
    out: list[dict[str, Any]] = []
    exp = TopExp_Explorer(shape, TopAbs_EDGE)
    while exp.More():
        edge = TopoDS.Edge_s(exp.Current())
        exp.Next()
        faces = _edge_faces(shape, edge)
        if len(faces) != 2:
            continue
        if any(is_plane_face(f) for f in faces):
            continue
        mid = _edge_midpoint_mm(edge)
        if mid is None:
            continue
        key = (
            round(float(mid[0]), 3),
            round(float(mid[1]), 3),
            round(float(mid[2]), 3),
        )
        if key in seen:
            continue
        seen.add(key)
        n0 = _face_normal_at_edge_mid(faces[0], edge)
        n1 = _face_normal_at_edge_mid(faces[1], edge)
        if n0 is None or n1 is None:
            continue
        ndot = float(np.dot(n0, n1))
        if ndot > float(ndot_max):
            continue
        rr = float(np.linalg.norm(mid))
        if rr < float(min_r_mm):
            continue
        if max_r_mm is not None and rr > float(max_r_mm):
            continue
        elen = _edge_length_mm(edge)
        if elen < float(min_edge_len_mm) or elen > float(max_edge_len_mm):
            continue
        out.append(
            {
                "edge": edge,
                "length_mm": elen,
                "r_mm": rr,
                "ndot": ndot,
                "mid": [float(x) for x in mid],
            }
        )
    out.sort(key=lambda d: d["ndot"])
    return out


def makefillet_rational(shape: Any, edges: list[Any], radius_mm: float) -> Any:
    from OCP.BRepFilletAPI import BRepFilletAPI_MakeFillet
    from OCP.ChFi3d import ChFi3d_Rational

    mk = BRepFilletAPI_MakeFillet(shape)
    mk.SetFilletShape(ChFi3d_Rational)
    for edge in edges:
        mk.Add(float(radius_mm), edge)
    mk.Build()
    if not mk.IsDone():
        raise RuntimeError("MakeFillet not done")
    return mk.Shape()


def apply_tangent_intersection_fillet(
    shape: Any,
    *,
    radius_mm: float,
    mass0: float,
    min_edge_len_mm: float = 0.40,
    max_r_mm: float | None = None,
) -> tuple[Any, dict[str, Any]]:
    cands = collect_pipe_intersection_edges(
        shape, min_edge_len_mm=min_edge_len_mm, max_r_mm=max_r_mm
    )
    print(
        f"  intersection edges={len(cands)} "
        + ", ".join(
            f"L={d['length_mm']:.2f}/ndot={d['ndot']:.3f}/r={d['r_mm']:.2f}"
            for d in cands
        ),
        flush=True,
    )
    if not cands:
        raise RuntimeError("no pipe–pipe intersection edge")

    edges = [d["edge"] for d in cands]
    cand_pub = [{k: v for k, v in d.items() if k != "edge"} for d in cands]
    errors: list[str] = []

    def _accept(trial: Any) -> tuple[Any, dict[str, Any], float, float]:
        if count_solids(trial) != 1:
            raise RuntimeError(f"solids={count_solids(trial)}")
        topo = ocp_shape_topology(trial, check_brep=True)
        m1 = float(ocp_mass(trial))
        if m1 < 0.95 * mass0:
            raise RuntimeError(f"mass collapse {m1:.3f} < 0.95*{mass0:.3f}")
        if not topo.get("brep_valid"):
            raise RuntimeError("brep invalid")
        dmass = m1 - mass0
        if dmass < -0.05:
            raise RuntimeError(f"dmass negative {dmass:+.4f}")
        return trial, topo, m1, dmass

    try:
        trial, topo, m1, dmass = _accept(
            makefillet_rational(shape, edges, radius_mm)
        )
        return trial, {
            "mode": "oneshot_all_ix_edges",
            "r_mm": radius_mm,
            "n_edges": len(edges),
            "candidates": cand_pub,
            "mass_mm3": m1,
            "dmass_mm3": dmass,
            "topology": topo,
        }
    except Exception as exc:
        errors.append(f"oneshot: {exc}")
        print(f"  oneshot failed ({exc}); try sequential", flush=True)

    cur = shape
    applied = 0
    last_topo: dict[str, Any] | None = None
    last_m = mass0
    for i, info in enumerate(cands):
        try:
            trial, last_topo, last_m, dmass = _accept(
                makefillet_rational(cur, [info["edge"]], radius_mm)
            )
            cur = trial
            applied += 1
            print(
                f"  +edge#{i} dmass_from_bare={dmass:+.4f} faces={last_topo.get('faces')}",
                flush=True,
            )
        except Exception as exc:
            errors.append(f"edge#{i}: {exc}")
            rec = collect_pipe_intersection_edges(
                cur, min_edge_len_mm=min_edge_len_mm, max_r_mm=max_r_mm
            )
            if not rec:
                continue
            try:
                trial, last_topo, last_m, dmass = _accept(
                    makefillet_rational(cur, [rec[0]["edge"]], radius_mm)
                )
                cur = trial
                applied += 1
                print(f"  +recollected dmass_from_bare={dmass:+.4f}", flush=True)
            except Exception as exc2:
                errors.append(f"recollect: {exc2}")

    if applied < 1:
        raise RuntimeError(f"no safe tangent fillet ({errors[-4:]})")
    return cur, {
        "mode": "sequential",
        "r_mm": radius_mm,
        "n_edges_applied": applied,
        "candidates": cand_pub,
        "mass_mm3": last_m,
        "dmass_mm3": last_m - mass0,
        "topology": last_topo,
        "errors": errors,
    }
