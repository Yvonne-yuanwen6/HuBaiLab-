"""Tetrahedral (C3D4) solid mesh for cylindrical lattice beams."""

from __future__ import annotations

import math

import numpy as np

from src.mesh.solid_profiles import SOLID_SKIP_BEAM_TYPES, polyline_mesh_profile


def _round_key(pos: np.ndarray, decimals: int = 6) -> tuple[float, float, float]:
    return tuple(np.round(pos, decimals))


def _beam_axes(p1: np.ndarray, p2: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return (axis_unit, u, v) orthonormal basis with axis along p1->p2."""
    axis = p2 - p1
    length = float(np.linalg.norm(axis))
    if length < 1e-12:
        raise ValueError("Degenerate beam segment")
    e_z = axis / length

    ref = np.array([1.0, 0.0, 0.0])
    if abs(float(np.dot(e_z, ref))) > 0.9:
        ref = np.array([0.0, 1.0, 0.0])

    e_x = np.cross(e_z, ref)
    e_x /= np.linalg.norm(e_x)
    e_y = np.cross(e_z, e_x)
    return e_z, e_x, e_y


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


def _orient_tet(
    coords: dict[int, np.ndarray],
    tet: tuple[int, int, int, int],
) -> tuple[int, int, int, int]:
    """Ensure positive signed volume (Abaqus C3D4 right-hand rule)."""
    n0, n1, n2, n3 = tet
    if _tet_volume(coords, n0, n1, n2, n3) < 0.0:
        return n0, n2, n1, n3
    return tet


def _parallel_transport_frame(
    e_x_prev: np.ndarray,
    e_z_new: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Carry the cross-section basis around a polyline bend."""
    e_z = e_z_new / float(np.linalg.norm(e_z_new))
    e_x = e_x_prev - float(np.dot(e_x_prev, e_z)) * e_z
    x_norm = float(np.linalg.norm(e_x))
    if x_norm < 1e-12:
        ref = np.array([1.0, 0.0, 0.0])
        if abs(float(np.dot(e_z, ref))) > 0.9:
            ref = np.array([0.0, 1.0, 0.0])
        e_x = np.cross(e_z, ref)
        x_norm = float(np.linalg.norm(e_x))
    e_x = e_x / x_norm
    e_y = np.cross(e_z, e_x)
    return e_z, e_x, e_y


def _mesh_prism_ring_stack(
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
    """Add C3D4 elements between consecutive ring stations."""
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
            for tet in _prism_to_tets(*prism):
                tet = _orient_tet(coords, tet)
                mesh_elements.append((next_eid, *tet, bid, btype))
                elsets_by_type.setdefault(btype, []).append(next_eid)
                next_eid += 1
    return next_eid


def mesh_polyline_c3d4(
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
    """
    One continuous solid along a polyline (no kink gaps between short segments).
    """
    if mesh_elements is None:
        mesh_elements = []
    if elsets_by_type is None:
        elsets_by_type = {}

    pts = [np.asarray(p, dtype=float) for p in path_points]
    if len(pts) < 2 or radius <= 0:
        return next_eid

    # Densify stations along each span
    dense: list[np.ndarray] = []
    for i in range(len(pts) - 1):
        p_a, p_b = pts[i], pts[i + 1]
        steps = n_axial_per_span if i < len(pts) - 2 else n_axial_per_span
        for k in range(steps):
            t = k / steps
            dense.append(p_a + t * (p_b - p_a))
    dense.append(pts[-1].copy())

    # Frames along dense path
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

    return _mesh_prism_ring_stack(
        ring_ids, center_ids, n_theta, coords, next_eid, bid, btype, elsets_by_type, mesh_elements
    )


def _prism_to_tets(
    n0: int, n1: int, n2: int, n3: int, n4: int, n5: int
) -> list[tuple[int, int, int, int]]:
    """
    Split a 6-node triangular prism into three C3D4 elements.

    Bottom triangle: n0 (center), n1, n2.  Top triangle: n3 (center), n4, n5.
    """
    return [
        (n0, n1, n2, n5),
        (n0, n1, n5, n4),
        (n0, n4, n5, n3),
    ]


def mesh_beams_c3d4(
    nodes: list,
    beams: list,
    *,
    polylines: list[dict] | None = None,
    n_axial: int | None = None,
    n_theta: int = 8,
    merge_decimals: int = 6,
    polyline_axial_per_span: int = 4,
) -> tuple[list[tuple[int, float, float, float]], list[tuple[int, int, int, int, int]], dict[str, list[int]]]:
    """
    Mesh each beam as a solid cylinder with C3D4 elements.

    Nodes at the same position are merged (rim + center), so joints stay connected.
    """
    node_lookup = {int(n[0]): np.array([float(n[1]), float(n[2]), float(n[3])]) for n in nodes}

    pos_to_nid: dict[tuple[float, float, float], int] = {}
    mesh_nodes: list[tuple[int, float, float, float]] = []
    mesh_elements: list[tuple[int, int, int, int, int, str]] = []
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
        length = float(np.linalg.norm(p2 - p1))
        if length < 1e-12 or r <= 0:
            continue

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

        next_eid = _mesh_prism_ring_stack(
            ring_ids,
            center_ids,
            n_theta,
            coords,
            next_eid,
            int(bid),
            str(btype),
            elsets_by_type,
            mesh_elements,
        )

    if polylines:
        for poly in polylines:
            node_ids = [int(n) for n in poly["nodes"]]
            path = [node_lookup[nid] for nid in node_ids]
            prof = polyline_mesh_profile(poly)
            if prof["profile"] == "square":
                # 1×1 方截面仅 C3D8R 路径精确；C3D4 用内切圆近似
                r = float(prof["square_half"])
            else:
                r = prof["radius"]
            next_eid = mesh_polyline_c3d4(
                path,
                r,
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

    elements_out = [(e[0], e[1], e[2], e[3], e[4]) for e in mesh_elements]
    return mesh_nodes, elements_out, elsets_by_type
