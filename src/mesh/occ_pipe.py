"""Gmsh OpenCASCADE pipe sweep along a centerline polyline."""

from __future__ import annotations

import numpy as np

from src.mesh.beam_tet_mesh import _beam_axes


def occ_volume_tag(result: int | tuple | list) -> int:
    if isinstance(result, int):
        return int(result)
    if isinstance(result, (list, tuple)):
        if len(result) == 2 and isinstance(result[0], int):
            return int(result[1])
        if result and isinstance(result[0], (list, tuple)) and len(result[0]) == 2:
            return int(result[0][1])
    raise ValueError(f"Unexpected gmsh OCC pipe return: {result!r}")


def gmsh_wire_from_points(points: list[np.ndarray]) -> int:
    import gmsh

    if len(points) < 2:
        raise ValueError("Wire needs at least two points.")
    pt_tags: list[int] = []
    for p in points:
        pt_tags.append(
            gmsh.model.occ.addPoint(float(p[0]), float(p[1]), float(p[2]))
        )
    line_tags = [
        gmsh.model.occ.addLine(pt_tags[i], pt_tags[i + 1])
        for i in range(len(pt_tags) - 1)
    ]
    return gmsh.model.occ.addWire(line_tags)


def gmsh_disk_profile_face(
    start: np.ndarray,
    end: np.ndarray,
    radius: float,
) -> int:
    import gmsh

    e_z, _, _ = _beam_axes(start, end)
    return gmsh.model.occ.addDisk(
        float(start[0]),
        float(start[1]),
        float(start[2]),
        float(radius),
        float(radius),
        zAxis=(float(e_z[0]), float(e_z[1]), float(e_z[2])),
    )


def gmsh_pipe_along_points(
    points: list[np.ndarray],
    *,
    radius: float,
    trihedron: str = "Frenet",
) -> int:
    """Sweep a circular profile along a polyline wire; returns volume tag."""
    import gmsh

    if len(points) < 2:
        raise ValueError("Pipe path needs at least two points.")
    wire = gmsh_wire_from_points(points)
    p0, p1 = points[0], points[1]
    face = gmsh_disk_profile_face(p0, p1, float(radius))
    out = gmsh.model.occ.addPipe([(2, face)], wire, trihedron=trihedron)
    return occ_volume_tag(out)


def prune_occ_for_step_export() -> int:
    """
    Remove pipe/cylinder construction geometry before STEP write.

    ``addPipe`` / ``addCylinder`` leave free points, edges, wires and profile
    faces in the OCC model.  Gmsh exports each as a separate STEP PRODUCT;
    SolidWorks opens one window per PRODUCT and exhausts GDI handles.

    Returns the number of remaining 3D volumes.
    """
    import gmsh

    gmsh.model.occ.synchronize()
    for dim in (2, 1, 0):
        entities = gmsh.model.getEntities(dim)
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
