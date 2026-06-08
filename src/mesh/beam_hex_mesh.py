"""Hexahedral (C3D8R) solid mesh for cylindrical lattice beams."""

from __future__ import annotations

import math

import numpy as np

from src.mesh.solid_profiles import SOLID_SKIP_BEAM_TYPES, polyline_mesh_profile
from src.mesh.beam_tet_mesh import (
    _beam_axes,
    _parallel_transport_frame,
    _round_key,
)


def _tet_volume(
    coords: dict[int, np.ndarray],
    n0: int,
    n1: int,
    n2: int,
    n3: int,
) -> float:
    a = coords[n0]
    b = coords[n1]
    c = coords[n2]
    d = coords[n3]
    return float(np.dot(b - a, np.cross(c - a, d - a))) / 6.0


def _hex_volume(coords: dict[int, np.ndarray], nodes: tuple[int, ...]) -> float:
    """Signed volume for Abaqus C3D8 node order (8 nodes, wedge allowed via repeats)."""
    n = nodes
    return (
        _tet_volume(coords, n[0], n[1], n[3], n[4])
        + _tet_volume(coords, n[1], n[2], n[3], n[6])
        + _tet_volume(coords, n[1], n[4], n[5], n[6])
        + _tet_volume(coords, n[3], n[4], n[6], n[7])
        + _tet_volume(coords, n[1], n[3], n[4], n[6])
    )


def _orient_c3d8(
    coords: dict[int, np.ndarray],
    nodes: tuple[int, int, int, int, int, int, int, int],
) -> tuple[int, int, int, int, int, int, int, int]:
    h = list(nodes)
    if _hex_volume(coords, tuple(h)) < 0.0:
        h[1], h[3] = h[3], h[1]
        h[5], h[7] = h[7], h[5]
    return tuple(h)


def _prism_to_c3d8(
    n0: int, n1: int, n2: int, n3: int, n4: int, n5: int
) -> tuple[int, int, int, int, int, int, int, int]:
    """
    Triangular prism as degenerate C3D8 (Abaqus wedge in brick form).

    Bottom triangle: n0 (center), n1, n2.  Top: n3 (center), n4, n5.
    """
    return (n0, n1, n2, n2, n3, n4, n5, n5)


def _mesh_prism_ring_stack_c3d8(
    ring_ids: list[list[int]],
    center_ids: list[int],
    n_theta: int,
    coords: dict[int, np.ndarray],
    next_eid: int,
    bid: int,
    btype: str,
    elsets_by_type: dict[str, list[int]],
    mesh_elements: list,
) -> int:
    for i in range(len(center_ids) - 1):
        for j in range(n_theta):
            j_next = (j + 1) % n_theta
            prism = (
                center_ids[i],
                ring_ids[i][j],
                ring_ids[i][j_next],
                center_ids[i + 1],
                ring_ids[i + 1][j],
                ring_ids[i + 1][j_next],
            )
            brick = _orient_c3d8(coords, _prism_to_c3d8(*prism))
            mesh_elements.append((next_eid, *brick, bid, btype))
            elsets_by_type.setdefault(btype, []).append(next_eid)
            next_eid += 1
    return next_eid


def _mesh_square_stack_c3d8(
    station_ids: list[tuple[int, int, int, int]],
    station_centers: list[int],
    coords: dict[int, np.ndarray],
    next_eid: int,
    bid: int,
    btype: str,
    elsets_by_type: dict[str, list[int]],
    mesh_elements: list,
) -> int:
    """Square tube: outer brick + center wedges for junction connectivity."""
    for i in range(len(station_ids) - 1):
        C0 = station_centers[i]
        C1 = station_centers[i + 1]
        a0, a1, a2, a3 = station_ids[i]
        b0, b1, b2, b3 = station_ids[i + 1]
        brick = _orient_c3d8(coords, (a0, a1, a2, a3, b0, b1, b2, b3))
        mesh_elements.append((next_eid, *brick, bid, btype))
        elsets_by_type.setdefault(btype, []).append(next_eid)
        next_eid += 1
        for ai, aj, bi, bj in ((a0, a1, b0, b1), (a1, a2, b1, b2), (a2, a3, b2, b3), (a3, a0, b3, b0)):
            wedge = _orient_c3d8(coords, _prism_to_c3d8(C0, ai, aj, C1, bi, bj))
            mesh_elements.append((next_eid, *wedge, bid, btype))
            elsets_by_type.setdefault(btype, []).append(next_eid)
            next_eid += 1
    return next_eid


def _square_corners(
    center: np.ndarray,
    e_x: np.ndarray,
    e_y: np.ndarray,
    half: float,
) -> list[np.ndarray]:
    h = float(half)
    return [
        center + h * e_x + h * e_y,
        center + h * e_x - h * e_y,
        center - h * e_x - h * e_y,
        center - h * e_x + h * e_y,
    ]


def _mesh_polyline_square_c3d8r(
    path_points: list[np.ndarray],
    half: float,
    *,
    get_nid,
    coords: dict[int, np.ndarray],
    n_axial_per_span: int = 4,
    bid: int = 0,
    btype: str = "load",
    mesh_elements: list | None = None,
    elsets_by_type: dict[str, list[int]] | None = None,
    next_eid: int = 1,
) -> int:
    """1×1 (or 2*half) square cross-section along a polyline."""
    if mesh_elements is None:
        mesh_elements = []
    if elsets_by_type is None:
        elsets_by_type = {}

    pts = [np.asarray(p, dtype=float) for p in path_points]
    if len(pts) < 2 or half <= 0:
        return next_eid

    dense: list[np.ndarray] = []
    for i in range(len(pts) - 1):
        p_a, p_b = pts[i], pts[i + 1]
        steps = n_axial_per_span
        for k in range(steps):
            t = k / steps
            dense.append(p_a + t * (p_b - p_a))
    dense.append(pts[-1].copy())

    frames: list[tuple[np.ndarray, np.ndarray, np.ndarray]] = []
    e_z0, e_x0, e_y0 = _beam_axes(dense[0], dense[1])
    frames.append((e_z0, e_x0, e_y0))
    for i in range(1, len(dense) - 1):
        e_z = dense[i + 1] - dense[i - 1]
        if float(np.linalg.norm(e_z)) < 1e-12:
            e_z = dense[i + 1] - dense[i]
        _, e_x, e_y = _parallel_transport_frame(frames[-1][1], e_z)
        e_z = e_z / float(np.linalg.norm(e_z))
        frames.append((e_z, e_x, e_y))
    e_zn, exn, eyn = _beam_axes(dense[-2], dense[-1])
    frames.append((e_zn, exn, eyn))

    station_ids: list[tuple[int, int, int, int]] = []
    station_centers: list[int] = []
    for i, center in enumerate(dense):
        _, e_x, e_y = frames[i]
        station_centers.append(get_nid(center))
        corners = _square_corners(center, e_x, e_y, half)
        station_ids.append(
            tuple(get_nid(np.asarray(c, dtype=float)) for c in corners)
        )

    return _mesh_square_stack_c3d8(
        station_ids, station_centers, coords, next_eid, bid, btype, elsets_by_type, mesh_elements
    )


def _mesh_straight_cylinder_c3d8r(
    p1: np.ndarray,
    p2: np.ndarray,
    radius: float,
    *,
    get_nid,
    coords: dict[int, np.ndarray],
    n_theta: int,
    n_axial: int | None,
    bid: int,
    btype: str,
    mesh_elements: list,
    elsets_by_type: dict[str, list[int]],
    next_eid: int,
) -> int:
    r = float(radius)
    length = float(np.linalg.norm(p2 - p1))
    if length < 1e-12 or r <= 0:
        return next_eid

    n_seg = n_axial
    if n_seg is None:
        n_seg = max(2, int(math.ceil(length / max(r * 1.5, 1e-6))))

    e_z, e_x, e_y = _beam_axes(p1, p2)
    ring_ids: list[list[int]] = []
    center_ids: list[int] = []

    for i in range(n_seg + 1):
        t = i / n_seg
        center = p1 + t * (p2 - p1)
        center_ids.append(get_nid(center))
        ring: list[int] = []
        for j in range(n_theta):
            ang = 2.0 * math.pi * j / n_theta
            offset = r * (math.cos(ang) * e_x + math.sin(ang) * e_y)
            ring.append(get_nid(center + offset))
        ring_ids.append(ring)

    return _mesh_prism_ring_stack_c3d8(
        ring_ids,
        center_ids,
        n_theta,
        coords,
        next_eid,
        bid,
        btype,
        elsets_by_type,
        mesh_elements,
    )


def mesh_beams_c3d8r(
    nodes: list,
    beams: list,
    *,
    polylines: list[dict] | None = None,
    n_axial: int | None = None,
    n_theta: int = 8,
    merge_decimals: int = 6,
    polyline_axial_per_span: int = 4,
    junction_spheres: bool = True,
    junction_n_lat: int = 4,
    trim_for_junctions: bool | None = None,
) -> tuple[list[tuple[int, float, float, float]], list[tuple[int, ...]], dict[str, list[int]]]:
    """
    Mesh each beam as a solid cylinder with C3D8R elements (wedge bricks).

    With ``junction_spheres=True``, beam ends are trimmed to junction-sphere radii
    so cylinders do not penetrate the nodal spheres (avoids contact blow-up at t=0).
    """
    from src.mesh.junction_mesh import collect_solid_junction_radii, trim_beam_endpoints

    if trim_for_junctions is None:
        trim_for_junctions = junction_spheres

    node_lookup = {int(n[0]): np.array([float(n[1]), float(n[2]), float(n[3])]) for n in nodes}
    junction_r: dict[int, float] = {}
    if trim_for_junctions or junction_spheres:
        junction_r = collect_solid_junction_radii(nodes, beams, polylines)

    pos_to_nid: dict[tuple[float, float, float], int] = {}
    mesh_nodes: list[tuple[int, float, float, float]] = []
    mesh_elements: list[tuple[int, ...]] = []
    elsets_by_type: dict[str, list[int]] = {}
    coords: dict[int, np.ndarray] = {}

    next_nid = 1
    next_eid = 1

    def get_nid(pos: np.ndarray) -> int:
        nonlocal next_nid
        key = _round_key(pos, merge_decimals)
        if key not in pos_to_nid:
            pos_to_nid[key] = next_nid
            mesh_nodes.append((next_nid, float(pos[0]), float(pos[1]), float(pos[2])))
            coords[next_nid] = pos.copy()
            next_nid += 1
        return pos_to_nid[key]

    for beam in beams:
        bid, n1, n2, radius, btype = beam
        if str(btype) in SOLID_SKIP_BEAM_TYPES:
            continue
        p1 = node_lookup[int(n1)]
        p2 = node_lookup[int(n2)]
        r = float(radius)
        if trim_for_junctions:
            trimmed = trim_beam_endpoints(
                p1,
                p2,
                junction_r.get(int(n1), 0.0),
                junction_r.get(int(n2), 0.0),
            )
            if trimmed is None:
                continue
            p1, p2 = trimmed

        next_eid = _mesh_straight_cylinder_c3d8r(
            p1,
            p2,
            r,
            get_nid=get_nid,
            coords=coords,
            n_theta=n_theta,
            n_axial=n_axial,
            bid=int(bid),
            btype=str(btype),
            mesh_elements=mesh_elements,
            elsets_by_type=elsets_by_type,
            next_eid=next_eid,
        )

    if polylines:
        for poly in polylines:
            node_ids = [int(n) for n in poly["nodes"]]
            path = [node_lookup[nid] for nid in node_ids]
            prof = polyline_mesh_profile(poly)
            if prof["profile"] == "square":
                half = prof["square_half"]
                for i in range(len(node_ids) - 1):
                    pa, pb = path[i], path[i + 1]
                    if trim_for_junctions:
                        trimmed = trim_beam_endpoints(
                            pa,
                            pb,
                            junction_r.get(node_ids[i], 0.0),
                            junction_r.get(node_ids[i + 1], 0.0),
                        )
                        if trimmed is None:
                            continue
                        pa, pb = trimmed
                    next_eid = _mesh_polyline_square_c3d8r(
                        [pa, pb],
                        half,
                        get_nid=get_nid,
                        coords=coords,
                        n_axial_per_span=polyline_axial_per_span,
                        bid=int(poly.get("id", 0)),
                        btype=str(poly.get("type", "support")),
                        mesh_elements=mesh_elements,
                        elsets_by_type=elsets_by_type,
                        next_eid=next_eid,
                    )
            else:
                rad = prof["radius"]
                for i in range(len(node_ids) - 1):
                    pa, pb = path[i], path[i + 1]
                    if trim_for_junctions:
                        trimmed = trim_beam_endpoints(
                            pa,
                            pb,
                            junction_r.get(node_ids[i], 0.0),
                            junction_r.get(node_ids[i + 1], 0.0),
                        )
                        if trimmed is None:
                            continue
                        pa, pb = trimmed
                    next_eid = _mesh_polyline_c3d8r(
                        [pa, pb],
                        rad,
                        get_nid=get_nid,
                        coords=coords,
                        n_theta=n_theta,
                        n_axial_per_span=polyline_axial_per_span,
                        bid=int(poly.get("id", 0)),
                        btype=str(poly.get("type", "support")),
                        mesh_elements=mesh_elements,
                        elsets_by_type=elsets_by_type,
                        next_eid=next_eid,
                    )

    if junction_spheres:
        from src.mesh.junction_mesh import mesh_junction_spheres_c3d8r

        struct_lookup = {
            int(n[0]): np.array([float(n[1]), float(n[2]), float(n[3])], dtype=float)
            for n in nodes
        }
        next_eid = mesh_junction_spheres_c3d8r(
            junction_r,
            struct_lookup,
            get_nid=get_nid,
            coords=coords,
            n_lat=junction_n_lat,
            n_theta=n_theta,
            next_eid=next_eid,
            elsets_by_type=elsets_by_type,
            mesh_elements=mesh_elements,
        )

    elements_out = [tuple(e[:9]) for e in mesh_elements]
    return mesh_nodes, elements_out, elsets_by_type


def _mesh_polyline_c3d8r(
    path_points: list[np.ndarray],
    radius: float,
    *,
    get_nid,
    coords: dict[int, np.ndarray],
    n_theta: int = 8,
    n_axial_per_span: int = 4,
    bid: int = 0,
    btype: str = "support",
    mesh_elements: list | None = None,
    elsets_by_type: dict[str, list[int]] | None = None,
    next_eid: int = 1,
) -> int:
    if mesh_elements is None:
        mesh_elements = []
    if elsets_by_type is None:
        elsets_by_type = {}

    pts = [np.asarray(p, dtype=float) for p in path_points]
    if len(pts) < 2 or radius <= 0:
        return next_eid

    dense: list[np.ndarray] = []
    for i in range(len(pts) - 1):
        p_a, p_b = pts[i], pts[i + 1]
        steps = n_axial_per_span
        for k in range(steps):
            t = k / steps
            dense.append(p_a + t * (p_b - p_a))
    dense.append(pts[-1].copy())

    frames: list[tuple[np.ndarray, np.ndarray, np.ndarray]] = []
    e_z0, e_x0, e_y0 = _beam_axes(dense[0], dense[1])
    frames.append((e_z0, e_x0, e_y0))
    for i in range(1, len(dense) - 1):
        e_z = dense[i + 1] - dense[i - 1]
        if float(np.linalg.norm(e_z)) < 1e-12:
            e_z = dense[i + 1] - dense[i]
        _, e_x, e_y = _parallel_transport_frame(frames[-1][1], e_z)
        e_z = e_z / float(np.linalg.norm(e_z))
        frames.append((e_z, e_x, e_y))
    e_zn, exn, eyn = _beam_axes(dense[-2], dense[-1])
    frames.append((e_zn, exn, eyn))

    r = float(radius)
    ring_ids: list[list[int]] = []
    center_ids: list[int] = []
    for i, center in enumerate(dense):
        e_z, e_x, e_y = frames[i]
        center_ids.append(get_nid(center))
        ring = []
        for j in range(n_theta):
            ang = 2.0 * math.pi * j / n_theta
            offset = r * (math.cos(ang) * e_x + math.sin(ang) * e_y)
            ring.append(get_nid(center + offset))
        ring_ids.append(ring)

    return _mesh_prism_ring_stack_c3d8(
        ring_ids, center_ids, n_theta, coords, next_eid, bid, btype, elsets_by_type, mesh_elements
    )
