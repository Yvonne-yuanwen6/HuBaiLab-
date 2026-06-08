"""Export lattice models to Abaqus INP (B31 beam or C3D8R/C3D4 solid + TPU)."""

from __future__ import annotations

import os
from typing import Iterable

from src.export.abaqus_compression import (
    CompressionSettings,
    build_plate_mesh,
    compute_loading_plate_z,
    compute_passive_plate_z,
    compute_plate_xy_extent,
    collect_bottom_node_ids,
    collect_c3d4_bottom_element_faces,
    collect_c3d4_top_element_faces,
    collect_c3d8_bottom_element_faces,
    collect_c3d8_top_element_faces,
    collect_lattice_bottom_node_ids,
    collect_lattice_top_node_ids,
    collect_top_node_ids,
    lattice_bounds,
    write_compression_sections,
)
from src.export.beam_utils import dedupe_beams
from src.mesh.beam_tet_mesh import mesh_beams_c3d4
from src.mesh.beam_hex_mesh import mesh_beams_c3d8r
from src.export.wireframe_overlay import build_wireframe_overlay
from src.naming import build_geometry_tag


def geom_tag_for_generator(gen, *, nx: int = 3, ny: int = 3, nz: int = 3) -> str:
    """Geometry tag embedded in INP Heading (matches case slug without stroke)."""
    return build_geometry_tag(gen, nx=nx, ny=ny, nz=nz)

# Default Neo-Hookean constants for TPU (Pa). Calibrate from tensile tests.
# Neo-Hooke C10，单位与模型一致（mm–N–MPa 时约为 0.1~2 MPa 量级软 TPU）
DEFAULT_TPU_C10 = 0.5
DEFAULT_TPU_C01 = 0.1e6
# Abaqus 默认 mm–N–s–tonne：密度 = (kg/m³) × 1e-12；1200 kg/m³ → 1.2e-9
DEFAULT_TPU_DENSITY = 1.2e-9


def _write_elset(f, name: str, element_ids: Iterable[int], *, lines: int = 16) -> None:
    ids = [str(i) for i in element_ids]
    if not ids:
        return
    f.write(f"*Elset, elset={name}\n")
    for i in range(0, len(ids), lines):
        f.write(", ".join(ids[i : i + lines]) + "\n")


def export_inp_b31(
    nodes,
    beams,
    path: str,
    *,
    polylines: list | None = None,
    geom_tag: str | None = None,
    by_type_elsets: bool = True,
) -> None:
    """B31 centerline model for CAE topology check (matches PNG wireframe)."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tag = geom_tag or "lattice"

    with open(path, "w", encoding="utf-8") as f:
        f.write(
            "*Heading\n"
            "Lattice topology wireframe (B31, visualization only)\n"
            f"LatticeLab geom={tag}; structural nodes={len(nodes)} beams={len(beams)}\n"
        )

        f.write("\n*Node\n")
        for n in nodes:
            f.write(f"{n[0]}, {n[1]}, {n[2]}, {n[3]}\n")

        all_eids: list[int] = []
        by_type: dict[str, list[int]] = {}
        f.write("\n*Element, type=B31\n")
        for b in beams:
            eid, n1, n2, _, btype = b
            f.write(f"{eid}, {n1}, {n2}\n")
            all_eids.append(int(eid))
            by_type.setdefault(str(btype), []).append(int(eid))
        next_eid = max(all_eids, default=0) + 1
        for poly in polylines or []:
            btype = str(poly.get("type", "support"))
            nids = poly["nodes"]
            for a, b in zip(nids[:-1], nids[1:]):
                f.write(f"{next_eid}, {a}, {b}\n")
                all_eids.append(next_eid)
                by_type.setdefault(btype, []).append(next_eid)
                next_eid += 1

        _write_elset(f, "ALLBEAMS", all_eids)
        if by_type_elsets:
            for btype, ids in sorted(by_type.items()):
                _write_elset(f, f"TYPE_{btype.upper()}", ids)

        f.write(
            """
*Material, name=STEEL
*Elastic
210000., 0.3
*Density
7.85e-9
*Beam Section, elset=ALLBEAMS, material=STEEL, section=PIPE
0.1, 0.05
"""
        )


def export_inp_c3d4(
    nodes,
    beams,
    path: str,
    *,
    polylines: list | None = None,
    n_axial: int | None = None,
    n_theta: int = 8,
    polyline_axial_per_span: int = 4,
    c10: float = DEFAULT_TPU_C10,
    c01: float = DEFAULT_TPU_C01,
    density: float = DEFAULT_TPU_DENSITY,
    material_model: str = "hyperelastic",
    elastic_e: float = 1250.0,
    elastic_nu: float = 0.3,
    plastic_yield: float | None = None,
    material_name: str = "TPU",
    compression: CompressionSettings | None = None,
    include_wireframe: bool = True,
    geom_tag: str | None = None,
    solid_element: str = "C3D8R",
    pre_mesh: tuple[list, list, dict[str, list[int]] | None] | None = None,
) -> dict[str, int | float]:
    """
    Solid model: C3D8R (default) or C3D4 tets + hyperelastic TPU.

    C3D8R uses ~3x fewer elements than C3D4 at the same n_axial/n_theta and
    is better suited to soft TPU large-deformation compression (reduced integration).

    If ``compression`` is set, adds a top plate coplanar with top O nodes,
    bottom fixed BC, displacement-controlled compression, and hard contact.

    Pass ``pre_mesh=(mesh_nodes, mesh_elements, elsets_by_type)`` to skip the
    beam-cylinder mesher (e.g. boolean-union voxel or gmsh volume mesh).
    """
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tag = geom_tag or "lattice"
    elem_key = solid_element.upper()
    if elem_key in ("C3D8R", "C3D8"):
        mesh_fn = mesh_beams_c3d8r
        abq_elem = elem_key
        collect_top_faces = collect_c3d8_top_element_faces
        collect_bottom_faces = collect_c3d8_bottom_element_faces
    elif elem_key in ("C3D4", "C3D4R"):
        mesh_fn = mesh_beams_c3d4
        abq_elem = "C3D4"
        collect_top_faces = collect_c3d4_top_element_faces
        collect_bottom_faces = collect_c3d4_bottom_element_faces
    else:
        raise ValueError(f"Unsupported solid_element: {solid_element}")

    beams, beam_duplicates = dedupe_beams(beams)
    z_struct = [float(n[3]) for n in nodes]
    z_beam = []
    lookup = {int(n[0]): (float(n[1]), float(n[2]), float(n[3])) for n in nodes}
    for _bid, n1, n2, _r, _t in beams:
        z_beam.extend((lookup[int(n1)][2], lookup[int(n2)][2]))
    if not z_beam and polylines:
        for poly in polylines:
            for nid in poly.get("nodes", []):
                if int(nid) in lookup:
                    z_beam.append(lookup[int(nid)][2])
    if not z_beam:
        z_beam = list(z_struct)

    mesh_nodes, mesh_elements, elsets_by_type = (
        pre_mesh
        if pre_mesh is not None
        else mesh_fn(
            nodes,
            beams,
            polylines=polylines,
            n_axial=n_axial,
            n_theta=n_theta,
            polyline_axial_per_span=polyline_axial_per_span,
        )
    )
    if elsets_by_type is None:
        elsets_by_type = {"solid": [e[0] for e in mesh_elements]}

    lattice_eids = [e[0] for e in mesh_elements]
    max_nid = max(n[0] for n in mesh_nodes)
    max_eid = max(lattice_eids)

    plate_nodes: list[tuple[int, float, float, float]] = []
    plate_elements: list[tuple[int, int, int, int, int]] = []
    counter_plate_nodes: list[tuple[int, float, float, float]] = []
    counter_plate_elements: list[tuple[int, int, int, int, int]] = []
    wire_extra_nodes: list[tuple[int, float, float, float]] = []
    wire_elements: list[tuple[int, int, int]] = []
    wire_eids: list[int] = []
    ref_node_id = max_nid + 1
    plate_node_ids: list[int] = []
    lattice_load_faces: list[tuple[int, str]] = []
    lattice_load_node_ids: list[int] = []
    fixed_node_ids: list[int] = []
    counter_lattice_node_ids: list[int] = []
    counter_ref_node_id: int | None = None
    counter_ref_node: tuple[int, float, float, float] | None = None
    z_counter: float | None = None
    use_counter_plate = False
    fixed_plate_nodes: list[tuple[int, float, float, float]] = []
    fixed_plate_elements: list[tuple[int, int, int, int, int]] = []
    fixed_ref_node_id: int | None = None
    fixed_ref_node: tuple[int, float, float, float] | None = None
    lattice_bottom_faces: list[tuple[int, str]] = []
    z_fixed: float | None = None
    use_fixed_bottom_plate = False

    # 压缩仿真 INP 不含 B31 线框（Explicit 下易报梁截面错误）；预览用 PNG
    if include_wireframe and compression is None:
        wire_extra_nodes, wire_elements, wire_eids = build_wireframe_overlay(
            nodes,
            beams,
            mesh_nodes,
            node_id_start=max_nid + 1,
            elem_id_start=max_eid + 1,
        )

    wire_offset = len(wire_extra_nodes)
    plate_node_start = max_nid + wire_offset + 1

    if compression is not None:
        xmin, xmax, ymin, ymax, zmin, zmax = lattice_bounds(nodes)
        mesh_z_min = min(z for _, _, _, z in mesh_nodes)
        mesh_z_max = max(z for _, _, _, z in mesh_nodes)
        x0, x1, y0, y1 = compute_plate_xy_extent(mesh_nodes, compression)
        half_thk = compression.plate_thickness / 2.0
        bottom_up = compression.is_bottom_up()
        if bottom_up:
            z_plate = compute_loading_plate_z(
                mesh_z_min, half_thk=half_thk, settings=compression, bottom_up=True
            )
        else:
            z_plate = compute_loading_plate_z(
                mesh_z_max, half_thk=half_thk, settings=compression, bottom_up=False
            )

        plate_nodes, plate_elements, plate_node_ids = build_plate_mesh(
            x0,
            x1,
            y0,
            y1,
            z_plate,
            compression.plate_divisions[0],
            compression.plate_divisions[1],
            node_id_start=plate_node_start,
            elem_id_start=max_eid + len(wire_eids) + 1,
        )
        ref_node_id = (plate_nodes[-1][0] + 1 if plate_nodes else plate_node_start)
        cx = 0.5 * (x0 + x1)
        cy = 0.5 * (y0 + y1)
        ref_node = (ref_node_id, cx, cy, z_plate)

        fixed_tol = compression.resolved_fixed_tol()
        if bottom_up:
            z_band_faces = compression.resolved_load_surface_z_band()
            lattice_load_faces = collect_bottom_faces(
                mesh_nodes,
                mesh_elements,
                z_band=z_band_faces,
                normal_z_max=compression.resolved_bottom_face_normal_z_max(),
            )
            z_band_nodes = compression.resolved_load_node_z_band()
            lattice_load_node_ids = collect_lattice_bottom_node_ids(
                mesh_nodes,
                z_band=z_band_nodes,
            )
            use_counter_plate = compression.use_passive_counter_plate()
            if use_counter_plate:
                z_counter = compute_passive_plate_z(
                    mesh_z_max, half_thk=half_thk, settings=compression, bottom_up=True
                )
                counter_node_start = ref_node_id + 1
                counter_elem_start = max_eid + len(wire_eids) + 1 + len(plate_elements)
                counter_plate_nodes, counter_plate_elements, _ = build_plate_mesh(
                    x0,
                    x1,
                    y0,
                    y1,
                    z_counter,
                    compression.plate_divisions[0],
                    compression.plate_divisions[1],
                    node_id_start=counter_node_start,
                    elem_id_start=counter_elem_start,
                )
                counter_ref_node_id = (
                    counter_plate_nodes[-1][0] + 1
                    if counter_plate_nodes
                    else counter_node_start
                )
                counter_ref_node = (counter_ref_node_id, cx, cy, z_counter)
                # 与无顶板时的 TOP_FIX 相同：仅最顶薄层节点，勿用宽 z_band
                counter_lattice_node_ids = collect_top_node_ids(mesh_nodes, fixed_tol)
                fixed_node_ids = counter_lattice_node_ids
            else:
                fixed_node_ids = collect_top_node_ids(mesh_nodes, fixed_tol)
        else:
            use_fixed_bottom_plate = compression.use_fixed_bottom_plate()
            if use_fixed_bottom_plate:
                z_fixed = compute_passive_plate_z(
                    mesh_z_min, half_thk=half_thk, settings=compression, bottom_up=False
                )
                fixed_node_start = ref_node_id + 1
                fixed_elem_start = max_eid + len(wire_eids) + 1 + len(plate_elements)
                fixed_plate_nodes, fixed_plate_elements, _ = build_plate_mesh(
                    x0,
                    x1,
                    y0,
                    y1,
                    z_fixed,
                    compression.plate_divisions[0],
                    compression.plate_divisions[1],
                    node_id_start=fixed_node_start,
                    elem_id_start=fixed_elem_start,
                )
                fixed_ref_node_id = (
                    fixed_plate_nodes[-1][0] + 1 if fixed_plate_nodes else fixed_node_start
                )
                fixed_ref_node = (fixed_ref_node_id, cx, cy, z_fixed)
                z_band_bottom = compression.resolved_bottom_surface_z_band()
                lattice_bottom_faces = collect_bottom_faces(
                    mesh_nodes,
                    mesh_elements,
                    z_band=z_band_bottom,
                    normal_z_max=compression.resolved_bottom_face_normal_z_max(),
                )
                fixed_node_ids = []
            else:
                fixed_node_ids = collect_bottom_node_ids(mesh_nodes, fixed_tol)
            z_band_faces = compression.resolved_load_surface_z_band()
            lattice_load_faces = collect_top_faces(
                mesh_nodes,
                mesh_elements,
                z_band=z_band_faces,
                normal_z_min=compression.resolved_top_face_normal_z_min(),
            )
            z_band_nodes = compression.resolved_load_node_z_band()
            lattice_load_node_ids = collect_lattice_top_node_ids(
                mesh_nodes,
                z_band=z_band_nodes,
            )
    else:
        ref_node = None
        fixed_node_ids = []

    stats: dict[str, int | float] = {
        "node_count": (
            len(mesh_nodes)
            + len(wire_extra_nodes)
            + len(plate_nodes)
            + len(counter_plate_nodes)
            + len(fixed_plate_nodes)
            + (1 if compression else 0)
            + (1 if counter_ref_node is not None else 0)
            + (1 if fixed_ref_node is not None else 0)
        ),
        "element_count": (
            len(mesh_elements)
            + len(wire_elements)
            + len(plate_elements)
            + len(counter_plate_elements)
            + len(fixed_plate_elements)
        ),
        "wireframe_beams": len(wire_eids),
        "structural_nodes": len(nodes),
        "structural_beams": len(beams),
        "beam_duplicates_removed": beam_duplicates,
        "geom_tag": tag,
        "solid_element": abq_elem,
        "structural_z_min": min(z_struct),
        "structural_z_max": max(z_struct),
        "beam_z_min": min(z_beam),
        "beam_z_max": max(z_beam),
    }

    with open(path, "w", encoding="utf-8") as f:
        if compression:
            load_desc = (
                "bottom plate upward + fixed top plate"
                if compression.is_bottom_up() and use_counter_plate
                else "bottom plate upward"
                if compression.is_bottom_up()
                else "top plate downward + fixed bottom plate (pair contact)"
                if use_fixed_bottom_plate
                else "top plate downward"
            )
            f.write(
                "*Heading\n"
                f"Lattice {abq_elem} + TPU compression ({load_desc}, lattice self-contact, disp. control)\n"
                f"LatticeLab geom={tag}; structural nodes={len(nodes)} "
                f"beams={len(beams)} (deduped); z_beam=[{min(z_beam):g},{max(z_beam):g}]\n"
            )
        else:
            f.write(
                "*Heading\n"
                f"Lattice solid model ({abq_elem}, TPU); LatticeLab geom={tag}\n"
            )

        f.write("\n*Node\n")
        for nid, x, y, z in mesh_nodes:
            f.write(f"{nid}, {x}, {y}, {z}\n")
        for nid, x, y, z in wire_extra_nodes:
            f.write(f"{nid}, {x}, {y}, {z}\n")
        for nid, x, y, z in plate_nodes:
            f.write(f"{nid}, {x}, {y}, {z}\n")
        if compression and ref_node is not None:
            f.write(f"{ref_node[0]}, {ref_node[1]}, {ref_node[2]}, {ref_node[3]}\n")
        for nid, x, y, z in counter_plate_nodes:
            f.write(f"{nid}, {x}, {y}, {z}\n")
        for nid, x, y, z in fixed_plate_nodes:
            f.write(f"{nid}, {x}, {y}, {z}\n")
        if compression and counter_ref_node is not None:
            f.write(
                f"{counter_ref_node[0]}, {counter_ref_node[1]}, "
                f"{counter_ref_node[2]}, {counter_ref_node[3]}\n"
            )
        if compression and fixed_ref_node is not None:
            f.write(
                f"{fixed_ref_node[0]}, {fixed_ref_node[1]}, "
                f"{fixed_ref_node[2]}, {fixed_ref_node[3]}\n"
            )

        f.write(f"\n*Element, type={abq_elem}\n")
        if abq_elem in ("C3D8R", "C3D8"):
            for row in mesh_elements:
                eid = row[0]
                n1, n2, n3, n4, n5, n6, n7, n8 = row[1:9]
                f.write(f"{eid}, {n1}, {n2}, {n3}, {n4}, {n5}, {n6}, {n7}, {n8}\n")
        else:
            for eid, n1, n2, n3, n4 in mesh_elements:
                f.write(f"{eid}, {n1}, {n2}, {n3}, {n4}\n")

        if wire_elements:
            f.write("\n*Element, type=B31\n")
            for eid, n1, n2 in wire_elements:
                f.write(f"{eid}, {n1}, {n2}\n")

        if plate_elements:
            f.write("*Element, type=S4R\n")
            for eid, n1, n2, n3, n4 in plate_elements:
                f.write(f"{eid}, {n1}, {n2}, {n3}, {n4}\n")
        if counter_plate_elements:
            f.write("*Element, type=S4R\n")
            for eid, n1, n2, n3, n4 in counter_plate_elements:
                f.write(f"{eid}, {n1}, {n2}, {n3}, {n4}\n")
        if fixed_plate_elements:
            f.write("*Element, type=S4R\n")
            for eid, n1, n2, n3, n4 in fixed_plate_elements:
                f.write(f"{eid}, {n1}, {n2}, {n3}, {n4}\n")

        _write_elset(f, "ALLSOLID", lattice_eids)
        if wire_eids:
            _write_elset(f, "WIREFRAME", wire_eids)

        for btype, ids in sorted(elsets_by_type.items()):
            _write_elset(f, f"TYPE_{btype.upper()}", ids)

        # Material (Neo-Hooke TPU default, or isotropic elastic per paper Table 1)
        tpu_d1 = 0.05
        if compression is not None:
            tpu_d1 = compression.tpu_d1

        mat = str(material_model).lower()
        f.write(f"*Material, name={material_name}\n*Density\n{density}\n")
        if mat == "elastic":
            f.write(f"*Elastic\n{float(elastic_e)}, {float(elastic_nu)}\n")
            if plastic_yield is not None and float(plastic_yield) > 0.0:
                f.write(f"*Plastic\n{float(plastic_yield)}, 0.\n")
        else:
            f.write(f"*Hyperelastic, neo Hooke\n{c10}, {tpu_d1}\n")
        f.write(f"*Solid Section, elset=ALLSOLID, material={material_name}\n")

        if wire_eids:
            f.write(
                """
*Material, name=WIRE-VIS
*Elastic
210000., 0.3
*Density
1.
*Beam Section, elset=WIREFRAME, material=WIRE-VIS, section=CIRC
0.05
"""
            )

        if compression is not None:
            plate_eids = [e[0] for e in plate_elements]
            stats["mesh_xmin"] = xmin
            stats["mesh_xmax"] = xmax
            stats["mesh_ymin"] = ymin
            stats["mesh_ymax"] = ymax
            stats["mesh_z_min"] = mesh_z_min if compression is not None else zmin
            stats["mesh_z_max"] = mesh_z_max
            stats["top_plane_z"] = compression.top_plane_z
            stats["plate_z"] = z_plate
            stats["loading_direction"] = compression.loading_direction
            stats["passive_counter_plate"] = use_counter_plate
            stats["fixed_bottom_plate"] = use_fixed_bottom_plate
            if use_fixed_bottom_plate and fixed_ref_node_id is not None:
                stats["fixed_plate_ref_node_id"] = int(fixed_ref_node_id)
                stats["plate_fixed_z"] = float(z_fixed) if z_fixed is not None else 0.0
                stats["lattice_bottom_faces"] = len(lattice_bottom_faces)
            if use_counter_plate and counter_ref_node_id is not None:
                stats["counter_ref_node_id"] = int(counter_ref_node_id)
                stats["plate_counter_z"] = float(z_counter) if z_counter is not None else 0.0
                stats["counter_lattice_nodes"] = len(counter_lattice_node_ids)
            stats["compression_velocity"] = compression.compression_velocity
            stats["fixed_nodes"] = len(fixed_node_ids)
            stats["lattice_load_faces"] = len(lattice_load_faces)
            stats["lattice_load_nodes"] = len(lattice_load_node_ids)
            stats["bottom_nodes_fixed"] = len(fixed_node_ids)
            stats["lattice_top_faces"] = len(lattice_load_faces)
            stats["lattice_top_nodes"] = len(lattice_load_node_ids)
            if ref_node is not None:
                stats["plate_ref_node_id"] = int(ref_node[0])
            write_compression_sections(
                f,
                compression,
                fixed_node_ids=fixed_node_ids,
                ref_node_id=ref_node_id,
                plate_elem_ids=plate_eids,
                lattice_elem_ids=lattice_eids,
                lattice_load_faces=lattice_load_faces,
                lattice_load_node_ids=lattice_load_node_ids,
                plate_z=z_plate,
                mesh_z_max=mesh_z_max,
                counter_plate_elem_ids=(
                    [e[0] for e in counter_plate_elements] if use_counter_plate else None
                ),
                counter_ref_node_id=counter_ref_node_id,
                counter_lattice_node_ids=counter_lattice_node_ids or None,
                fixed_plate_elem_ids=(
                    [e[0] for e in fixed_plate_elements] if use_fixed_bottom_plate else None
                ),
                fixed_ref_node_id=fixed_ref_node_id,
                lattice_bottom_faces=lattice_bottom_faces if use_fixed_bottom_plate else None,
            )

    return stats


def export_inp(
    nodes,
    beams,
    path: str,
    *,
    polylines: list | None = None,
    element_type: str = "C3D8R",
    **kwargs,
) -> dict[str, int | float] | None:
    """
    Unified entry point.

    element_type: "C3D8R" (default), "C3D4", or "B31" (beam).
    """
    if element_type.upper() == "B31":
        export_inp_b31(nodes, beams, path)
        return None
    if element_type.upper() in ("C3D4", "C3D4R", "C3D8R", "C3D8"):
        return export_inp_c3d4(
            nodes,
            beams,
            path,
            polylines=polylines,
            solid_element=element_type,
            **kwargs,
        )
    raise ValueError(f"Unsupported element_type: {element_type}")
