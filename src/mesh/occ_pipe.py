"""Gmsh OpenCASCADE pipe sweep along a centerline polyline."""

from __future__ import annotations

import numpy as np

from src.mesh.beam_tet_mesh import _beam_axes, _parallel_transport_frame


def occ_volume_tag(result: int | tuple | list) -> int:
    if isinstance(result, int):
        return int(result)
    if isinstance(result, (list, tuple)):
        if len(result) == 2 and isinstance(result[0], int):
            return int(result[1])
        if result and isinstance(result[0], (list, tuple)) and len(result[0]) == 2:
            return int(result[0][1])
    raise ValueError(f"Unexpected gmsh OCC pipe return: {result!r}")


def _as_points(points: list[np.ndarray]) -> list[np.ndarray]:
    pts = [np.asarray(p, dtype=float) for p in points]
    if len(pts) < 2:
        raise ValueError("Pipe path needs at least two points.")
    return pts


def frames_along_polyline(points: list[np.ndarray]) -> list[tuple[np.ndarray, np.ndarray, np.ndarray]]:
    """Parallel-transport orthonormal frames (e_z, e_x, e_y) along a polyline."""
    pts = _as_points(points)
    if len(pts) == 2:
        e_z, e_x, e_y = _beam_axes(pts[0], pts[1])
        return [(e_z, e_x, e_y), (e_z, e_x, e_y)]

    frames: list[tuple[np.ndarray, np.ndarray, np.ndarray]] = []
    e_z0, e_x0, e_y0 = _beam_axes(pts[0], pts[1])
    frames.append((e_z0, e_x0, e_y0))
    for i in range(1, len(pts) - 1):
        e_z = pts[i + 1] - pts[i - 1]
        if float(np.linalg.norm(e_z)) < 1e-12:
            e_z = pts[i + 1] - pts[i]
        _, e_x, e_y = _parallel_transport_frame(frames[-1][1], e_z)
        e_z = e_z / float(np.linalg.norm(e_z))
        frames.append((e_z, e_x, e_y))
    e_zn, exn, eyn = _beam_axes(pts[-2], pts[-1])
    frames.append((e_zn, exn, eyn))
    return frames


def gmsh_wire_from_points(
    points: list[np.ndarray],
    *,
    smooth: bool = True,
) -> int:
    import gmsh

    pts = _as_points(points)
    pt_tags: list[int] = []
    for p in pts:
        pt_tags.append(
            gmsh.model.occ.addPoint(float(p[0]), float(p[1]), float(p[2]))
        )
    if len(pt_tags) == 2 or not smooth:
        line_tags = [
            gmsh.model.occ.addLine(pt_tags[i], pt_tags[i + 1])
            for i in range(len(pt_tags) - 1)
        ]
        return gmsh.model.occ.addWire(line_tags)
    spline = gmsh.model.occ.addSpline(pt_tags)
    return gmsh.model.occ.addWire([spline])


def gmsh_disk_profile_face(
    center: np.ndarray,
    tangent: np.ndarray,
    radius: float,
    *,
    x_axis: np.ndarray | None = None,
) -> int:
    import gmsh

    e_z, e_x, _ = _beam_axes(center, center + np.asarray(tangent, dtype=float))
    if x_axis is not None:
        e_x = np.asarray(x_axis, dtype=float)
        e_x = e_x - float(np.dot(e_x, e_z)) * e_z
        n = float(np.linalg.norm(e_x))
        if n > 1e-12:
            e_x = e_x / n
    return gmsh.model.occ.addDisk(
        float(center[0]),
        float(center[1]),
        float(center[2]),
        float(radius),
        float(radius),
        zAxis=(float(e_z[0]), float(e_z[1]), float(e_z[2])),
        xAxis=(float(e_x[0]), float(e_x[1]), float(e_x[2])),
    )


def gmsh_pipe_along_points(
    points: list[np.ndarray],
    *,
    radius: float,
    trihedron: str = "CorrectedFrenet",
    smooth_wire: bool = True,
) -> int:
    """Sweep a circular profile along a polyline wire; returns volume tag.

    ``smooth_wire=True`` (default) uses a B-spline wire for uniform cylindrical
    sections (CorrectedFrenet + parallel-transport profile).  ``False`` uses the
    raw polyline (more fuse-stable but visible segment faceting in CAD).
    """
    import gmsh

    pts = _as_points(points)
    wire = gmsh_wire_from_points(pts, smooth=smooth_wire)
    frames = frames_along_polyline(pts)
    e_z0, e_x0, _ = frames[0]
    face = gmsh_disk_profile_face(
        pts[0],
        e_z0,
        float(radius),
        x_axis=e_x0,
    )
    out = gmsh.model.occ.addPipe([(2, face)], wire, trihedron=trihedron)
    return occ_volume_tag(out)


def prune_occ_for_step_export() -> int:
    """
    Remove pipe/cylinder construction geometry before STEP write.

    ``addPipe`` / ``addCylinder`` leave free points, edges, wires and profile
    faces in the OCC model.  Gmsh exports each as a separate STEP PRODUCT;
    SolidWorks opens one window per PRODUCT and exhausts GDI handles.

    When only one 3D volume remains (post-fuse export), keep its boundary
    faces — deleting all 2D entities collapses the BREP to ~hundreds of faces
    and breaks FEA self-contact (Abaqus surface intersections at t=0).

    Returns the number of remaining 3D volumes.
    """
    import gmsh

    gmsh.model.occ.synchronize()
    volumes = gmsh.model.getEntities(3)
    keep_faces: set[tuple[int, int]] = set()
    if len(volumes) == 1:
        dim, tag = volumes[0]
        try:
            for bdim, btag in gmsh.model.getBoundary(
                [(int(dim), int(tag))],
                combined=False,
                oriented=False,
                recursive=False,
            ):
                if int(bdim) == 2:
                    keep_faces.add((2, int(btag)))
        except Exception:
            keep_faces = set()

    for dim in (2, 1, 0):
        entities = gmsh.model.getEntities(dim)
        if not entities:
            continue
        if int(dim) == 2 and keep_faces:
            entities = [e for e in entities if (int(e[0]), int(e[1])) not in keep_faces]
            if not entities:
                continue
        try:
            gmsh.model.occ.remove(entities, recursive=True)
        except Exception:
            pass
    gmsh.model.occ.synchronize()
    try:
        gmsh.model.occ.removeAllDuplicates()
        gmsh.model.occ.synchronize()
    except Exception:
        pass
    volumes = gmsh.model.getEntities(3)
    if not volumes:
        raise RuntimeError("STEP export: no 3D volumes remain after OCC prune.")
    return len(volumes)
