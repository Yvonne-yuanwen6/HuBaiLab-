"""Export lattice as STL / STEP / Parasolid X_T solids for SolidWorks."""

from __future__ import annotations

import math
import os
from typing import Iterable

import numpy as np

BeamSegment = dict[str, object]


def _node_dict(nodes: list) -> dict[int, tuple[float, float, float]]:
    return {int(n[0]): (float(n[1]), float(n[2]), float(n[3])) for n in nodes}


def beam_segments(
    nodes: list,
    beams: list,
    scale: float = 1.0,
) -> list[BeamSegment]:
    """Convert nodes/beams to centerline segments with scaled radius."""
    lookup = _node_dict(nodes)
    segments: list[BeamSegment] = []

    for beam in beams:
        bid, n1, n2, radius, btype = beam
        p1 = lookup[int(n1)]
        p2 = lookup[int(n2)]
        segments.append(
            {
                "id": int(bid),
                "p1": tuple(v * scale for v in p1),
                "p2": tuple(v * scale for v in p2),
                "radius": float(radius) * scale,
                "type": str(btype),
            }
        )

    return segments


def _segment_trimesh_cylinder(
    p1: tuple[float, float, float],
    p2: tuple[float, float, float],
    radius: float,
    resolution: int = 16,
):
    """Watertight cylinder solid for boolean union (trimesh + manifold)."""
    import trimesh

    start = np.asarray(p1, dtype=float)
    end = np.asarray(p2, dtype=float)
    axis = end - start
    height = float(np.linalg.norm(axis))
    if height < 1e-12:
        return None

    direction = axis / height
    cyl = trimesh.creation.cylinder(
        radius=float(radius),
        height=height,
        sections=resolution,
    )
    cyl.apply_transform(trimesh.geometry.align_vectors([0.0, 0.0, 1.0], direction, False))
    cyl.apply_translation((start + end) / 2.0)
    return cyl


def _four_corner_sphere_meshes(
    nodes: list,
    r_frame: float,
    scale: float,
    resolution: int = 16,
    *,
    nz: int | None = None,
    cell_size: float | None = None,
    include_top: bool = True,
) -> list:
    """
    Spheres at the four outer corners on bottom and top frame faces.

    Same radius as frame; used to fill right-angle gaps after boolean union.
    Top Z uses nz * cell_size (top of outer cube frame), not O-point height.
    """
    import trimesh

    if not nodes:
        return []

    pts = np.array(
        [[float(n[1]) * scale, float(n[2]) * scale, float(n[3]) * scale] for n in nodes],
        dtype=float,
    )
    xmin, ymin = float(pts[:, 0].min()), float(pts[:, 1].min())
    xmax, ymax = float(pts[:, 0].max()), float(pts[:, 1].max())
    z_min = float(pts[:, 2].min())

    z_levels = [z_min]
    if include_top:
        if nz is not None and cell_size is not None:
            z_top = float(nz) * float(cell_size) * scale
        else:
            z_top = float(pts[:, 2].max())
        if abs(z_top - z_min) > max(1e-6, 1e-4 * scale):
            z_levels.append(z_top)

    corner_xy = [(xmin, ymin), (xmax, ymin), (xmax, ymax), (xmin, ymax)]
    centers: list[tuple[float, float, float]] = [
        (cx, cy, z) for z in z_levels for cx, cy in corner_xy
    ]

    radius = float(r_frame) * scale
    subdiv = 3 if resolution >= 20 else 2
    spheres: list = []
    for center in centers:
        sphere = trimesh.creation.icosphere(subdivisions=subdiv, radius=radius)
        sphere.apply_translation(center)
        spheres.append(sphere)
    return spheres


def _union_meshes_tree(meshes: list, *, progress_label: str | None = None) -> object:
    """Pairwise boolean union for large lattice blocks."""
    import trimesh

    level = [m for m in meshes if m is not None]
    if not level:
        raise ValueError("No meshes to union.")
    step = 0
    while len(level) > 1:
        nxt: list = []
        for i in range(0, len(level), 2):
            if i + 1 < len(level):
                nxt.append(trimesh.boolean.union([level[i], level[i + 1]], engine="manifold"))
            else:
                nxt.append(level[i])
        step += 1
        if progress_label:
            print(f"  {progress_label}: level {step}, {len(level)} → {len(nxt)} parts")
        level = nxt
    return level[0]


def _union_all_meshes(meshes: list) -> object:
    """Boolean union — single SolidWorks solid."""
    import trimesh

    if len(meshes) == 1:
        return meshes[0]
    if len(meshes) <= 48:
        return trimesh.boolean.union(meshes, engine="manifold")
    return _union_meshes_tree(meshes, progress_label="union")


def export_stl_solids(
    segments: Iterable[BeamSegment],
    path: str,
    resolution: int = 16,
    *,
    nodes: list | None = None,
    r_frame: float | None = None,
    scale: float = 1.0,
    add_corner_spheres: bool = True,
    nz: int | None = None,
    cell_size: float | None = None,
) -> None:
    """Export boolean-unioned tube solids as STL for SolidWorks."""
    try:
        import trimesh  # noqa: F401
    except ImportError as exc:
        raise ImportError(
            "STL export requires trimesh and manifold3d. "
            "Install: pip install trimesh manifold3d"
        ) from exc

    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    segment_list = list(segments)

    trimesh_meshes: list = []
    if add_corner_spheres and nodes is not None and r_frame is not None:
        trimesh_meshes.extend(
            _four_corner_sphere_meshes(
                nodes,
                r_frame,
                scale,
                resolution=resolution,
                nz=nz,
                cell_size=cell_size,
            )
        )

    for seg in segment_list:
        mesh = _segment_trimesh_cylinder(
            seg["p1"], seg["p2"], float(seg["radius"]), resolution=resolution
        )
        if mesh is not None:
            trimesh_meshes.append(mesh)

    if not trimesh_meshes:
        raise ValueError("No beam solids to export.")

    combined = _union_all_meshes(trimesh_meshes)
    combined.export(path)


def export_sw_solid(
    nodes: list,
    beams: list,
    output_dir: str,
    prefix: str = "lattice",
    scale: float = 1.0,
    resolution: int = 16,
    *,
    r_frame: float | None = None,
    add_corner_spheres: bool = True,
    nz: int | None = None,
    cell_size: float | None = None,
) -> str:
    """
    Export one STL solid for SolidWorks (File → Open → Form solid).

    Uses boolean union at beam centerlines; right-angle joints may retain
    small corner gaps (tube-end artifacts) but import as one solid body.
    """
    os.makedirs(output_dir, exist_ok=True)
    segments = beam_segments(nodes, beams, scale=scale)
    stl_path = os.path.join(output_dir, f"{prefix}_solid.stl")
    export_stl_solids(
        segments,
        stl_path,
        resolution=resolution,
        nodes=nodes,
        r_frame=r_frame,
        scale=scale,
        add_corner_spheres=add_corner_spheres,
        nz=nz,
        cell_size=cell_size,
    )
    return stl_path


def _facet_list_append(facets: list, v0, v1, v2) -> None:
    facets.append(
        (
            np.asarray(v0, dtype=float),
            np.asarray(v1, dtype=float),
            np.asarray(v2, dtype=float),
        )
    )


def _cylinder_facets(
    p0: np.ndarray | list[float],
    p1: np.ndarray | list[float],
    radius: float,
    *,
    n_theta: int = 16,
) -> list[tuple[np.ndarray, np.ndarray, np.ndarray]]:
    """Watertight cylinder (side + caps) as triangle list."""
    p0a = np.asarray(p0, dtype=float)
    p1a = np.asarray(p1, dtype=float)
    axis = p1a - p0a
    height = float(np.linalg.norm(axis))
    if height < 1e-12 or radius <= 0.0:
        return []

    ez = axis / height
    ref = np.array([0.0, 0.0, 1.0])
    if abs(float(np.dot(ez, ref))) > 0.9:
        ref = np.array([1.0, 0.0, 0.0])
    ex = np.cross(ez, ref)
    ex /= float(np.linalg.norm(ex))
    ey = np.cross(ez, ex)

    ring0: list[np.ndarray] = []
    ring1: list[np.ndarray] = []
    for i in range(n_theta):
        ang = 2.0 * math.pi * i / n_theta
        off = float(radius) * (math.cos(ang) * ex + math.sin(ang) * ey)
        ring0.append(p0a + off)
        ring1.append(p1a + off)

    facets: list[tuple[np.ndarray, np.ndarray, np.ndarray]] = []
    for i in range(n_theta):
        j = (i + 1) % n_theta
        _facet_list_append(facets, ring0[i], ring0[j], ring1[j])
        _facet_list_append(facets, ring0[i], ring1[j], ring1[i])
        _facet_list_append(facets, p0a, ring0[j], ring0[i])
        _facet_list_append(facets, p1a, ring1[i], ring1[j])
    return facets


def _sphere_facets(
    center: np.ndarray | list[float],
    radius: float,
    *,
    n_lat: int = 8,
    n_lon: int = 16,
) -> list[tuple[np.ndarray, np.ndarray, np.ndarray]]:
    """UV-sphere as triangle list."""
    c = np.asarray(center, dtype=float)
    r = float(radius)
    if r <= 0.0:
        return []

    def point(theta: float, phi: float) -> np.ndarray:
        st = math.sin(theta)
        return c + r * np.array([st * math.cos(phi), st * math.sin(phi), math.cos(theta)])

    facets: list[tuple[np.ndarray, np.ndarray, np.ndarray]] = []
    for i in range(n_lat):
        t0 = math.pi * i / n_lat
        t1 = math.pi * (i + 1) / n_lat
        for j in range(n_lon):
            p0 = 2.0 * math.pi * j / n_lon
            p1 = 2.0 * math.pi * (j + 1) / n_lon
            a = point(t0, p0)
            b = point(t0, p1)
            cpt = point(t1, p1)
            d = point(t1, p0)
            _facet_list_append(facets, a, b, cpt)
            _facet_list_append(facets, a, cpt, d)
    return facets


def write_ascii_stl(path: str, facets: list[tuple[np.ndarray, np.ndarray, np.ndarray]], *, name: str = "lattice") -> None:
    """Write concatenated triangle soup as ASCII STL (no boolean union)."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"solid {name}\n")
        for v0, v1, v2 in facets:
            n = np.cross(v1 - v0, v2 - v0)
            nlen = float(np.linalg.norm(n))
            if nlen > 1e-15:
                n = n / nlen
            else:
                n = np.array([0.0, 0.0, 1.0])
            f.write(f"  facet normal {n[0]:.6e} {n[1]:.6e} {n[2]:.6e}\n")
            f.write("    outer loop\n")
            for v in (v0, v1, v2):
                f.write(f"      vertex {v[0]:.6e} {v[1]:.6e} {v[2]:.6e}\n")
            f.write("    endloop\n")
            f.write("  endfacet\n")
        f.write(f"endsolid {name}\n")


def export_lattice_stl_concat(
    nodes: list,
    beams: list,
    path: str,
    *,
    polylines: list[dict] | None = None,
    n_theta: int = 16,
    n_sphere_lat: int = 8,
    n_sphere_lon: int = 16,
    junction_spheres: bool = True,
) -> dict[str, int | float]:
    """
    Export lattice as one STL file by merging cylinder/sphere meshes (no boolean union).

    Fast and does not require trimesh. Junction spheres overlap strut ends so
    SolidWorks can often form one solid (Import → Try to form solid).
    """
    from src.mesh.junction_mesh import collect_solid_junction_radii, effective_solid_radius
    from src.mesh.solid_profiles import SOLID_SKIP_BEAM_TYPES, polyline_mesh_profile

    lookup = {int(n[0]): np.array([float(n[1]), float(n[2]), float(n[3])]) for n in nodes}
    facets: list[tuple[np.ndarray, np.ndarray, np.ndarray]] = []

    if junction_spheres:
        for nid, radius in collect_solid_junction_radii(nodes, beams, polylines).items():
            center = lookup.get(int(nid))
            if center is not None and radius > 0.0:
                facets.extend(
                    _sphere_facets(
                        center,
                        radius,
                        n_lat=n_sphere_lat,
                        n_lon=n_sphere_lon,
                    )
                )

    for _bid, n1, n2, radius, btype in beams:
        if str(btype) in SOLID_SKIP_BEAM_TYPES:
            continue
        r = effective_solid_radius(radius=float(radius), profile="circle")
        facets.extend(_cylinder_facets(lookup[int(n1)], lookup[int(n2)], r, n_theta=n_theta))

    if polylines:
        for poly in polylines:
            node_ids = [int(n) for n in poly["nodes"]]
            prof = polyline_mesh_profile(poly)
            if prof["profile"] == "square":
                r = effective_solid_radius(profile="square", square_half=prof["square_half"])
            else:
                r = effective_solid_radius(radius=prof["radius"], profile="circle")
            for i in range(len(node_ids) - 1):
                facets.extend(
                    _cylinder_facets(
                        lookup[node_ids[i]],
                        lookup[node_ids[i + 1]],
                        r,
                        n_theta=n_theta,
                    )
                )

    if not facets:
        raise ValueError("No solid facets to export.")

    write_ascii_stl(path, facets, name=os.path.splitext(os.path.basename(path))[0])
    return {
        "facet_count": len(facets),
        "node_count": len(nodes),
        "beam_count": len(beams),
        "polyline_count": len(polylines or []),
    }


def _occ_volume_dimtag(result: int | tuple | list) -> tuple[int, int]:
    """Normalize gmsh OCC primitive return value to (dim, tag)."""
    if isinstance(result, int):
        return (3, result)
    if isinstance(result, (list, tuple)):
        if len(result) == 2 and isinstance(result[0], int) and isinstance(result[1], int):
            return (int(result[0]), int(result[1]))
        if result and isinstance(result[0], (list, tuple)) and len(result[0]) == 2:
            return (int(result[0][0]), int(result[0][1]))
    raise ValueError(f"Unexpected gmsh OCC return value: {result!r}")


def _collect_solid_primitives(
    nodes: list,
    beams: list,
    *,
    polylines: list[dict] | None = None,
    junction_spheres: bool = True,
    trim_for_junctions: bool | None = None,
    polyline_sweep: str = "cylinder",
    polyline_endpoints_only: bool = False,
) -> tuple[dict[int, np.ndarray], list[tuple[str, tuple, float]]]:
    """
    Return node lookup and analytic primitives.

    Kinds: ``sphere``, ``cylinder``, or ``pipe`` (centerline points + radius).
    """
    from src.mesh.junction_mesh import (
        collect_solid_junction_radii,
        effective_solid_radius,
        trim_beam_endpoints,
    )
    from src.mesh.solid_profiles import SOLID_SKIP_BEAM_TYPES, polyline_mesh_profile

    if trim_for_junctions is None:
        trim_for_junctions = junction_spheres

    lookup = {int(n[0]): np.array([float(n[1]), float(n[2]), float(n[3])]) for n in nodes}
    parts: list[tuple[str, tuple, float]] = []
    use_pipe = str(polyline_sweep).lower() == "pipe"

    junction_r: dict[int, float] = {}
    if junction_spheres or trim_for_junctions:
        junction_r = collect_solid_junction_radii(
            nodes,
            beams,
            polylines,
            polyline_endpoints_only=use_pipe or polyline_endpoints_only,
        )

    if junction_spheres:
        for nid, radius in junction_r.items():
            center = lookup.get(int(nid))
            if center is not None and radius > 0.0:
                parts.append(("sphere", tuple(center), float(radius)))

    for _bid, n1, n2, radius, btype in beams:
        if str(btype) in SOLID_SKIP_BEAM_TYPES:
            continue
        r = effective_solid_radius(radius=float(radius), profile="circle")
        p1 = lookup[int(n1)]
        p2 = lookup[int(n2)]
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
        parts.append(("cylinder", tuple(p1), tuple(p2), r))

    if polylines:
        for poly in polylines:
            node_ids = [int(n) for n in poly["nodes"]]
            prof = polyline_mesh_profile(poly)
            if prof["profile"] == "square":
                r = effective_solid_radius(profile="square", square_half=prof["square_half"])
            else:
                r = effective_solid_radius(radius=prof["radius"], profile="circle")
            if use_pipe:
                if len(node_ids) < 2:
                    continue
                path = tuple(tuple(lookup[nid]) for nid in node_ids)
                parts.append(("pipe", path, r))
                continue
            for i in range(len(node_ids) - 1):
                pa = lookup[node_ids[i]]
                pb = lookup[node_ids[i + 1]]
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
                parts.append(("cylinder", tuple(pa), tuple(pb), r))

    return lookup, parts


def _fuse_occ_all(dimtags: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Fuse OCC volumes in batches ≤256 (gmsh occ.fuse limit)."""
    import gmsh

    current = list(dimtags)
    if len(current) <= 1:
        return current

    chunk = 256
    while len(current) > 1:
        if len(current) <= chunk:
            fused, _ = gmsh.model.occ.fuse([current[0]], current[1:])
            gmsh.model.occ.synchronize()
            return list(fused)
        nxt: list[tuple[int, int]] = []
        for i in range(0, len(current), chunk):
            batch = current[i : i + chunk]
            if len(batch) == 1:
                nxt.append(batch[0])
                continue
            fused, _ = gmsh.model.occ.fuse([batch[0]], batch[1:])
            nxt.extend(fused)
        gmsh.model.occ.synchronize()
        current = nxt
    return current


def _fuse_occ_tree(dimtags: list[tuple[int, int]], *, progress_label: str | None = None) -> list[tuple[int, int]]:
    """Deprecated alias — use :func:`_fuse_occ_all`."""
    return _fuse_occ_all(dimtags)


# gmsh OCC batch-fuse fails silently above ~256 disjoint cylinders; tree-fuse fails on 4×4×4.
OCC_FUSE_MAX_PARTS = 256


def _next_occ_volume_tag() -> int:
    """First unused 3D OCC tag in the active gmsh model."""
    import gmsh

    max_tag = 0
    for dim in (0, 1, 2, 3):
        for _, t in gmsh.model.getEntities(dim):
            max_tag = max(max_tag, int(t))
    return max_tag + 1


def _occ_dimtags_from_parts(
    parts: list[tuple[str, tuple, float]],
    *,
    tag_start: int | None = None,
) -> list[tuple[int, int]]:
    """Create OCC volume dimtags from analytic primitives (active gmsh model)."""
    from src.mesh.occ_pipe import gmsh_pipe_along_points

    import gmsh

    dimtags: list[tuple[int, int]] = []
    tag = int(tag_start) if tag_start is not None else _next_occ_volume_tag()
    for kind, *payload in parts:
        if kind == "sphere":
            center, radius = payload
            cx, cy, cz = center
            dimtags.append(
                _occ_volume_dimtag(
                    gmsh.model.occ.addSphere(cx, cy, cz, float(radius), tag=tag)
                )
            )
        elif kind == "pipe":
            path_pts, radius = payload
            points = [np.asarray(p, dtype=float) for p in path_pts]
            if len(points) < 2 or float(radius) <= 0.0:
                tag += 1
                continue
            vol_tag = gmsh_pipe_along_points(points, radius=float(radius))
            dimtags.append((3, int(vol_tag)))
        else:
            p1, p2, radius = payload
            a = np.asarray(p1, dtype=float)
            b = np.asarray(p2, dtype=float)
            axis = b - a
            length = float(np.linalg.norm(axis))
            if length < 1e-12 or float(radius) <= 0.0:
                tag += 1
                continue
            dimtags.append(
                _occ_volume_dimtag(
                    gmsh.model.occ.addCylinder(
                        float(a[0]),
                        float(a[1]),
                        float(a[2]),
                        float(axis[0]),
                        float(axis[1]),
                        float(axis[2]),
                        float(radius),
                        tag=tag,
                    )
                )
            )
        tag += 1
    return dimtags


def _occ_fuse_dimtags(dimtags: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Boolean-union OCC volumes; returns fused volume dimtags."""
    import gmsh

    if len(dimtags) <= 1:
        return list(dimtags)
    _configure_occ_for_fuse()
    if len(dimtags) <= OCC_FUSE_MAX_PARTS:
        fused, _ = gmsh.model.occ.fuse([dimtags[0]], dimtags[1:])
    else:
        fused = _fuse_occ_all(dimtags)
    gmsh.model.occ.synchronize()
    return list(fused)


def _fuse_occ_layer_volumes(
    dimtags: list[tuple[int, int]],
    *,
    progress_label: str = "inter-layer",
) -> list[tuple[int, int]]:
    """Pairwise tree fuse of pre-merged layer solids; batch fallback on stall."""
    import gmsh

    current = list(dimtags)
    if len(current) <= 1:
        return current
    if len(current) <= 8:
        return _occ_fuse_dimtags(current)

    level = 0
    max_levels = max(32, len(current) * 2)
    while len(current) > 1:
        nxt: list[tuple[int, int]] = []
        for i in range(0, len(current), 2):
            if i + 1 < len(current):
                fused, _ = gmsh.model.occ.fuse([current[i]], [current[i + 1]])
                gmsh.model.occ.synchronize()
                nxt.extend(fused)
            else:
                nxt.append(current[i])
        level += 1
        print(
            f"  {progress_label}: level {level}, {len(current)} → {len(nxt)} volume(s)",
            flush=True,
        )
        if len(nxt) >= len(current):
            print(
                f"  {progress_label}: pairwise stall at {len(nxt)} volume(s), "
                f"batch fuse...",
                flush=True,
            )
            return _occ_fuse_dimtags(current)
        if level >= max_levels:
            print(
                f"  {progress_label}: max levels ({max_levels}), batch fuse...",
                flush=True,
            )
            return _occ_fuse_dimtags(current)
        current = nxt
    return current


def _occ_primary_volume(dimtags: list[tuple[int, int]]) -> tuple[int, int]:
    if not dimtags:
        raise RuntimeError("OCC fuse produced no volume.")
    if len(dimtags) == 1:
        return dimtags[0]
    fused = _fuse_occ_layer_volumes(dimtags, progress_label="occ-residual")
    return _occ_primary_volume(fused)


def _occ_list_volume_dimtags() -> list[tuple[int, int]]:
    import gmsh

    return [(3, int(t)) for dim, t in gmsh.model.getEntities(3) if dim == 3]


def _require_single_fused_volume(
    *,
    progress_label: str,
    stage: str,
) -> tuple[int, int]:
    from src.mesh.occ_pipe import prune_occ_for_step_export

    vols = _occ_list_volume_dimtags()
    if len(vols) == 1:
        return vols[0]
    if not vols:
        raise RuntimeError(f"{progress_label}: {stage} produced no volume.")

    print(
        f"  {progress_label}: {stage} unify {len(vols)} volume(s)...",
        flush=True,
    )
    _occ_fuse_dimtags(vols)
    prune_occ_for_step_export()
    vols = _occ_list_volume_dimtags()
    if len(vols) == 1:
        return vols[0]
    raise RuntimeError(
        f"{progress_label}: {stage} produced {len(vols)} volume(s), expected 1."
    )


def _fuse_layer_step_files_sequential(
    layer_step_paths: list[str],
    *,
    progress_label: str = "inter-layer",
) -> str:
    """Merge z-slab STEP files two-at-a-time in isolated gmsh sessions."""
    import gmsh

    from src.mesh.occ_pipe import prune_occ_for_step_export

    paths = [os.path.abspath(p) for p in layer_step_paths]
    if not paths:
        raise ValueError("layer_step_paths is empty.")
    if len(paths) == 1:
        return paths[0]

    layer_dir = os.path.dirname(paths[0]) or "."
    acc = paths[0]

    for idx in range(1, len(paths)):
        merge_path = os.path.join(layer_dir, f".__merge_through_{idx}.step")
        print(f"  {progress_label}: fuse through slab {idx}...", flush=True)
        gmsh.initialize()
        try:
            gmsh.option.setNumber("General.Terminal", 0)
            _configure_occ_for_fuse()
            gmsh.model.add(f"slab_merge_{idx}")
            gmsh.model.occ.importShapes(acc)
            gmsh.model.occ.importShapes(paths[idx])
            gmsh.model.occ.synchronize()

            vols = _occ_list_volume_dimtags()
            if len(vols) != 2:
                raise RuntimeError(
                    f"{progress_label}: expected 2 imported slab volumes, "
                    f"got {len(vols)}"
                )
            _occ_fuse_dimtags(vols)
            prune_occ_for_step_export()
            _require_single_fused_volume(
                progress_label=progress_label,
                stage=f"after slab {idx}",
            )
            gmsh.write(merge_path)
        finally:
            gmsh.finalize()

        acc = merge_path

    return acc


def _fuse_unitcell_array_inter_cell(
    cell_volumes: list[tuple[int, int]],
    *,
    nx: int,
    ny: int,
    nz: int,
    progress_label: str = "inter-cell",
) -> None:
    """
    Fuse translated unit-cell solids without crashing gmsh OCC on SFBLS arrays.

    Strategy: within each z-slab, fuse 2×2 spatial blocks (pairwise tree), then
    union blocks; finally pairwise-merge the nz slab solids. Batch fuse of 16 complex
    curved cells still segfaults; hierarchical 4-cell blocks are stable in practice.
    """
    from src.mesh.occ_pipe import prune_occ_for_step_export

    n = len(cell_volumes)
    if n <= 1:
        return

    nx_i, ny_i, nz_i = int(nx), int(ny), int(nz)
    if nx_i * ny_i * nz_i != n:
        print(f"  {progress_label}: batch fuse {n} volume(s)...", flush=True)
        _occ_fuse_dimtags(cell_volumes)
        return

    if n <= 4:
        _fuse_occ_layer_volumes(cell_volumes, progress_label=progress_label)
        return

    block_nx = min(2, nx_i)
    block_ny = min(2, ny_i)

    slab_cells: list[list[tuple[int, int]]] = [[] for _ in range(nz_i)]
    idx = 0
    for iz in range(nz_i):
        for _iy in range(ny_i):
            for _ix in range(nx_i):
                slab_cells[iz].append(cell_volumes[idx])
                idx += 1

    slab_vols: list[tuple[int, int]] = []
    for iz, cells in enumerate(slab_cells):
        if len(cells) == 1:
            slab_vols.append(cells[0])
            continue

        print(
            f"  {progress_label}: z-slab {iz} fuse {len(cells)} cell(s) "
            f"({block_nx}x{block_ny} blocks)...",
            flush=True,
        )
        block_vols: list[tuple[int, int]] = []
        for by in range(0, ny_i, block_ny):
            for bx in range(0, nx_i, block_nx):
                block: list[tuple[int, int]] = []
                for iy in range(by, min(by + block_ny, ny_i)):
                    for ix in range(bx, min(bx + block_nx, nx_i)):
                        block.append(cells[iy * nx_i + ix])
                if len(block) == 1:
                    block_vols.append(block[0])
                    continue
                blk_label = f"{progress_label}-z{iz}-b{bx // block_nx}_{by // block_ny}"
                fused_blk = _fuse_occ_layer_volumes(block, progress_label=blk_label)
                prune_occ_for_step_export()
                block_vols.append(_occ_primary_volume(fused_blk))

        if len(block_vols) == 1:
            slab_vols.append(block_vols[0])
        else:
            slab_label = f"{progress_label}-z{iz}-slab"
            fused_slab = _fuse_occ_layer_volumes(block_vols, progress_label=slab_label)
            prune_occ_for_step_export()
            slab_vols.append(_occ_primary_volume(fused_slab))

    if len(slab_vols) <= 1:
        return

    print(
        f"  {progress_label}: inter-slab fuse {len(slab_vols)} slab(s)...",
        flush=True,
    )
    _fuse_occ_layer_volumes(slab_vols, progress_label=f"{progress_label}-slab")


def export_fused_stl(
    nodes: list,
    beams: list,
    stl_path: str,
    *,
    polylines: list[dict] | None = None,
    resolution: int = 12,
    junction_spheres: bool = True,
) -> dict[str, int | float | bool | str]:
    """Single watertight STL via trimesh/manifold boolean union (large blocks)."""
    from src.mesh.solid_union import export_union_stl

    print("  trimesh boolean union (may take a few minutes)...", flush=True)
    stats = export_union_stl(
        nodes,
        beams,
        stl_path,
        polylines=polylines,
        resolution=resolution,
        junction_spheres=junction_spheres,
    )
    stats["fused_stl"] = stl_path
    stats["method"] = "trimesh_union"
    return stats


def _configure_occ_for_fuse() -> None:
    """Tighten OCC boolean + healing so STEP imports cleaner into Abaqus."""
    import gmsh

    for opt, val in (
        ("Geometry.Tolerance", 1e-5),
        ("Geometry.ToleranceBoolean", 1e-5),
        ("Geometry.OCCFixDegenerated", 1),
        ("Geometry.OCCFixSmallEdges", 1),
        ("Geometry.OCCFixSmallFaces", 1),
        ("Geometry.OCCSewFaces", 1),
    ):
        try:
            gmsh.option.setNumber(opt, val)
        except Exception:
            pass


def _finalize_occ_step_write(
    path: str,
    *,
    fuse: bool,
) -> dict[str, int | bool | str]:
    """Prune construction geometry, write STEP, validate SolidWorks safety."""
    import gmsh

    from src.export.sw_parasolid import analyze_step_for_solidworks
    from src.mesh.occ_pipe import prune_occ_for_step_export

    n_volumes = prune_occ_for_step_export()
    gmsh.write(path)

    return analyze_step_for_solidworks(
        path,
        expected_volumes=n_volumes,
        fused_single=fuse,
        require_advanced_brep=fuse,
    )


def export_lattice_step_occ(
    nodes: list,
    beams: list,
    path: str,
    *,
    polylines: list[dict] | None = None,
    junction_spheres: bool = True,
    fuse: bool = False,
    polyline_sweep: str | None = None,
) -> dict[str, int | float | bool | str]:
    """
    Export analytic rod/sphere BREP as STEP via gmsh OpenCASCADE.

    ``fuse=False`` (default): multi-body compound, fast — matches STL concat mode.
    ``fuse=True``: boolean union into one solid (junction spheres + overlapping struts).

    Polylines default to ``pipe`` sweep (one OCC volume per curved strut). Pass
    ``polyline_sweep="cylinder"`` to restore the legacy per-segment cylinder chain.
    """
    try:
        import gmsh
    except ImportError as exc:
        raise ImportError(
            "STEP/X_T export requires gmsh. Install: pip install gmsh"
        ) from exc

    use_junction = junction_spheres
    # Trimmed struts leave micro-gaps at spheres → OCC fuse yields 90+ disjoint solids
    # (SW runs out of window resources opening the STEP). Overlapping strut+sphere → 1 solid.
    trim_ends = False
    if polyline_sweep is None:
        polyline_sweep = "pipe" if polylines else "cylinder"
    use_pipe = str(polyline_sweep).lower() == "pipe"

    _, parts = _collect_solid_primitives(
        nodes,
        beams,
        polylines=polylines,
        junction_spheres=use_junction,
        trim_for_junctions=trim_ends,
        polyline_sweep=polyline_sweep,
    )
    if not parts:
        raise ValueError("No solid primitives to export.")

    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)

    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add(os.path.splitext(os.path.basename(path))[0] or "lattice")

        dimtags = _occ_dimtags_from_parts(parts)
        if not dimtags:
            raise ValueError("No OCC solids were created.")

        gmsh.model.occ.synchronize()
        if fuse:
            n_parts = len(dimtags)
            sweep_label = "pipe sweep" if use_pipe else "cylinder chain"
            print(
                f"  Boolean fuse: {n_parts} OCC solids "
                f"({sweep_label}, junction spheres={'on' if use_junction else 'off'}, "
                f"trimmed struts={'on' if trim_ends else 'off'})...",
                flush=True,
            )
            if n_parts > 1:
                _occ_fuse_dimtags(dimtags)
                n_vol = len(gmsh.model.getEntities(3))
                if not n_vol:
                    raise RuntimeError(
                        "OCC fuse produced no volume; STEP would be empty. "
                        "Try --skip-xt and import *_solid.stl, or use --union for fused STL."
                    )
                if n_vol != 1:
                    print(
                        f"  [WARN] Fuse produced {n_vol} separate solids (expected 1). "
                        "SolidWorks may run out of window resources; use Abaqus STEP import or B31 INP.",
                        flush=True,
                    )
            print("  Fuse complete.", flush=True)

        if not fuse and len(parts) > 1:
            print(
                f"  [WARN] Multi-body STEP ({len(parts)} primitives, fuse=False). "
                "SolidWorks may open many windows — use fuse=True for single-body export.",
                flush=True,
            )

        step_report = _finalize_occ_step_write(path, fuse=fuse)
        fused_volume_count = int(step_report.get("solid_count", 0))
    finally:
        gmsh.finalize()

    pipe_count = sum(1 for k, *_ in parts if k == "pipe")
    return {
        "step_path": path,
        "solid_count": len(parts),
        "pipe_count": pipe_count,
        "polyline_sweep": polyline_sweep,
        "fused": bool(fuse),
        "fused_volume_count": fused_volume_count,
        "step_product_count": step_report.get("product_count"),
        "step_solidworks_safe": step_report.get("solidworks_safe"),
        "node_count": len(nodes),
        "beam_count": len(beams),
        "polyline_count": len(polylines or []),
        "method": "gmsh_occ_pipe" if use_pipe and pipe_count else "gmsh_occ_step",
    }


def _lattice_cell_center_mm(index: int, count: int, cell_size: float) -> float:
    """Origin-centred cell centre coordinate (matches HuBaiLatticeGenerator)."""
    return (int(index) - (int(count) - 1) / 2.0) * float(cell_size)


def export_lattice_step_occ_unitcell_array(
    nodes: list,
    beams: list,
    path: str,
    *,
    nx: int,
    ny: int,
    nz: int,
    cell_size: float,
    polylines: list[dict] | None = None,
    junction_spheres: bool = True,
    polyline_sweep: str | None = None,
) -> dict[str, int | float | bool | str | list]:
    """
    Fused STEP via unit-cell template + OCC translate/array + boolean union.

    Builds and fuses one ``1×1×1`` cell (centre at origin), copies it to each
    origin-centred grid position, then fuses all cell solids into one body.
    Much faster than per-strut primitive fuse for large periodic blocks (e.g. 4×4×4).

    ``nodes`` / ``beams`` / ``polylines`` must describe a single unit cell only.
    """
    try:
        import gmsh
    except ImportError as exc:
        raise ImportError(
            "STEP/X_T export requires gmsh. Install: pip install gmsh"
        ) from exc

    from src.mesh.occ_pipe import prune_occ_for_step_export

    nx_i, ny_i, nz_i = int(nx), int(ny), int(nz)
    if nx_i < 1 or ny_i < 1 or nz_i < 1:
        raise ValueError(f"nx/ny/nz must be >= 1, got {nx_i}x{ny_i}x{nz_i}")
    cell_l = float(cell_size)
    if cell_l <= 0.0:
        raise ValueError(f"cell_size must be positive, got {cell_l}")

    use_junction = junction_spheres
    trim_ends = False
    if polyline_sweep is None:
        polyline_sweep = "pipe" if polylines else "cylinder"
    use_pipe = str(polyline_sweep).lower() == "pipe"

    _, parts = _collect_solid_primitives(
        nodes,
        beams,
        polylines=polylines,
        junction_spheres=use_junction,
        trim_for_junctions=trim_ends,
        polyline_sweep=polyline_sweep,
    )
    if not parts:
        raise ValueError("No solid primitives for unit cell.")

    cell_offsets: list[tuple[float, float, float]] = []
    for iz in range(nz_i):
        for iy in range(ny_i):
            for ix in range(nx_i):
                cell_offsets.append(
                    (
                        _lattice_cell_center_mm(ix, nx_i, cell_l),
                        _lattice_cell_center_mm(iy, ny_i, cell_l),
                        _lattice_cell_center_mm(iz, nz_i, cell_l),
                    )
                )

    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    n_cells = len(cell_offsets)

    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add(os.path.splitext(os.path.basename(path))[0] or "lattice_uc_array")

        dimtags = _occ_dimtags_from_parts(parts)
        if not dimtags:
            raise ValueError("No OCC solids were created for unit cell.")

        gmsh.model.occ.synchronize()
        n_uc_parts = len(dimtags)
        sweep_label = "pipe sweep" if use_pipe else "cylinder chain"
        print(
            f"  Unit cell fuse: {n_uc_parts} OCC solids "
            f"({sweep_label}, junction spheres={'on' if use_junction else 'off'})...",
            flush=True,
        )
        if n_uc_parts > 1:
            _occ_fuse_dimtags(dimtags)
        prune_occ_for_step_export()

        seed_vols = [(3, int(t)) for dim, t in gmsh.model.getEntities(3) if dim == 3]
        if len(seed_vols) != 1:
            raise RuntimeError(
                f"Unit cell fuse produced {len(seed_vols)} volume(s), expected 1."
            )
        seed_vol = seed_vols[0]
        print("  Unit cell fuse complete.", flush=True)

        cell_volumes: list[tuple[int, int]] = []
        for idx, (dx, dy, dz) in enumerate(cell_offsets):
            if abs(dx) < 1e-9 and abs(dy) < 1e-9 and abs(dz) < 1e-9:
                cell_volumes.append(seed_vol)
                continue
            copied = list(gmsh.model.occ.copy([seed_vol]))
            gmsh.model.occ.translate(copied, float(dx), float(dy), float(dz))
            gmsh.model.occ.synchronize()
            cell_volumes.extend(copied)

        print(
            f"  Array: {n_cells} cell solid(s) "
            f"({nx_i}x{ny_i}x{nz_i}, L={cell_l:.3g} mm)...",
            flush=True,
        )
        if n_cells > 1:
            print(f"  Inter-cell fuse: {len(cell_volumes)} volume(s)...", flush=True)
            _fuse_unitcell_array_inter_cell(
                cell_volumes,
                nx=nx_i,
                ny=ny_i,
                nz=nz_i,
                progress_label="inter-cell",
            )
            prune_occ_for_step_export()

        n_vol = len(gmsh.model.getEntities(3))
        if not n_vol:
            raise RuntimeError(
                "Unit-cell array fuse produced no volume; STEP would be empty."
            )
        if n_vol != 1:
            print(
                f"  [WARN] Array fuse produced {n_vol} separate solids (expected 1).",
                flush=True,
            )
        print("  Array fuse complete.", flush=True)

        step_report = _finalize_occ_step_write(path, fuse=True)
        fused_volume_count = int(step_report.get("solid_count", 0))
        xmin, ymin, zmin, xmax, ymax, zmax = _occ_imported_volume_bbox()
    finally:
        gmsh.finalize()

    pipe_count = sum(1 for k, *_ in parts if k == "pipe")
    return {
        "step_path": path,
        "solid_count": n_uc_parts,
        "unitcell_primitive_count": n_uc_parts,
        "cell_count": n_cells,
        "pipe_count": pipe_count,
        "polyline_sweep": polyline_sweep,
        "fused": True,
        "fused_volume_count": fused_volume_count,
        "step_product_count": step_report.get("product_count"),
        "step_solidworks_safe": step_report.get("solidworks_safe"),
        "node_count": len(nodes),
        "beam_count": len(beams),
        "polyline_count": len(polylines or []),
        "bbox_mm": {
            "x": [xmin, xmax],
            "y": [ymin, ymax],
            "z": [zmin, zmax],
        },
        "method": "gmsh_occ_unitcell_array",
    }


def _occ_imported_volume_bbox() -> tuple[float, float, float, float, float, float]:
    """Axis-aligned bbox (xmin, ymin, zmin, xmax, ymax, zmax) of all 3D volumes."""
    import gmsh

    vols = gmsh.model.getEntities(3)
    if not vols:
        raise RuntimeError("No 3D volumes in gmsh model.")
    xmin = ymin = zmin = float("inf")
    xmax = ymax = zmax = float("-inf")
    for dim, tag in vols:
        bx0, by0, bz0, bx1, by1, bz1 = gmsh.model.occ.getBoundingBox(dim, tag)
        xmin = min(xmin, float(bx0))
        ymin = min(ymin, float(by0))
        zmin = min(zmin, float(bz0))
        xmax = max(xmax, float(bx1))
        ymax = max(ymax, float(by1))
        zmax = max(zmax, float(bz1))
    return xmin, ymin, zmin, xmax, ymax, zmax


def export_lattice_step_occ_layered(
    layer_data: list[tuple[list, list, list]],
    path: str,
    *,
    junction_spheres: bool = True,
    polyline_sweep: str | None = None,
    keep_layer_steps: bool = False,
) -> dict[str, int | float | bool | str | list]:
    """
    Hierarchical OCC fuse: fuse each z-slab in its own gmsh session, import STEP
    slabs, then tree-fuse into one solid.

    ``layer_data`` is ``[(nodes, beams, polylines), ...]`` bottom → top. Use
    :meth:`HuBaiLatticeGenerator.build_lattice_z_layer` to build aligned slabs.

    Each slab is exported via :func:`export_lattice_step_occ` (isolated session)
    so later slabs cannot overwrite earlier volumes in a shared OCC model.
    """
    try:
        import gmsh
    except ImportError as exc:
        raise ImportError(
            "STEP export requires gmsh. Install: pip install gmsh"
        ) from exc

    from src.mesh.occ_pipe import prune_occ_for_step_export

    if not layer_data:
        raise ValueError("layer_data is empty.")

    if polyline_sweep is None:
        has_polylines = any(polylines for _, _, polylines in layer_data)
        polyline_sweep = "pipe" if has_polylines else "cylinder"

    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    root, ext = os.path.splitext(path)
    layer_dir = os.path.dirname(path) or "."

    layer_stats: list[dict[str, int | float | str]] = []
    layer_step_paths: list[str] = []
    total_parts = 0
    total_polylines = 0

    import copy as _copy

    for layer_idx, layer in enumerate(layer_data):
        nodes, beams, polylines = layer
        nodes = [list(n) for n in nodes]
        beams = [list(b) for b in beams]
        polylines = _copy.deepcopy(polylines)
        if keep_layer_steps:
            layer_path = f"{root}_layer{layer_idx}{ext}"
        else:
            layer_path = os.path.join(layer_dir, f".__layer_{layer_idx}.step")
        print(
            f"  Layer {layer_idx}: intra-fuse "
            f"({len(nodes)} nodes, {len(polylines or [])} polylines)...",
            flush=True,
        )
        slab = export_lattice_step_occ(
            nodes,
            beams,
            layer_path,
            polylines=polylines,
            junction_spheres=junction_spheres,
            fuse=True,
            polyline_sweep=polyline_sweep,
        )
        if int(slab.get("fused_volume_count") or 0) != 1:
            raise RuntimeError(
                f"Layer {layer_idx} fuse produced {slab.get('fused_volume_count')} "
                f"volume(s), expected 1: {layer_path}"
            )
        total_parts += int(slab.get("solid_count") or 0)
        total_polylines += len(polylines or [])
        layer_step_paths.append(layer_path)

        gmsh.initialize()
        try:
            gmsh.option.setNumber("General.Terminal", 0)
            gmsh.model.add(f"layer_bbox_{layer_idx}")
            gmsh.model.occ.importShapes(os.path.abspath(layer_path))
            gmsh.model.occ.synchronize()
            xmin, ymin, zmin, xmax, ymax, zmax = _occ_imported_volume_bbox()
        finally:
            gmsh.finalize()

        layer_stats.append(
            {
                "layer": layer_idx,
                "primitive_count": int(slab.get("solid_count") or 0),
                "fused_volume_count": int(slab.get("fused_volume_count") or 0),
                "step_path": layer_path,
                "bbox_mm": {
                    "x": [xmin, xmax],
                    "y": [ymin, ymax],
                    "z": [zmin, zmax],
                },
            }
        )
        print(
            f"    slab z=[{zmin:.1f}, {zmax:.1f}] mm "
            f"({int(slab.get('solid_count') or 0)} primitives)",
            flush=True,
        )

    print(f"  Inter-layer fuse: {len(layer_step_paths)} slab solid(s)...", flush=True)
    merged_step = _fuse_layer_step_files_sequential(
        layer_step_paths,
        progress_label="inter-layer",
    )

    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add(os.path.splitext(os.path.basename(path))[0] or "lattice_layered")
        print(f"  Import merged solid: {merged_step}", flush=True)
        gmsh.model.occ.importShapes(os.path.abspath(merged_step))
        gmsh.model.occ.synchronize()

        n_vol = len(gmsh.model.getEntities(3))
        if not n_vol:
            raise RuntimeError(
                "Layered OCC fuse produced no volume; STEP would be empty."
            )
        if n_vol != 1:
            print(
                f"  [WARN] Final fuse produced {n_vol} separate solids (expected 1).",
                flush=True,
            )

        xmin, ymin, zmin, xmax, ymax, zmax = _occ_imported_volume_bbox()
        print(
            f"  Final bbox: x=[{xmin:.1f},{xmax:.1f}] y=[{ymin:.1f},{ymax:.1f}] "
            f"z=[{zmin:.1f},{zmax:.1f}] mm",
            flush=True,
        )

        step_report = _finalize_occ_step_write(path, fuse=True)
        fused_volume_count = int(step_report.get("solid_count", 0))
    finally:
        gmsh.finalize()

    if not keep_layer_steps:
        for layer_path in layer_step_paths:
            try:
                os.remove(layer_path)
            except OSError:
                pass
        for idx in range(1, len(layer_step_paths)):
            merge_tmp = os.path.join(layer_dir, f".__merge_through_{idx}.step")
            try:
                os.remove(merge_tmp)
            except OSError:
                pass

    return {
        "step_path": path,
        "solid_count": total_parts,
        "pipe_count": total_polylines,
        "polyline_sweep": polyline_sweep,
        "fused": True,
        "fused_volume_count": fused_volume_count,
        "step_product_count": step_report.get("product_count"),
        "step_solidworks_safe": step_report.get("solidworks_safe"),
        "layer_count": len(layer_data),
        "layer_stats": layer_stats,
        "bbox_mm": {
            "x": [xmin, xmax],
            "y": [ymin, ymax],
            "z": [zmin, zmax],
        },
        "method": "gmsh_occ_layered_fuse",
    }


def export_lattice_xt(
    nodes: list,
    beams: list,
    xt_path: str,
    *,
    polylines: list[dict] | None = None,
    junction_spheres: bool = True,
    fuse: bool = False,
    keep_step: bool = True,
    step_path: str | None = None,
    mesh_resolution: int = 12,
    step_to_xt: bool = True,
) -> dict[str, int | float | bool | str]:
    """
    Export Parasolid text (.x_t) for SolidWorks.

    Small/medium blocks: gmsh OCC fuse → STEP → X_T via SolidWorks COM (STEP open + Save As).
    Large blocks (4×4×4): trimesh boolean union → fused STL (STEP→X_T only if SW open + small STL).

    With ``step_to_xt=True`` (default), calls SolidWorks on the fused STEP when SW is already
    running — same as manual File → Open STEP → Save As *.x_t. Does not start SolidWorks.
    """
    if step_path is None:
        root, _ = os.path.splitext(xt_path)
        step_path = root + ".step"

    from src.export.sw_parasolid import (
        convert_stl_to_xt,
        convert_step_to_xt,
        count_step_solids,
        solidworks_com_available,
    )

    count_junction = junction_spheres or bool(fuse)
    polyline_sweep = "pipe" if polylines else "cylinder"
    _, parts = _collect_solid_primitives(
        nodes,
        beams,
        polylines=polylines,
        junction_spheres=count_junction,
        polyline_sweep=polyline_sweep,
    )
    n_parts = len(parts)
    use_trimesh = False  # gmsh OCC batch fuse handles large part counts

    stats: dict[str, int | float | bool | str] = {
        "xt_path": xt_path,
        "xt_converted": False,
        "solid_count": n_parts,
        "fused": bool(fuse),
    }

    if use_trimesh:
        fused_stl = step_path.replace(".step", "_fused.stl")
        print(
            f"  Large lattice ({n_parts} rods): trimesh union → fused STL "
            f"(no SolidWorks COM — avoids crashes)",
            flush=True,
        )
        stl_stats = export_fused_stl(
            nodes,
            beams,
            fused_stl,
            polylines=polylines,
            resolution=mesh_resolution,
            junction_spheres=junction_spheres,
        )
        stats.update(stl_stats)
        stats["method"] = "trimesh_union_stl"
        stats["fused_stl"] = fused_stl
        stats["xt_manual"] = True
        stats["xt_error"] = (
            "Large fused STL: import manually in SolidWorks (Mesh → Solid body → Save As .x_t). "
            "Pass sw_com=True only for small test STLs with SW already open."
        )
        if step_to_xt and solidworks_com_available():
            try:
                print("  SolidWorks COM: STEP → X_T...", flush=True)
                convert_step_to_xt(step_path, xt_path)
                stats["xt_converted"] = True
                stats["xt_manual"] = False
                stats["xt_error"] = ""
                stats["step_solid_count"] = count_step_solids(step_path)
            except Exception as exc:
                stats["xt_error"] = str(exc)
        elif step_to_xt:
            stats["xt_manual"] = True
            stats["xt_error"] = (
                "SolidWorks not running. Start SW, then: "
                f"py -3 scripts/sw_step_to_xt.py \"{step_path}\""
            )
        return stats

    stats = export_lattice_step_occ(
        nodes,
        beams,
        step_path,
        polylines=polylines,
        junction_spheres=True,
        fuse=fuse,
    )
    stats["step_path"] = step_path
    stats["xt_path"] = xt_path
    stats["xt_converted"] = False
    stats["method"] = "gmsh_occ_step"

    if not step_to_xt:
        stats["xt_manual"] = True
        stats["xt_error"] = (
            f"STEP written: {step_path}. Re-run with SW open or "
            f"py -3 scripts/sw_step_to_xt.py \"{step_path}\""
        )
        return stats

    if not solidworks_com_available():
        stats["xt_error"] = (
            "SolidWorks is not running. Start SolidWorks, then re-run or use "
            f"scripts/sw_step_to_xt.py \"{step_path}\""
        )
        stats["xt_manual"] = True
        return stats

    fused_n = int(stats.get("fused_volume_count") or 0)
    if fuse and fused_n > 1:
        stats["xt_error"] = (
            f"Fused STEP has {fused_n} solids (expected 1). Fix STEP before X_T; "
            "see docs/hu_bai_abaqus_cad_import.md"
        )
        stats["xt_manual"] = True
        return stats

    if stats.get("step_solidworks_safe") is False:
        stats["xt_error"] = "STEP failed SolidWorks safety check (orphan PRODUCT geometry)"
        stats["xt_manual"] = True
        return stats

    try:
        print("  SolidWorks COM: STEP → X_T...", flush=True)
        convert_step_to_xt(step_path, xt_path)
        stats["xt_converted"] = True
        stats["xt_manual"] = False
        stats["xt_error"] = ""
        stats["step_solid_count"] = count_step_solids(step_path)
    except Exception as exc:
        stats["xt_error"] = str(exc)
        stats["xt_manual"] = True

    if not keep_step and os.path.isfile(step_path):
        os.remove(step_path)
        stats["step_path"] = ""

    return stats
