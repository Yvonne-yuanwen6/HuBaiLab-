"""Boolean-union lattice solids (single watertight body, no beam penetration)."""

from __future__ import annotations

import os
import tempfile
from collections import defaultdict
from typing import Iterable

import numpy as np

from src.export.export_sw import _segment_trimesh_cylinder, _union_all_meshes, _union_meshes_tree
from src.mesh.junction_mesh import collect_solid_junction_radii, effective_solid_radius
from src.mesh.solid_profiles import SOLID_SKIP_BEAM_TYPES, polyline_mesh_profile


def _node_lookup(nodes: list) -> dict[int, tuple[float, float, float]]:
    return {int(n[0]): (float(n[1]), float(n[2]), float(n[3])) for n in nodes}


def _junction_radii(
    nodes: list,
    beams: list,
    polylines: list[dict] | None,
) -> dict[int, float]:
    return collect_solid_junction_radii(nodes, beams, polylines)


def _junction_sphere_meshes(
    lookup: dict[int, tuple[float, float, float]],
    junction_r: dict[int, float],
    *,
    resolution: int = 12,
) -> list:
    import trimesh

    subdiv = 3 if resolution >= 20 else 2
    meshes: list = []
    for nid, radius in junction_r.items():
        if radius <= 0.0:
            continue
        center = lookup.get(nid)
        if center is None:
            continue
        sphere = trimesh.creation.icosphere(subdivisions=subdiv, radius=float(radius))
        sphere.apply_translation(center)
        meshes.append(sphere)
    return meshes


def _polyline_segment_meshes(
    lookup: dict[int, tuple[float, float, float]],
    polylines: Iterable[dict],
    *,
    resolution: int = 12,
) -> list:
    meshes: list = []
    for poly in polylines:
        node_ids = [int(n) for n in poly["nodes"]]
        radius = float(poly["radius"])
        for i in range(len(node_ids) - 1):
            p1 = lookup[node_ids[i]]
            p2 = lookup[node_ids[i + 1]]
            mesh = _segment_trimesh_cylinder(p1, p2, radius, resolution=resolution)
            if mesh is not None:
                meshes.append(mesh)
    return meshes


def build_lattice_union_mesh(
    nodes: list,
    beams: list,
    *,
    polylines: list[dict] | None = None,
    resolution: int = 12,
    junction_spheres: bool = True,
) -> object:
    """
    Merge all beam cylinders and junction spheres into one watertight solid.

    Requires trimesh + manifold3d (same as SolidWorks STL export).
    """
    try:
        import trimesh  # noqa: F401
    except ImportError as exc:
        raise ImportError(
            "Union solid requires trimesh and manifold3d. Install: pip install trimesh manifold3d"
        ) from exc

    lookup = _node_lookup(nodes)
    parts: list = []

    if junction_spheres:
        parts.extend(
            _junction_sphere_meshes(
                lookup,
                _junction_radii(nodes, beams, polylines),
                resolution=resolution,
            )
        )

    for _bid, n1, n2, radius, btype in beams:
        if str(btype) in SOLID_SKIP_BEAM_TYPES:
            continue
        p1 = lookup[int(n1)]
        p2 = lookup[int(n2)]
        mesh = _segment_trimesh_cylinder(p1, p2, float(radius), resolution=resolution)
        if mesh is not None:
            parts.append(mesh)

    if polylines:
        for poly in polylines:
            node_ids = [int(n) for n in poly["nodes"]]
            prof = polyline_mesh_profile(poly)
            if prof["profile"] == "square":
                r = effective_solid_radius(
                    profile="square", square_half=prof["square_half"]
                )
            else:
                r = effective_solid_radius(radius=prof["radius"], profile="circle")
            for i in range(len(node_ids) - 1):
                p1 = lookup[node_ids[i]]
                p2 = lookup[node_ids[i + 1]]
                mesh = _segment_trimesh_cylinder(p1, p2, r, resolution=resolution)
                if mesh is not None:
                    parts.append(mesh)

    if not parts:
        raise ValueError("No beam solids to union.")

    label = "union" if len(parts) > 48 else None
    if label:
        print(f"  Boolean union: {len(parts)} parts (tree merge)...")
    return _union_meshes_tree(parts, progress_label=label) if label else _union_all_meshes(parts)


def export_union_stl(
    nodes: list,
    beams: list,
    path: str,
    *,
    polylines: list[dict] | None = None,
    resolution: int = 12,
    junction_spheres: bool = True,
) -> dict[str, float | bool | int]:
    """Write boolean-union STL and return mesh quality stats."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    combined = build_lattice_union_mesh(
        nodes,
        beams,
        polylines=polylines,
        resolution=resolution,
        junction_spheres=junction_spheres,
    )
    combined.export(path)
    return {
        "watertight": bool(combined.is_watertight),
        "volume_mm3": float(combined.volume),
        "face_count": int(len(combined.faces)),
        "vertex_count": int(len(combined.vertices)),
    }


def _beam_segments(
    nodes: list,
    beams: list,
    polylines: list[dict] | None,
) -> list[tuple[np.ndarray, np.ndarray, float, str]]:
    lookup = {
        int(n[0]): np.array([float(n[1]), float(n[2]), float(n[3])], dtype=float) for n in nodes
    }
    segments: list[tuple[np.ndarray, np.ndarray, float, str]] = []
    for _bid, n1, n2, radius, btype in beams:
        if str(btype) in SOLID_SKIP_BEAM_TYPES:
            continue
        r = effective_solid_radius(radius=float(radius), profile="circle")
        segments.append((lookup[int(n1)], lookup[int(n2)], r, str(btype)))
    if polylines:
        for poly in polylines:
            ids = [int(n) for n in poly["nodes"]]
            prof = polyline_mesh_profile(poly)
            if prof["profile"] == "square":
                r = effective_solid_radius(
                    profile="square", square_half=prof["square_half"]
                )
            else:
                r = effective_solid_radius(radius=prof["radius"], profile="circle")
            btype = str(poly.get("type", "polyline"))
            for i in range(len(ids) - 1):
                segments.append((lookup[ids[i]], lookup[ids[i + 1]], r, btype))
    return segments


def _min_centerline_gap(a1: np.ndarray, a2: np.ndarray, b1: np.ndarray, b2: np.ndarray) -> float:
    best = float("inf")
    for t in np.linspace(0.0, 1.0, 21):
        p1 = a1 + t * (a2 - a1)
        for s in np.linspace(0.0, 1.0, 21):
            p2 = b1 + s * (b2 - b1)
            best = min(best, float(np.linalg.norm(p1 - p2)))
    return best


def analyze_cylinder_overlaps(
    nodes: list,
    beams: list,
    *,
    polylines: list[dict] | None = None,
    clearance_mm: float = 0.02,
) -> dict[str, int | list[tuple[str, str, float, float]]]:
    """
    Detect centerline pairs whose circular cross-sections intersect.

    Joint overlaps (shared endpoints) are expected for independent cylinder meshes;
    non-joint overlaps indicate geometric penetration (穿模).
    """
    segments = _beam_segments(nodes, beams, polylines)
    joint_overlap = 0
    body_overlap = 0
    samples: list[tuple[str, str, float, float]] = []

    for i in range(len(segments)):
        a1, a2, r1, t1 = segments[i]
        ends1 = {tuple(np.round(a1, 4)), tuple(np.round(a2, 4))}
        for j in range(i + 1, len(segments)):
            b1, b2, r2, t2 = segments[j]
            ends2 = {tuple(np.round(b1, 4)), tuple(np.round(b2, 4))}
            shared = bool(ends1 & ends2)
            gap = _min_centerline_gap(a1, a2, b1, b2)
            if gap >= r1 + r2 - clearance_mm:
                continue
            if shared:
                joint_overlap += 1
            else:
                body_overlap += 1
                if len(samples) < 16:
                    samples.append((t1, t2, gap, r1 + r2))

    return {
        "segment_count": len(segments),
        "joint_overlap_pairs": joint_overlap,
        "body_overlap_pairs": body_overlap,
        "body_overlap_samples": samples,
    }


def _gmsh_elem_props(elem_type: int) -> tuple[str, int, int, int]:
    import gmsh

    props = gmsh.model.mesh.getElementProperties(elem_type)
    return str(props[0]), int(props[1]), int(props[2]), int(props[3])


def _gmsh_extract_linear_tets() -> tuple[
    list[tuple[int, float, float, float]],
    list[tuple[int, int, int, int, int]],
]:
    import gmsh

    node_tags, coord, _ = gmsh.model.mesh.getNodes()
    tag_to_idx = {int(t): i for i, t in enumerate(node_tags)}
    mesh_nodes: list[tuple[int, float, float, float]] = []
    for tag in node_tags:
        i = tag_to_idx[int(tag)]
        mesh_nodes.append(
            (int(tag), float(coord[3 * i]), float(coord[3 * i + 1]), float(coord[3 * i + 2]))
        )

    elem_types, elem_tags, elem_node_tags = gmsh.model.mesh.getElements(dim=3)
    if not elem_types:
        raise RuntimeError("gmsh: no 3D elements generated")

    tet_type = None
    for et in elem_types:
        name, dim, order, n_nodes = _gmsh_elem_props(et)
        if dim == 3 and order == 1 and n_nodes == 4:
            tet_type = et
            break
    if tet_type is None:
        raise RuntimeError("gmsh: no linear 4-node tet elements in volume mesh")

    idx = list(elem_types).index(tet_type)
    tags = elem_tags[idx]
    conn = elem_node_tags[idx]
    mesh_elements: list[tuple[int, int, int, int, int]] = []
    for e, eid in enumerate(tags):
        base = 4 * e
        nids = tuple(int(conn[base + k]) for k in range(4))
        mesh_elements.append((int(eid), *nids))
    return mesh_nodes, mesh_elements


def mesh_lattice_gmsh_occ(
    nodes: list,
    beams: list,
    *,
    polylines: list[dict] | None = None,
    mesh_size: float = 0.3,
    junction_spheres: bool = False,
    progress: bool = True,
) -> tuple[
    list[tuple[int, float, float, float]],
    list[tuple[int, int, int, int, int]],
    dict[str, list[int]],
]:
    """
    Paper-style solid mesh: analytic beam cylinders (+ optional junction spheres)
    boolean-fused in Gmsh OpenCASCADE, then ~mesh_size mm tet volume mesh (C3D4).

    Single connected solid (no beam penetration, smooth cosine surfaces).
    """
    import gmsh

    lookup = _node_lookup(nodes)
    segments = _beam_segments(nodes, beams, polylines)
    if not segments:
        raise ValueError("No beam segments for gmsh OCC mesh.")

    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add("lattice_occ")
        vol_tags: list[int] = []

        for p1, p2, radius, _btype in segments:
            d = p2 - p1
            height = float(np.linalg.norm(d))
            if height < 1e-6:
                continue
            vol_tags.append(
                gmsh.model.occ.addCylinder(
                    float(p1[0]),
                    float(p1[1]),
                    float(p1[2]),
                    float(d[0]),
                    float(d[1]),
                    float(d[2]),
                    float(radius),
                )
            )

        if junction_spheres:
            for nid, radius in _junction_radii(nodes, beams, polylines).items():
                if radius <= 0.0:
                    continue
                center = lookup.get(int(nid))
                if center is None:
                    continue
                vol_tags.append(
                    gmsh.model.occ.addSphere(
                        float(center[0]),
                        float(center[1]),
                        float(center[2]),
                        float(radius),
                    )
                )

        if not vol_tags:
            raise ValueError("gmsh OCC: no volume primitives created.")

        if progress:
            print(f"  Gmsh OCC fuse: {len(vol_tags)} primitives...")
        if len(vol_tags) > 1:
            gmsh.model.occ.fuse([(3, vol_tags[0])], [(3, t) for t in vol_tags[1:]])
        gmsh.model.occ.synchronize()
        # Volume mesh only — no gmsh.write(STEP). Solid STEP export must use
        # export_lattice_step_occ → prune_occ_for_step_export() before write.

        gmsh.option.setNumber("Mesh.MeshSizeMax", float(mesh_size))
        gmsh.option.setNumber("Mesh.MeshSizeMin", float(mesh_size) * 0.5)
        if progress:
            print(f"  Gmsh volume mesh (target {mesh_size} mm)...")
        gmsh.model.mesh.generate(3)

        mesh_nodes, mesh_elements = _gmsh_extract_linear_tets()
        n_comp = count_connected_components(mesh_nodes, mesh_elements)
        if n_comp != 1:
            raise RuntimeError(
                f"gmsh OCC union produced {n_comp} disconnected solids (expected 1). "
                "Try junction_spheres=True or check geometry."
            )
        elsets = {"solid": [int(e[0]) for e in mesh_elements]}
        return mesh_nodes, mesh_elements, elsets
    finally:
        gmsh.finalize()


def mesh_step_gmsh_tets(
    step_path: str,
    *,
    mesh_size: float = 0.6,
    algorithm: int = 1,
    heal_shapes: bool = False,
    progress: bool = True,
) -> tuple[
    list[tuple[int, float, float, float]],
    list[tuple[int, int, int, int, int]],
    dict[str, list[int]],
]:
    """Volume tet mesh (C3D4) of a single-body STEP BREP via gmsh OpenCASCADE."""
    import gmsh

    if not os.path.isfile(step_path):
        raise FileNotFoundError(step_path)

    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add("cad_step")
        gmsh.model.occ.importShapes(os.path.abspath(step_path))
        gmsh.model.occ.synchronize()

        if not gmsh.model.getEntities(3):
            raise RuntimeError(f"gmsh: no 3D volumes in STEP {step_path}")

        if heal_shapes:
            gmsh.model.occ.healShapes()
            gmsh.model.occ.synchronize()

        gmsh.option.setNumber("Mesh.CharacteristicLengthMin", float(mesh_size) * 0.5)
        gmsh.option.setNumber("Mesh.CharacteristicLengthMax", float(mesh_size))
        gmsh.option.setNumber("Mesh.Algorithm3D", int(algorithm))
        if progress:
            heal_tag = ", heal" if heal_shapes else ""
            print(
                f"  Gmsh STEP volume mesh (target {mesh_size} mm, algo={algorithm}{heal_tag})...",
                flush=True,
            )
        gmsh.model.mesh.generate(3)

        mesh_nodes, mesh_elements = _gmsh_extract_linear_tets()
        n_comp = count_connected_components(mesh_nodes, mesh_elements)
        if n_comp != 1:
            raise RuntimeError(
                f"gmsh STEP mesh has {n_comp} disconnected solids (expected 1): {step_path}"
            )
        elsets = {"solid": [int(e[0]) for e in mesh_elements]}
        return mesh_nodes, mesh_elements, elsets
    finally:
        gmsh.finalize()


def step_to_trimesh_surface(
    step_path: str,
    *,
    mesh_size: float = 0.4,
    progress: bool = True,
) -> object:
    """Tessellate a single-body STEP to a watertight trimesh surface (for voxel fill)."""
    import gmsh
    import trimesh

    if not os.path.isfile(step_path):
        raise FileNotFoundError(step_path)

    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add("cad_surf")
        gmsh.model.occ.importShapes(os.path.abspath(step_path))
        gmsh.model.occ.synchronize()

        if not gmsh.model.getEntities(3):
            raise RuntimeError(f"gmsh: no 3D volumes in STEP {step_path}")

        gmsh.option.setNumber("Mesh.CharacteristicLengthMin", float(mesh_size) * 0.5)
        gmsh.option.setNumber("Mesh.CharacteristicLengthMax", float(mesh_size))
        if progress:
            print(
                f"  Gmsh STEP surface tessellation ({mesh_size} mm) for voxel shell...",
                flush=True,
            )
        gmsh.model.mesh.generate(2)

        with tempfile.TemporaryDirectory() as tmp:
            stl_path = os.path.join(tmp, "shell.stl")
            gmsh.write(stl_path)
            loaded = trimesh.load(stl_path)

        if isinstance(loaded, trimesh.Scene):
            loaded = loaded.dump(concatenate=True)
        if not isinstance(loaded, trimesh.Trimesh):
            raise RuntimeError(f"Expected trimesh.Trimesh from STEP shell, got {type(loaded)}")
        if not loaded.is_watertight:
            loaded.fill_holes()
        if not loaded.is_watertight:
            raise RuntimeError(
                f"STEP surface mesh is not watertight ({step_path}); "
                "try smaller surface mesh_size or heal the CAD."
            )
        return loaded
    finally:
        gmsh.finalize()


def mesh_step_voxel_c3d8r(
    step_path: str,
    *,
    pitch: float = 0.5,
    surface_mesh_size: float | None = None,
    progress: bool = True,
) -> tuple[
    list[tuple[int, float, float, float]],
    list[tuple[int, int, int, int, int, int, int, int, int]],
    dict[str, list[int]],
]:
    """Voxel-fill a STEP solid into merged C3D8R hex elements (stair-step surface)."""
    pitch = float(pitch)
    surf = float(surface_mesh_size) if surface_mesh_size is not None else max(pitch * 0.5, 0.2)
    if progress:
        print(f"  Voxel fill @ pitch={pitch} mm (surface tessellation {surf} mm)...", flush=True)
    shell = step_to_trimesh_surface(step_path, mesh_size=surf, progress=progress)
    mesh_nodes, mesh_elements = mesh_union_voxel_c3d8r(shell, pitch=pitch)
    elsets = {"solid": [int(e[0]) for e in mesh_elements]}
    return mesh_nodes, mesh_elements, elsets


def mesh_union_gmsh_tets(
    union_mesh: object,
    *,
    mesh_size: float = 0.3,
    algorithm: int = 1,
) -> tuple[list[tuple[int, float, float, float]], list[tuple[int, int, int, int, int]]]:
    """
    Tetrahedral volume mesh (C3D4) of a watertight union surface via gmsh.

    Raises ImportError if gmsh is not installed.
    """
    import gmsh

    with tempfile.TemporaryDirectory() as tmp:
        stl_path = os.path.join(tmp, "union.stl")
        union_mesh.export(stl_path)

        gmsh.initialize()
        try:
            gmsh.option.setNumber("General.Terminal", 0)
            gmsh.model.add("lattice_union")
            gmsh.merge(stl_path)

            entities = gmsh.model.getEntities(2)
            if not entities:
                raise RuntimeError("gmsh: no surface entities after STL merge")

            surface_tags = [tag for dim, tag in entities if dim == 2]
            loop = gmsh.model.geo.addSurfaceLoop(surface_tags)
            gmsh.model.geo.addVolume([loop])
            gmsh.model.geo.synchronize()

            gmsh.option.setNumber("Mesh.CharacteristicLengthMin", float(mesh_size) * 0.5)
            gmsh.option.setNumber("Mesh.CharacteristicLengthMax", float(mesh_size))
            gmsh.option.setNumber("Mesh.Algorithm3D", int(algorithm))
            gmsh.model.mesh.generate(3)
            return _gmsh_extract_linear_tets()
        finally:
            gmsh.finalize()


def count_connected_components(
    mesh_nodes: list[tuple[int, float, float, float]],
    mesh_elements: list[tuple[int, ...]],
) -> int:
    parent: dict[int, int] = {}

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for nid, *_ in mesh_nodes:
        parent[int(nid)] = int(nid)

    for elem in mesh_elements:
        nids = [int(n) for n in elem[1:]]
        for i in range(1, len(nids)):
            union(nids[0], nids[i])

    return len({find(int(nid)) for nid, *_ in mesh_nodes})


def mesh_union_voxel_c3d8r(
    union_mesh: object,
    *,
    pitch: float = 0.3,
) -> tuple[list[tuple[int, float, float, float]], list[tuple[int, int, int, int, int, int, int, int, int]]]:
    """
    Voxel-fill a watertight union solid into merged C3D8R hex elements.

    Produces one connected solid without beam penetration (stair-step surface).
    """
    import trimesh

    from src.mesh.beam_hex_mesh import _orient_c3d8

    pitch = float(pitch)
    if pitch <= 0.0:
        raise ValueError("pitch must be positive")

    vg = union_mesh.voxelized(pitch=pitch).fill()
    matrix = np.asarray(vg.matrix, dtype=bool)
    transform = np.asarray(vg.transform, dtype=float)

    corner_idx = (
        (0, 0, 0),
        (1, 0, 0),
        (1, 1, 0),
        (0, 1, 0),
        (0, 0, 1),
        (1, 0, 1),
        (1, 1, 1),
        (0, 1, 1),
    )

    pos_to_nid: dict[tuple[float, float, float], int] = {}
    coords: dict[int, np.ndarray] = {}
    mesh_nodes: list[tuple[int, float, float, float]] = []
    mesh_elements: list[tuple[int, int, int, int, int, int, int, int, int]] = []
    next_nid = 1
    next_eid = 1

    def get_nid(x: float, y: float, z: float) -> int:
        nonlocal next_nid
        key = (round(x, 6), round(y, 6), round(z, 6))
        if key not in pos_to_nid:
            pos_to_nid[key] = next_nid
            pos = np.array([x, y, z], dtype=float)
            mesh_nodes.append((next_nid, x, y, z))
            coords[next_nid] = pos
            next_nid += 1
        return pos_to_nid[key]

    filled = np.argwhere(matrix)
    for i, j, k in filled:
        nids: list[int] = []
        for ci, cj, ck in corner_idx:
            local = np.array([float(i + ci), float(j + cj), float(k + ck), 1.0])
            world = transform @ local
            nids.append(get_nid(float(world[0]), float(world[1]), float(world[2])))
        brick = _orient_c3d8(coords, tuple(nids))
        mesh_elements.append((next_eid, *brick))
        next_eid += 1

    if not mesh_elements:
        raise RuntimeError("Voxel mesh produced no solid elements; try smaller pitch or check union STL.")

    return mesh_nodes, mesh_elements
