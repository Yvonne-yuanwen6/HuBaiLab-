"""Junction radii and sphere mesh for connected non-penetrating solids."""

from __future__ import annotations

import math
from collections import defaultdict

import numpy as np

from src.mesh.solid_profiles import SOLID_SKIP_BEAM_TYPES, polyline_mesh_profile


def effective_solid_radius(
    *,
    radius: float | None = None,
    profile: str = "circle",
    square_half: float | None = None,
) -> float:
    """外接圆半径：圆=R，正方形 1×1 → half×sqrt(2)。"""
    if str(profile).lower() == "square":
        h = 0.5 if square_half is None else float(square_half)
        return h * math.sqrt(2.0)
    return float(radius if radius is not None else 0.5)


def collect_solid_junction_radii(
    nodes: list,
    beams: list,
    polylines: list[dict] | None,
    *,
    polyline_endpoints_only: bool = False,
) -> dict[int, float]:
    """每个结构结点处，取相连杆件的最大外接半径。"""
    radii: dict[int, float] = defaultdict(float)
    for _bid, n1, n2, radius, btype in beams:
        if str(btype) in SOLID_SKIP_BEAM_TYPES:
            continue
        r = effective_solid_radius(radius=float(radius), profile="circle")
        radii[int(n1)] = max(radii[int(n1)], r)
        radii[int(n2)] = max(radii[int(n2)], r)
    if polylines:
        for poly in polylines:
            prof = polyline_mesh_profile(poly)
            if prof["profile"] == "square":
                r = effective_solid_radius(
                    profile="square", square_half=prof["square_half"]
                )
            else:
                r = effective_solid_radius(radius=prof["radius"], profile="circle")
            node_ids = [int(n) for n in poly["nodes"]]
            if polyline_endpoints_only and len(node_ids) >= 2:
                endpoint_ids = (node_ids[0], node_ids[-1])
            else:
                endpoint_ids = node_ids
            for nid in endpoint_ids:
                radii[int(nid)] = max(radii[int(nid)], r)
    return dict(radii)


def trim_beam_endpoints(
    p1: np.ndarray,
    p2: np.ndarray,
    trim_start: float,
    trim_end: float,
    *,
    min_length: float = 1e-6,
) -> tuple[np.ndarray, np.ndarray] | None:
    """
    Shorten a beam so its ends stop at junction-sphere surfaces (radius trim).

    trim_start / trim_end are distances from p1 / p2 along the chord toward the
    opposite end (typically junction_r at each node when junction spheres are used).
    """
    axis = np.asarray(p2, dtype=float) - np.asarray(p1, dtype=float)
    length = float(np.linalg.norm(axis))
    t0 = max(0.0, float(trim_start))
    t1 = max(0.0, float(trim_end))
    if length <= t0 + t1 + min_length:
        return None
    u = axis / length
    a = np.asarray(p1, dtype=float) + t0 * u
    b = np.asarray(p2, dtype=float) - t1 * u
    return a, b


def mesh_junction_spheres_c3d8r(
    junction_r: dict[int, float],
    node_lookup: dict[int, np.ndarray],
    *,
    get_nid,
    coords: dict[int, np.ndarray],
    n_lat: int = 4,
    n_theta: int = 8,
    next_eid: int = 1,
    elsets_by_type: dict[str, list[int]] | None = None,
    mesh_elements: list | None = None,
) -> int:
    """在结点处生成球体 C3D8R 网格，使不同截面/方向的杆在结点处连通。"""
    from src.mesh.beam_hex_mesh import _mesh_prism_ring_stack_c3d8

    if mesh_elements is None:
        mesh_elements = []
    if elsets_by_type is None:
        elsets_by_type = {}

    ex = np.array([1.0, 0.0, 0.0])
    ey = np.array([0.0, 1.0, 0.0])
    ez = np.array([0.0, 0.0, 1.0])

    for nid, radius in junction_r.items():
        r = float(radius)
        if r <= 1e-9:
            continue
        center = node_lookup.get(int(nid))
        if center is None:
            continue
        c = np.asarray(center, dtype=float)

        ring_ids: list[list[int]] = []
        center_ids: list[int] = []

        for i in range(n_lat + 1):
            phi = math.pi * float(i) / float(n_lat)
            z_off = r * math.cos(phi)
            ring_r = r * math.sin(phi)
            ctr = c + z_off * ez
            center_ids.append(get_nid(ctr))
            if ring_r < 1e-9:
                ring = [get_nid(ctr)] * n_theta
            else:
                ring = []
                for j in range(n_theta):
                    theta = 2.0 * math.pi * j / n_theta
                    pos = ctr + ring_r * (math.cos(theta) * ex + math.sin(theta) * ey)
                    ring.append(get_nid(pos))
            ring_ids.append(ring)

        next_eid = _mesh_prism_ring_stack_c3d8(
            ring_ids,
            center_ids,
            n_theta,
            coords,
            next_eid,
            int(nid),
            "junction",
            elsets_by_type,
            mesh_elements,
        )

    return next_eid
