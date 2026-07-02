"""OCP (OpenCASCADE) helpers for Q=1 unit-cell octant cut + Glue fuse pilot."""

from __future__ import annotations

import os
from typing import Any, Literal

import numpy as np

from src.export.unitcell_box_cut import (
    MIN_CUT_MERGE_MASS_RATIO,
    OCTANT_CENTER_OVERLAP_MM,
    OCTANT_SEQUENTIAL_FUSE_ORDER,
    _canonical_corner_from_pipe_path,
    _octant_bounds_from_corner_mm,
    extend_pipe_path_past_cell_centre,
    extend_pipe_path_past_corner,
    octant_centre_path_extension_mm,
    pipe_part_with_both_end_path_extension,
    unitcell_octant_corners_mm,
)
from src.mesh.occ_pipe import frames_along_polyline

GlueMode = Literal["off", "shift", "full"]
FuseStrategy = Literal[
    "sequential",
    "sequential_glue_shift",
    "sequential_glue_full",
    "batch_glue_shift",
    "batch_glue_full",
    "x_layer_glue_shift",
    "x_layer_glue_full",
]

PipeBuildMode = Literal["centre_stub", "both_end_extension"]
EllipseSweepMode = Literal["frenet", "parallel_transport"]

# Gmsh healShapes tolerance after BREP roundtrip (probe: 0.05 mm fixes STEP validity).
OCP_BREP_GMSH_HEAL_MM = 0.05


def _require_ocp():
    try:
        from OCP.BRepAlgoAPI import BRepAlgoAPI_Common, BRepAlgoAPI_Fuse
        from OCP.BRepBuilderAPI import (
            BRepBuilderAPI_MakeEdge,
            BRepBuilderAPI_MakeFace,
            BRepBuilderAPI_MakeVertex,
            BRepBuilderAPI_MakeWire,
            BRepBuilderAPI_TransitionMode,
        )
        from OCP.BRepGProp import BRepGProp
        from OCP.BRepOffsetAPI import BRepOffsetAPI_MakePipeShell
        from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakeCylinder
        from OCP.BOPAlgo import BOPAlgo_GlueEnum
        from OCP.GProp import GProp_GProps
        from OCP.GeomAPI import GeomAPI_PointsToBSpline
        from OCP.STEPControl import STEPControl_AsIs, STEPControl_Writer
        from OCP.TColgp import TColgp_Array1OfPnt
        from OCP.gp import gp_Ax2, gp_Circ, gp_Dir, gp_Elips, gp_Pnt
    except ImportError as exc:
        raise ImportError(
            "OCP pilot requires cadquery-ocp. Install: pip install cadquery-ocp"
        ) from exc
    return {
        "BRepAlgoAPI_Common": BRepAlgoAPI_Common,
        "BRepAlgoAPI_Fuse": BRepAlgoAPI_Fuse,
        "BRepBuilderAPI_MakeEdge": BRepBuilderAPI_MakeEdge,
        "BRepBuilderAPI_MakeFace": BRepBuilderAPI_MakeFace,
        "BRepBuilderAPI_MakeVertex": BRepBuilderAPI_MakeVertex,
        "BRepBuilderAPI_MakeWire": BRepBuilderAPI_MakeWire,
        "BRepBuilderAPI_TransitionMode": BRepBuilderAPI_TransitionMode,
        "BRepGProp": BRepGProp,
        "BRepOffsetAPI_MakePipeShell": BRepOffsetAPI_MakePipeShell,
        "BRepPrimAPI_MakeBox": BRepPrimAPI_MakeBox,
        "BRepPrimAPI_MakeCylinder": BRepPrimAPI_MakeCylinder,
        "BOPAlgo_GlueEnum": BOPAlgo_GlueEnum,
        "GProp_GProps": GProp_GProps,
        "GeomAPI_PointsToBSpline": GeomAPI_PointsToBSpline,
        "STEPControl_AsIs": STEPControl_AsIs,
        "STEPControl_Writer": STEPControl_Writer,
        "TColgp_Array1OfPnt": TColgp_Array1OfPnt,
        "gp_Ax2": gp_Ax2,
        "gp_Circ": gp_Circ,
        "gp_Dir": gp_Dir,
        "gp_Elips": gp_Elips,
        "gp_Pnt": gp_Pnt,
    }


def ocp_mass(shape: Any) -> float:
    ocp = _require_ocp()
    props = ocp["GProp_GProps"]()
    ocp["BRepGProp"].VolumeProperties_s(shape, props)
    return float(props.Mass())


def ocp_shape_topology(
    shape: Any,
    *,
    count_faces: bool = True,
    check_brep: bool = True,
) -> dict[str, Any]:
    """Count solids/shells/(optional faces) and optional BRepCheck validity."""
    from OCP.TopAbs import TopAbs_FACE, TopAbs_SHELL, TopAbs_SOLID
    from OCP.TopExp import TopExp_Explorer

    def _count(top_abs) -> int:
        exp = TopExp_Explorer(shape, top_abs)
        n = 0
        while exp.More():
            n += 1
            exp.Next()
        return n

    out: dict[str, Any] = {
        "solids": _count(TopAbs_SOLID),
        "shells": _count(TopAbs_SHELL),
        "mass_mm3": ocp_mass(shape),
    }
    if count_faces:
        out["faces"] = _count(TopAbs_FACE)
    if check_brep:
        from OCP.BRepCheck import BRepCheck_Analyzer

        out["brep_valid"] = bool(BRepCheck_Analyzer(shape).IsValid())
    return out


def ocp_heal_fused_solid(shape: Any) -> Any:
    """Merge coplanar seams and fix minor BRep issues before STEP export."""
    from OCP.ShapeFix import ShapeFix_Shape
    from OCP.ShapeUpgrade import ShapeUpgrade_UnifySameDomain

    unified = ShapeUpgrade_UnifySameDomain(shape, True, True, True)
    unified.Build()
    healed = ShapeFix_Shape(unified.Shape())
    healed.Perform()
    return healed.Shape()


def ocp_readback_step(
    path: str,
    *,
    fast: bool = False,
) -> dict[str, Any]:
    """Read STEP back and report topology (CAD importer sanity check)."""
    from OCP.STEPControl import STEPControl_Reader

    reader = STEPControl_Reader()
    if reader.ReadFile(os.path.abspath(path)) != 1:
        raise RuntimeError(f"STEP read failed: {path}")
    reader.TransferRoots()
    shape = reader.OneShape()
    stats = ocp_shape_topology(
        shape,
        count_faces=not fast,
        check_brep=not fast,
    )
    stats["step_path"] = os.path.abspath(path)
    return stats


def ocp_write_step(shape: Any, path: str) -> None:
    ocp = _require_ocp()
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    writer = ocp["STEPControl_Writer"]()
    writer.Transfer(shape, ocp["STEPControl_AsIs"])
    status = writer.Write(os.path.abspath(path))
    if status != 1:
        raise RuntimeError(f"STEP write failed for {path} (status={status})")


def ocp_write_step_via_gmsh_brep_heal(
    shape: Any,
    path: str,
    *,
    heal_mm: float = OCP_BREP_GMSH_HEAL_MM,
    fast_readback: bool = True,
) -> dict[str, Any]:
    """
    Export a valid single-shell STEP for SolidWorks.

    Direct OCP STEP write can split internal glue seams into a second shell;
    BREP -> gmsh healShapes -> STEP fixes this (see ``scripts/_tmp_ocp_step_heal_probe.py``).
    """
    import gmsh
    from OCP.BRepTools import BRepTools

    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    abs_path = os.path.abspath(path)
    brep_path = abs_path + ".brep"
    healed = False
    try:
        print(f"  gmsh export: writing BREP...", flush=True)
        if not BRepTools.Write_s(shape, brep_path):
            raise RuntimeError(f"BREP write failed: {brep_path}")
        gmsh.initialize()
        try:
            gmsh.option.setNumber("General.Terminal", 0)
            gmsh.model.add("ocp_brep_heal")
            gmsh.model.occ.importShapes(brep_path)
            gmsh.model.occ.synchronize()
            volumes = gmsh.model.getEntities(3)
            n_vol = len(volumes)
            print(f"  gmsh export: BREP import -> {n_vol} volume(s)", flush=True)
            if n_vol > 1:
                tags = [t[1] for t in volumes]
                gmsh.model.occ.fuse([(3, tags[0])], [(3, t) for t in tags[1:]])
                gmsh.model.occ.synchronize()
                volumes = gmsh.model.getEntities(3)
                n_vol = len(volumes)
                print(f"  gmsh export: after fuse -> {n_vol} volume(s)", flush=True)
            gmsh.model.occ.removeAllDuplicates()
            gmsh.model.occ.synchronize()

            def _import_brep() -> int:
                gmsh.model.occ.importShapes(brep_path)
                gmsh.model.occ.synchronize()
                return len(gmsh.model.getEntities(3))

            try:
                print(f"  gmsh export: healShapes tol={heal_mm:g} mm...", flush=True)
                gmsh.model.occ.healShapes(
                    tolerance=float(heal_mm),
                    fixDegenerated=True,
                    fixSmallEdges=True,
                    fixSmallFaces=True,
                    sewFaces=True,
                    makeSolids=True,
                )
                gmsh.model.occ.synchronize()
                healed = True
            except Exception as exc:
                print(
                    f"  gmsh export: healShapes failed ({exc}); re-import BREP",
                    flush=True,
                )
                gmsh.model.remove()
                gmsh.model.add("ocp_brep_heal_retry")
                n_vol = _import_brep()
                print(f"  gmsh export: re-import -> {n_vol} volume(s)", flush=True)

            volumes = gmsh.model.getEntities(3)
            n_vol = len(volumes)
            if n_vol > 1:
                tags = [t[1] for t in volumes]
                gmsh.model.occ.fuse([(3, tags[0])], [(3, t) for t in tags[1:]])
                gmsh.model.occ.synchronize()
                volumes = gmsh.model.getEntities(3)
                n_vol = len(volumes)
            if n_vol != 1:
                raise RuntimeError(
                    f"gmsh export left {n_vol} volume(s), expected 1 "
                    f"(heal={'ok' if healed else 'skipped'})"
                )
            from src.mesh.occ_pipe import prune_occ_for_step_export

            prune_occ_for_step_export()
            print(f"  gmsh export: writing STEP...", flush=True)
            gmsh.write(abs_path)
        finally:
            gmsh.finalize()
    finally:
        if os.path.isfile(brep_path):
            os.remove(brep_path)

    step_bytes = os.path.getsize(abs_path) if os.path.isfile(abs_path) else 0
    if step_bytes < 1024:
        raise RuntimeError(f"gmsh STEP too small ({step_bytes} B): {abs_path}")

    if fast_readback and step_bytes > 5_000_000:
        readback = {
            "solids": 1,
            "step_path": abs_path,
            "step_bytes": step_bytes,
            "readback_skipped": True,
        }
    else:
        readback = ocp_readback_step(abs_path, fast=fast_readback)
    readback["export_route"] = "brep_gmsh_heal" if healed else "brep_gmsh_import_only"
    readback["heal_mm"] = float(heal_mm)
    readback["step_bytes"] = step_bytes
    return readback


def _as_np_points(path_pts: tuple) -> list[np.ndarray]:
    return [np.asarray(p, dtype=float) for p in path_pts]


def _spline_wire(path_pts: tuple):
    ocp = _require_ocp()
    pts = _as_np_points(path_pts)
    if len(pts) < 2:
        raise ValueError("pipe path needs at least two points")
    arr = ocp["TColgp_Array1OfPnt"](1, len(pts))
    for i, p in enumerate(pts, start=1):
        arr.SetValue(i, ocp["gp_Pnt"](float(p[0]), float(p[1]), float(p[2])))
    curve = ocp["GeomAPI_PointsToBSpline"](arr).Curve()
    edge = ocp["BRepBuilderAPI_MakeEdge"](curve).Edge()
    return ocp["BRepBuilderAPI_MakeWire"](edge).Wire()


def _polyline_wire_with_vertices(path_pts: tuple) -> tuple[Any, list[Any]]:
    """Polyline spine with explicit vertices (for multi-profile PipeShell)."""
    ocp = _require_ocp()
    pts = _as_np_points(path_pts)
    if len(pts) < 2:
        raise ValueError("pipe path needs at least two points")
    verts: list[Any] = []
    for p in pts:
        verts.append(
            ocp["BRepBuilderAPI_MakeVertex"](
                ocp["gp_Pnt"](float(p[0]), float(p[1]), float(p[2]))
            ).Vertex()
        )
    wire_builder = ocp["BRepBuilderAPI_MakeWire"]()
    for i in range(len(pts) - 1):
        edge = ocp["BRepBuilderAPI_MakeEdge"](verts[i], verts[i + 1]).Edge()
        wire_builder.Add(edge)
    return wire_builder.Wire(), verts


def _profile_wire_at_point(
    point: np.ndarray,
    tangent: np.ndarray,
    x_axis: np.ndarray,
    radius: float,
):
    ocp = _require_ocp()
    p = ocp["gp_Pnt"](float(point[0]), float(point[1]), float(point[2]))
    tz = np.asarray(tangent, dtype=float)
    tz_n = float(np.linalg.norm(tz))
    if tz_n < 1e-12:
        raise ValueError("zero tangent for pipe profile")
    tz = tz / tz_n
    tx = np.asarray(x_axis, dtype=float)
    tx = tx - float(np.dot(tx, tz)) * tz
    tx_n = float(np.linalg.norm(tx))
    if tx_n < 1e-12:
        raise ValueError("degenerate profile x-axis")
    tx = tx / tx_n
    ax = ocp["gp_Ax2"](
        p,
        ocp["gp_Dir"](float(tz[0]), float(tz[1]), float(tz[2])),
        ocp["gp_Dir"](float(tx[0]), float(tx[1]), float(tx[2])),
    )
    circ = ocp["gp_Circ"](ax, float(radius))
    edge = ocp["BRepBuilderAPI_MakeEdge"](circ).Edge()
    return ocp["BRepBuilderAPI_MakeWire"](edge).Wire()


def _profile_wire_ellipse_at_point(
    point: np.ndarray,
    tangent: np.ndarray,
    major_axis: np.ndarray,
    major_radius: float,
    minor_radius: float,
):
    ocp = _require_ocp()
    p = ocp["gp_Pnt"](float(point[0]), float(point[1]), float(point[2]))
    tz = np.asarray(tangent, dtype=float)
    tz_n = float(np.linalg.norm(tz))
    if tz_n < 1e-12:
        raise ValueError("zero tangent for pipe profile")
    tz = tz / tz_n

    tx = np.asarray(major_axis, dtype=float)
    tx = tx - float(np.dot(tx, tz)) * tz
    tx_n = float(np.linalg.norm(tx))
    if tx_n < 1e-12:
        raise ValueError("degenerate ellipse major axis")
    tx = tx / tx_n

    a = float(major_radius)
    b = float(minor_radius)
    if a <= 0.0 or b <= 0.0:
        raise ValueError("ellipse radii must be positive")
    if b > a:
        a, b = b, a

    ax = ocp["gp_Ax2"](
        p,
        ocp["gp_Dir"](float(tz[0]), float(tz[1]), float(tz[2])),
        ocp["gp_Dir"](float(tx[0]), float(tx[1]), float(tx[2])),
    )
    el = ocp["gp_Elips"](ax, float(a), float(b))
    edge = ocp["BRepBuilderAPI_MakeEdge"](el).Edge()
    return ocp["BRepBuilderAPI_MakeWire"](edge).Wire()


def ocp_elliptic_pipe_parallel_transport(
    path_pts: tuple,
    *,
    major_radius: float,
    minor_radius: float,
    compression_axis: np.ndarray,
    align_up_to: str = "minor",
) -> Any:
    """
    Elliptic pipe with explicit parallel-transport profiles at each path vertex.

    At every polyline knot the ellipse major axis is recomputed from the local
    tangent and global compression direction (no centre junction sphere).
    """
    from src.mesh.occ_pipe import _major_axis_from_up

    ocp = _require_ocp()
    pts = _as_np_points(path_pts)
    if len(pts) < 2:
        raise ValueError("pipe path needs at least two points")

    wire, spine_verts = _polyline_wire_with_vertices(path_pts)
    frames = frames_along_polyline(pts)
    up = np.asarray(compression_axis, dtype=float)

    shell = ocp["BRepOffsetAPI_MakePipeShell"](wire)
    shell.SetMode(False)
    tm = ocp["BRepBuilderAPI_TransitionMode"]
    shell.SetTransitionMode(tm.BRepBuilderAPI_RoundCorner)

    for pt, vert, (e_z, e_x, _) in zip(pts, spine_verts, frames):
        major_hint = _major_axis_from_up(
            e_z,
            up=up,
            fallback_x=e_x,
            align_up_to=str(align_up_to),
        )
        profile = _profile_wire_ellipse_at_point(
            pt,
            e_z,
            major_hint,
            float(major_radius),
            float(minor_radius),
        )
        shell.Add(profile, vert, False, True)

    shell.Build()
    if not shell.IsDone():
        raise RuntimeError("OCP parallel-transport MakePipeShell failed")
    if not shell.MakeSolid():
        raise RuntimeError("OCP parallel-transport MakePipeShell MakeSolid failed")
    return shell.Shape()


def ocp_elliptic_pipe_along_points(
    path_pts: tuple,
    *,
    major_radius: float,
    minor_radius: float,
    major_axis_hint: np.ndarray,
    open_at_start: bool = False,
) -> Any:
    """
    Spline pipe sweep with an elliptic profile.

    The ellipse plane is normal to the local tangent at the sweep start; its
    major axis is oriented by ``major_axis_hint`` projected into that plane.
    """
    ocp = _require_ocp()
    pts = _as_np_points(path_pts)
    if len(pts) < 2:
        raise ValueError("pipe path needs at least two points")

    if open_at_start:
        if len(pts) < 3:
            raise ValueError("open_at_start pipe needs at least three path points")
        sweep_pts = pts[1:]
        frames = frames_along_polyline(pts)
        e_z, _, _ = frames[1]
    else:
        sweep_pts = pts
        frames = frames_along_polyline(pts)
        e_z, _, _ = frames[0]

    wire = _spline_wire(tuple(tuple(float(v) for v in p) for p in sweep_pts))
    profile = _profile_wire_ellipse_at_point(
        sweep_pts[0],
        e_z,
        np.asarray(major_axis_hint, dtype=float),
        float(major_radius),
        float(minor_radius),
    )
    shell = ocp["BRepOffsetAPI_MakePipeShell"](wire)
    # CorrectedFrenet (IsFrenet=False) — matches gmsh addPipe(..., trihedron="CorrectedFrenet").
    shell.SetMode(False)
    shell.Add(profile)
    shell.Build()
    if not shell.IsDone():
        raise RuntimeError("OCP MakePipeShell failed")
    if not shell.MakeSolid():
        raise RuntimeError("OCP MakePipeShell MakeSolid failed")
    return shell.Shape()


def ocp_pipe_along_points(
    path_pts: tuple,
    radius: float,
    *,
    open_at_start: bool = False,
) -> Any:
    """Spline pipe sweep with parallel-transport profile (gmsh CorrectedFrenet analogue)."""
    ocp = _require_ocp()
    pts = _as_np_points(path_pts)
    if open_at_start:
        if len(pts) < 3:
            raise ValueError("open_at_start pipe needs at least three path points")
        sweep_pts = pts[1:]
        frames = frames_along_polyline(pts)
        e_z, e_x, _ = frames[1]
    else:
        sweep_pts = pts
        frames = frames_along_polyline(pts)
        e_z, e_x, _ = frames[0]

    wire = _spline_wire(tuple(tuple(float(v) for v in p) for p in sweep_pts))
    profile = _profile_wire_at_point(sweep_pts[0], e_z, e_x, radius)
    shell = ocp["BRepOffsetAPI_MakePipeShell"](wire)
    shell.SetMode(False)
    shell.Add(profile)
    shell.Build()
    if not shell.IsDone():
        raise RuntimeError("OCP MakePipeShell failed")
    if not shell.MakeSolid():
        raise RuntimeError("OCP MakePipeShell MakeSolid failed")
    return shell.Shape()


def ocp_pipe_with_centre_stub(path_pts: tuple, radius: float) -> Any:
    """Chord cylinder at cell centre + open-start spline pipe (Q=1 octant route)."""
    pts = _as_np_points(path_pts)
    if len(pts) < 2:
        raise ValueError("pipe path needs at least two points")
    p0, p1 = pts[0], pts[1]
    chord = p1 - p0
    length = float(np.linalg.norm(chord))
    if length < 1e-9:
        return ocp_pipe_along_points(path_pts, radius)

    ocp = _require_ocp()
    direction = chord / length
    ax = ocp["gp_Ax2"](
        ocp["gp_Pnt"](float(p0[0]), float(p0[1]), float(p0[2])),
        ocp["gp_Dir"](
            float(direction[0]),
            float(direction[1]),
            float(direction[2]),
        ),
    )
    cyl = ocp["BRepPrimAPI_MakeCylinder"](ax, float(radius), length).Shape()
    pipe = ocp_pipe_along_points(path_pts, radius, open_at_start=True)
    return ocp_fuse_pair(cyl, pipe, glue="off", fuzzy_mm=1e-3, label="centre-stub")


def _box_from_bounds(bounds: tuple[float, float, float, float, float, float]) -> Any:
    ocp = _require_ocp()
    xmin, xmax, ymin, ymax, zmin, zmax = map(float, bounds)
    return ocp["BRepPrimAPI_MakeBox"](
        ocp["gp_Pnt"](xmin, ymin, zmin),
        xmax - xmin,
        ymax - ymin,
        zmax - zmin,
    ).Shape()


def ocp_clip_to_periodic_cell(
    shape: Any,
    center_xyz: tuple[float, float, float],
    cell_size: float,
) -> Any:
    """Clip one centred unit cell to its nominal [-L/2,L/2]^3 periodic box."""
    h = 0.5 * float(cell_size)
    cx, cy, cz = (float(center_xyz[0]), float(center_xyz[1]), float(center_xyz[2]))
    box = _box_from_bounds(
        (cx - h, cx + h, cy - h, cy + h, cz - h, cz + h)
    )
    clipped = ocp_common(shape, box)
    mass = ocp_mass(clipped)
    if mass <= 0.0:
        raise RuntimeError(
            f"periodic clip empty (center=({cx:g},{cy:g},{cz:g}), L={cell_size:g})"
        )
    return clipped


def ocp_common(a: Any, b: Any) -> Any:
    ocp = _require_ocp()
    op = ocp["BRepAlgoAPI_Common"](a, b)
    op.Build()
    if not op.IsDone():
        raise RuntimeError("OCP common (intersect) failed")
    return op.Shape()


def _glue_enum(glue: GlueMode):
    ocp = _require_ocp()
    if glue == "off":
        return ocp["BOPAlgo_GlueEnum"].BOPAlgo_GlueOff
    if glue == "shift":
        return ocp["BOPAlgo_GlueEnum"].BOPAlgo_GlueShift
    if glue == "full":
        return ocp["BOPAlgo_GlueEnum"].BOPAlgo_GlueFull
    raise ValueError(f"unknown glue mode: {glue!r}")


def _configure_bop_fuse(
    op: Any,
    *,
    glue: GlueMode,
    fuzzy_mm: float,
    simplify: bool,
) -> None:
    if glue != "off":
        op.SetGlue(_glue_enum(glue))
    if fuzzy_mm > 0.0:
        op.SetFuzzyValue(float(fuzzy_mm))
    if simplify and hasattr(op, "SimplifyResult"):
        op.SimplifyResult(True)


def ocp_fuse_pair(
    a: Any,
    b: Any,
    *,
    glue: GlueMode = "off",
    fuzzy_mm: float = 1e-3,
    simplify: bool = True,
    label: str = "fuse",
) -> Any:
    ocp = _require_ocp()
    op = ocp["BRepAlgoAPI_Fuse"](a, b)
    _configure_bop_fuse(op, glue=glue, fuzzy_mm=fuzzy_mm, simplify=simplify)
    op.Build()
    if not op.IsDone():
        raise RuntimeError(
            f"OCP fuse failed ({label}, glue={glue}, fuzzy={fuzzy_mm:g} mm)"
        )
    shape = op.Shape()
    if ocp_mass(shape) <= 0.0:
        raise RuntimeError(
            f"OCP fuse empty result ({label}, glue={glue}, fuzzy={fuzzy_mm:g} mm)"
        )
    return shape


def ocp_fuse_batch(
    shapes: list[Any],
    *,
    glue: GlueMode = "off",
    fuzzy_mm: float = 1e-3,
    simplify: bool = True,
    label: str = "fuse-batch",
) -> Any:
    """Fuse N solids in one BOP call (first = argument, rest = tools)."""
    if not shapes:
        raise RuntimeError(f"{label}: no shapes")
    if len(shapes) == 1:
        return shapes[0]

    from OCP.TopTools import TopTools_ListOfShape

    args = TopTools_ListOfShape()
    tools = TopTools_ListOfShape()
    args.Append(shapes[0])
    for shape in shapes[1:]:
        tools.Append(shape)

    ocp = _require_ocp()
    op = ocp["BRepAlgoAPI_Fuse"]()
    op.SetArguments(args)
    op.SetTools(tools)
    _configure_bop_fuse(op, glue=glue, fuzzy_mm=fuzzy_mm, simplify=simplify)
    op.Build()
    if not op.IsDone():
        raise RuntimeError(
            f"OCP batch fuse failed ({label}, n={len(shapes)}, "
            f"glue={glue}, fuzzy={fuzzy_mm:g} mm)"
        )
    result = op.Shape()
    if ocp_mass(result) <= 0.0:
        raise RuntimeError(
            f"OCP batch fuse empty result ({label}, n={len(shapes)}, "
            f"glue={glue}, fuzzy={fuzzy_mm:g} mm)"
        )
    return result


def _order_octant_shapes(
    shapes: list[Any],
    order: tuple[int, ...] = OCTANT_SEQUENTIAL_FUSE_ORDER,
) -> list[Any]:
    if len(shapes) != len(order):
        return list(shapes)
    return [shapes[i] for i in order]


def _fuse_group_sequential(
    shapes: list[Any],
    *,
    cut_mass: float,
    glue: GlueMode,
    fuzzy_mm: float,
    label: str,
) -> Any:
    if not shapes:
        raise RuntimeError(f"{label}: no shapes")
    if len(shapes) == 1:
        return shapes[0]

    acc = shapes[0]
    mean_piece = float(cut_mass) / max(1, len(shapes))
    min_step_delta = 0.25 * mean_piece
    for idx, shape in enumerate(shapes[1:], start=2):
        prev_mass = ocp_mass(acc)
        piece_mass = ocp_mass(shape)
        acc = ocp_fuse_pair(
            acc,
            shape,
            glue=glue,
            fuzzy_mm=fuzzy_mm,
            label=f"{label} step {idx}",
        )
        new_mass = ocp_mass(acc)
        if new_mass < prev_mass + min_step_delta:
            raise RuntimeError(
                f"{label}: step {idx}/{len(shapes)} mass drop "
                f"({new_mass:.1f} < {prev_mass + min_step_delta:.1f}; "
                f"piece ~{piece_mass:.1f})"
            )
        print(
            f"  {label}: fused {idx}/{len(shapes)} mass={new_mass:.1f} mm3",
            flush=True,
        )
    return acc


def _fuse_batch(
    shapes: list[Any],
    *,
    glue: GlueMode,
    fuzzy_mm: float,
    label: str,
) -> Any:
    if len(shapes) == 1:
        return shapes[0]
    acc = shapes[0]
    for idx, shape in enumerate(shapes[1:], start=2):
        acc = ocp_fuse_pair(
            acc,
            shape,
            glue=glue,
            fuzzy_mm=fuzzy_mm,
            label=f"{label} batch {idx}",
        )
    return acc


def fuse_octant_shapes(
    shapes: list[Any],
    *,
    cut_mass: float,
    strategy: FuseStrategy,
    fuzzy_mm: float = 1e-3,
    cell_size_mm: float = 20.0,
) -> tuple[Any, str]:
    """Merge eight octant-cut solids with the requested Glue strategy."""
    ordered = _order_octant_shapes(shapes)
    min_mass = MIN_CUT_MERGE_MASS_RATIO * float(cut_mass)

    if strategy == "sequential":
        merged = _fuse_group_sequential(
            ordered,
            cut_mass=cut_mass,
            glue="off",
            fuzzy_mm=fuzzy_mm,
            label="ocp-sequential",
        )
        desc = f"sequential (order {list(OCTANT_SEQUENTIAL_FUSE_ORDER)}, glue=off)"
    elif strategy == "sequential_glue_shift":
        merged = _fuse_group_sequential(
            ordered,
            cut_mass=cut_mass,
            glue="shift",
            fuzzy_mm=fuzzy_mm,
            label="ocp-seq-glue-shift",
        )
        desc = f"sequential + GlueShift (order {list(OCTANT_SEQUENTIAL_FUSE_ORDER)})"
    elif strategy == "sequential_glue_full":
        merged = _fuse_group_sequential(
            ordered,
            cut_mass=cut_mass,
            glue="full",
            fuzzy_mm=fuzzy_mm,
            label="ocp-seq-glue-full",
        )
        desc = f"sequential + GlueFull (order {list(OCTANT_SEQUENTIAL_FUSE_ORDER)})"
    elif strategy == "batch_glue_shift":
        merged = _fuse_batch(
            ordered,
            glue="shift",
            fuzzy_mm=fuzzy_mm,
            label="ocp-batch-glue-shift",
        )
        desc = "batch fuse all + GlueShift"
    elif strategy == "batch_glue_full":
        merged = _fuse_batch(
            ordered,
            glue="full",
            fuzzy_mm=fuzzy_mm,
            label="ocp-batch-glue-full",
        )
        desc = "batch fuse all + GlueFull"
    elif strategy in ("x_layer_glue_shift", "x_layer_glue_full"):
        glue: GlueMode = "shift" if strategy.endswith("shift") else "full"
        corners = unitcell_octant_corners_mm(cell_size_mm)
        neg = [shapes[i] for i, c in enumerate(corners) if c[0] < 0]
        pos = [shapes[i] for i, c in enumerate(corners) if c[0] > 0]
        left = _fuse_group_sequential(
            neg,
            cut_mass=cut_mass,
            glue=glue,
            fuzzy_mm=fuzzy_mm,
            label="ocp-x-neg",
        )
        right = _fuse_group_sequential(
            pos,
            cut_mass=cut_mass,
            glue=glue,
            fuzzy_mm=fuzzy_mm,
            label="ocp-x-pos",
        )
        merged = ocp_fuse_pair(
            left,
            right,
            glue=glue,
            fuzzy_mm=fuzzy_mm,
            label="ocp-x-halves",
        )
        desc = f"x-layer halves + Glue{glue.title()}"
    else:
        raise ValueError(f"unknown fuse strategy: {strategy!r}")

    merged_mass = ocp_mass(merged)
    if cut_mass > 0.0 and merged_mass < min_mass:
        raise RuntimeError(
            f"{strategy}: merged mass {merged_mass:.1f} mm3 < "
            f"{min_mass:.1f} mm3 ({MIN_CUT_MERGE_MASS_RATIO:.0%} of cut sum)"
        )
    ratio = merged_mass / cut_mass if cut_mass > 0.0 else 0.0
    print(
        f"  ocp fuse OK: strategy={strategy} mass={merged_mass:.1f} "
        f"ratio={ratio:.3f}",
        flush=True,
    )
    return merged, desc


def _ocp_pipe_solid_for_part(
    part: tuple[str, tuple, float],
    *,
    pipe_mode: PipeBuildMode,
    cell_size_mm: float,
    centre_extension_mm: float | None,
    corner_extension_mm: float | None,
    ellipse_sweep_mode: EllipseSweepMode = "frenet",
) -> tuple[Any, tuple[float, float, float]]:
    """Build one full pipe solid and return (shape, canonical corner)."""
    kind = part[0]
    if kind not in ("pipe", "pipe_ellipse"):
        raise ValueError(f"expected pipe, got {kind!r}")

    if kind == "pipe":
        path_pts, radius = part[1], float(part[2])
        ellipse_kwargs: dict[str, Any] = {}
    else:
        path_pts, r_major, r_minor, comp, align = part[1:]
        radius = float(r_major)
        from src.mesh.occ_pipe import _major_axis_from_up, frames_along_polyline

        pts = [np.asarray(p, dtype=float) for p in path_pts]
        e_z, e_x, _ = frames_along_polyline(pts)[0]
        major_hint = _major_axis_from_up(
            e_z,
            up=np.asarray(comp, dtype=float),
            fallback_x=e_x,
            align_up_to=str(align),
        )
        ellipse_kwargs = {
            "major_radius": float(r_major),
            "minor_radius": float(r_minor),
            "major_axis_hint": major_hint,
            "compression_axis": np.asarray(comp, dtype=float),
            "align_up_to": str(align),
            "sweep_mode": str(ellipse_sweep_mode),
        }

    corner = _canonical_corner_from_pipe_path(path_pts, cell_size_mm)
    if pipe_mode == "centre_stub":
        if kind == "pipe_ellipse":
            raise ValueError("centre_stub not supported for elliptic pipes")
        return ocp_pipe_with_centre_stub(path_pts, float(radius)), corner

    centre_ext = (
        float(centre_extension_mm)
        if centre_extension_mm is not None
        else octant_centre_path_extension_mm(float(radius))
    )
    corner_ext = (
        float(corner_extension_mm)
        if corner_extension_mm is not None
        else centre_ext
    )
    if kind == "pipe":
        _, extended_path, _ = pipe_part_with_both_end_path_extension(
            part,
            centre_ext,
            corner_extension_mm=corner_ext,
        )
        return ocp_pipe_along_points(extended_path, float(radius)), corner

    path = path_pts
    if centre_ext > 0.0:
        path = extend_pipe_path_past_cell_centre(path, centre_ext)
    if corner_ext > 0.0:
        path = extend_pipe_path_past_corner(path, corner_ext)
    if ellipse_kwargs.get("sweep_mode") == "parallel_transport":
        return (
            ocp_elliptic_pipe_parallel_transport(
                path,
                major_radius=ellipse_kwargs["major_radius"],
                minor_radius=ellipse_kwargs["minor_radius"],
                compression_axis=ellipse_kwargs["compression_axis"],
                align_up_to=ellipse_kwargs["align_up_to"],
            ),
            corner,
        )
    return (
        ocp_elliptic_pipe_along_points(
            path,
            major_radius=ellipse_kwargs["major_radius"],
            minor_radius=ellipse_kwargs["minor_radius"],
            major_axis_hint=ellipse_kwargs["major_axis_hint"],
        ),
        corner,
    )


def build_q1_octant_cut_shapes(
    pipe_parts: list[tuple[str, tuple, float]],
    cell_size_mm: float,
    *,
    center_overlap_mm: float = OCTANT_CENTER_OVERLAP_MM,
    pipe_mode: PipeBuildMode = "centre_stub",
    centre_extension_mm: float | None = None,
    corner_extension_mm: float | None = None,
    corner_offset_mm: tuple[float, float, float] = (0.0, 0.0, 0.0),
    ellipse_sweep_mode: EllipseSweepMode = "frenet",
) -> tuple[list[Any], float, float]:
    """
    Build eight aligned octant-cut OCP solids.

    ``pipe_mode=centre_stub`` — chord cylinder + open-start pipe (gmsh default).
    ``pipe_mode=both_end_extension`` — extend path at centre and corner before sweep.
    """
    corners = unitcell_octant_corners_mm(cell_size_mm)
    ox, oy, oz = (
        float(corner_offset_mm[0]),
        float(corner_offset_mm[1]),
        float(corner_offset_mm[2]),
    )
    if abs(ox) > 1e-12 or abs(oy) > 1e-12 or abs(oz) > 1e-12:
        corners = [(c[0] + ox, c[1] + oy, c[2] + oz) for c in corners]
    if len(pipe_parts) != 8:
        raise ValueError(f"expected 8 pipe parts, got {len(pipe_parts)}")

    corner_tol = max(1e-3, 1e-6 * float(cell_size_mm))
    cut_shapes: list[Any] = []
    pipe_ref_mass = 0.0
    if pipe_mode == "both_end_extension":
        sample_r = float(pipe_parts[0][2])
        auto_ext = octant_centre_path_extension_mm(sample_r)
        print(
            f"  ocp octant cut: pipe_mode=both_end_extension "
            f"(centre={centre_extension_mm or auto_ext:g} mm "
            f"corner={corner_extension_mm or (centre_extension_mm or auto_ext):g} mm)",
            flush=True,
        )
    else:
        print("  ocp octant cut: pipe_mode=centre_stub", flush=True)
    if ellipse_sweep_mode == "parallel_transport":
        print("  ocp octant cut: ellipse_sweep=parallel_transport", flush=True)

    for idx, part in enumerate(pipe_parts, start=1):
        corner = corners[idx - 1]
        path_corner = _canonical_corner_from_pipe_path(part[1], cell_size_mm)
        if any(abs(path_corner[i] - corner[i]) > corner_tol for i in range(3)):
            raise RuntimeError(
                f"strut {idx}: endpoint {path_corner} != octant corner {corner}"
            )
        pipe_solid, _ = _ocp_pipe_solid_for_part(
            part,
            pipe_mode=pipe_mode,
            cell_size_mm=cell_size_mm,
            centre_extension_mm=centre_extension_mm,
            corner_extension_mm=corner_extension_mm,
            ellipse_sweep_mode=ellipse_sweep_mode,
        )
        pipe_ref_mass += ocp_mass(pipe_solid)
        bounds = _octant_bounds_from_corner_mm(
            corner,
            cell_size_mm,
            center_overlap_mm=center_overlap_mm,
        )
        box = _box_from_bounds(bounds)
        cut = ocp_common(pipe_solid, box)
        cut_mass = ocp_mass(cut)
        if cut_mass <= 0.0:
            raise RuntimeError(f"strut {idx}: octant cut produced zero mass")
        cut = ocp_common(cut, box)
        cut_shapes.append(cut)
        print(
            f"  octant cut strut {idx}/8 mass={cut_mass:.1f} mm3 corner={corner}",
            flush=True,
        )

    cut_sum = sum(ocp_mass(s) for s in cut_shapes)
    return cut_shapes, pipe_ref_mass, cut_sum


def export_q1_ocp_glue_unitcell(
    pipe_parts: list[tuple[str, tuple, float]],
    out_step: str,
    *,
    cell_size_mm: float = 20.0,
    strategy: FuseStrategy = "sequential_glue_shift",
    fuzzy_mm: float = 1e-3,
    center_overlap_mm: float = OCTANT_CENTER_OVERLAP_MM,
    pipe_mode: PipeBuildMode = "centre_stub",
    centre_extension_mm: float | None = None,
    corner_extension_mm: float | None = None,
    ellipse_sweep_mode: EllipseSweepMode = "frenet",
) -> dict[str, Any]:
    """Full Q=1 pilot: octant cuts + Glue fuse + STEP export."""
    cut_shapes, pipe_ref_mass, cut_mass = build_q1_octant_cut_shapes(
        pipe_parts,
        cell_size_mm,
        center_overlap_mm=center_overlap_mm,
        pipe_mode=pipe_mode,
        centre_extension_mm=centre_extension_mm,
        corner_extension_mm=corner_extension_mm,
        ellipse_sweep_mode=ellipse_sweep_mode,
    )
    merged, fuse_desc = fuse_octant_shapes(
        cut_shapes,
        cut_mass=cut_mass,
        strategy=strategy,
        fuzzy_mm=fuzzy_mm,
        cell_size_mm=cell_size_mm,
    )
    merged_mass = ocp_mass(merged)
    mem_raw = ocp_shape_topology(merged)
    export_shape = ocp_heal_fused_solid(merged)
    mem_healed = ocp_shape_topology(export_shape)
    step_readback = ocp_write_step_via_gmsh_brep_heal(export_shape, out_step)
    return {
        "step_path": os.path.abspath(out_step),
        "method": "ocp_octant_glue_fuse",
        "fuse_strategy": fuse_desc,
        "strategy_key": strategy,
        "cell_size_mm": float(cell_size_mm),
        "pipe_ref_mass_mm3": pipe_ref_mass,
        "octant_cut_sum_mm3": cut_mass,
        "merged_mass_mm3": merged_mass,
        "mass_ratio": merged_mass / cut_mass if cut_mass > 0.0 else None,
        "fuzzy_mm": float(fuzzy_mm),
        "center_overlap_mm": float(center_overlap_mm),
        "pipe_mode": pipe_mode,
        "ellipse_sweep_mode": ellipse_sweep_mode,
        "centre_path_extension_mm": centre_extension_mm,
        "corner_path_extension_mm": corner_extension_mm,
        "pipe_count": len(pipe_parts),
        "mem_raw_topology": mem_raw,
        "mem_healed_topology": mem_healed,
        "step_readback_topology": step_readback,
        "step_solid_ok": bool(step_readback.get("brep_valid")),
        "step_export_route": step_readback.get("export_route"),
    }
