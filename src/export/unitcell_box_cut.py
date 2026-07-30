"""Paper-style unit cell: pipe sweep + virtual hexahedron boolean cut (no junction spheres).

Same pipe-first OCC sweep as ``export_lattice_step_occ`` (CorrectedFrenet + spline wire),
but the RVE boundary is a cube L×L×L centred on the cell origin. Strut ends on cell
faces/edges/corners become planar cut caps instead of nodal sphere connections.
"""

from __future__ import annotations

import os
from typing import Any

from src.export.export_sw import (
    _collect_solid_primitives,
    _configure_occ_for_fuse,
    _finalize_occ_step_write,
    _occ_dimtags_from_parts,
    _occ_fuse_dimtags,
    _occ_fuse_sequential,
    _occ_fuse_unitcell_pipe_first,
    _occ_list_volume_dimtags,
    _occ_primary_volume,
    _occ_remove_all_volumes_except,
    _occ_remove_volumes_in_set,
    _occ_unify_volumes_to_one,
    _occ_volume_dimtag,
    _occ_volumes_mass,
    _postprocess_written_step,
)
from src.export.array_auto_fuse import _fuse_occ_layer_volumes_safe
from src.mesh.occ_pipe import prune_occ_for_step_export
from src.generator.hu_bai_bcc import is_q1_period, q1_paper_orientation_label

# Q=1: OCC batch pipe fuse drops struts at the centre junction.
# Weld sphere must be ≥~1.70× rod radius for batch merge; trim subtracts excess ball.
Q1_CENTRE_WELD_RADIUS_SCALE = 1.70
Q1_CENTRE_TRIM_RADIUS_SCALE = 1.50
# Lose one of eight struts (~12.5%) must fail. Old 0.85 allowed silent single-rod drops.
MIN_CUT_MERGE_MASS_RATIO = 0.95
# Pipe-first intra-fuse can lose a few % to boolean topology without dropping a strut
# (e.g. Q=0.5 ≈0.95). Still fails if ~1 strut missing (~0.875).
PIPE_FIRST_INTRA_FUSE_MIN_MASS_RATIO = 0.90
# Q=1: pipe-first fuse at centre fails; use per-strut 1/8 octant box-cut +
# sequential pairwise fuse (see docs/单胞融合策略.md).
# Total overlap thickness at each x/y/z=0 bisector during OCC cut/fuse (mm).
# Applied symmetrically: each octant extends ±overlap/2 about the bisector so
# eight nominal virtual cubes stay centred on x/y/z=0 (outer faces ±L/2).
OCTANT_CENTER_OVERLAP_MM = 0.02
# Per-strut sequential fuse order (0-based strut indices).
# Historical ``(…, 7, 6)`` put idx6 ``(−,+,+)`` last and left a hub void on thin rods
# (af2q1_deq1p5_k1, 2026-07-29 visual). Natural ``0..7`` (6 then 7) fixes that case;
# deq=2 smoke still 1-solid ~382 mm³. See docs/单胞融合策略.md.
OCTANT_SEQUENTIAL_FUSE_ORDER = (0, 1, 2, 3, 4, 5, 6, 7)
# Extend centre-end path before pipe sweep so the cell centre is interior to the
# solid (end cap sits in adjacent octants and is removed by the 1/8 box cut).
OCTANT_CENTRE_PATH_EXTENSION_SCALE = 1.5
OCTANT_CENTRE_PATH_EXTENSION_MIN_MM = 1.0


def octant_centre_path_extension_mm(rod_radius_mm: float) -> float:
    """Path stub past (0,0,0) so pipe fill reaches origin cleanly after octant cut."""
    radius = float(rod_radius_mm)
    return max(
        OCTANT_CENTRE_PATH_EXTENSION_MIN_MM,
        OCTANT_CENTRE_PATH_EXTENSION_SCALE * radius,
    )


def extend_pipe_path_past_cell_centre(
    path_pts: tuple[tuple[float, ...], ...],
    extension_mm: float,
) -> tuple[tuple[float, float, float], ...]:
    """
    Prepend a point before the cell centre, continuing the first chord backward.

    The pipe end cap moves into neighbouring octants; after the 1/8 box cut the
    centre node lies on the solid interior with planar faces on x/y/z=0.
    """
    import numpy as np

    if float(extension_mm) <= 0.0 or len(path_pts) < 2:
        return tuple(tuple(float(v) for v in p) for p in path_pts)
    pts = [np.asarray(p, dtype=float) for p in path_pts]
    p0, p1 = pts[0], pts[1]
    chord = p1 - p0
    length = float(np.linalg.norm(chord))
    if length < 1e-12:
        return tuple(tuple(float(v) for v in p) for p in path_pts)
    direction = chord / length
    p0_ext = p0 - direction * float(extension_mm)
    extended: list[tuple[float, float, float]] = [
        (float(p0_ext[0]), float(p0_ext[1]), float(p0_ext[2]))
    ]
    extended.extend((float(p[0]), float(p[1]), float(p[2])) for p in path_pts)
    return tuple(extended)


def extend_pipe_path_past_corner(
    path_pts: tuple[tuple[float, ...], ...],
    extension_mm: float,
) -> tuple[tuple[float, float, float], ...]:
    """
    Append a point beyond the corner endpoint, continuing the last chord forward.

    The pipe end cap moves past the RVE corner; after the 1/8 box cut the corner
    end lies on a planar face at the outer RVE boundary.
    """
    import numpy as np

    if float(extension_mm) <= 0.0 or len(path_pts) < 2:
        return tuple(tuple(float(v) for v in p) for p in path_pts)
    pts = [np.asarray(p, dtype=float) for p in path_pts]
    p_prev, p_corner = pts[-2], pts[-1]
    chord = p_corner - p_prev
    length = float(np.linalg.norm(chord))
    if length < 1e-12:
        return tuple(tuple(float(v) for v in p) for p in path_pts)
    direction = chord / length
    p_ext = p_corner + direction * float(extension_mm)
    extended: list[tuple[float, float, float]] = [
        (float(p[0]), float(p[1]), float(p[2])) for p in path_pts
    ]
    extended.append((float(p_ext[0]), float(p_ext[1]), float(p_ext[2])))
    return tuple(extended)


def _pipe_sweep_nominal_radius(part: tuple) -> float:
    """Major sweep radius for path extensions and centre-weld sizing."""
    kind = part[0]
    if kind == "pipe":
        return float(part[2])
    if kind == "pipe_ellipse":
        return float(part[2])
    raise ValueError(f"unsupported pipe sweep kind: {kind!r}")


def pipe_part_with_centre_path_extension(
    part: tuple[str, tuple, float],
    extension_mm: float,
) -> tuple:
    kind = part[0]
    if kind not in ("pipe", "pipe_ellipse") or float(extension_mm) <= 0.0:
        return part
    path_pts = part[1]
    new_path = extend_pipe_path_past_cell_centre(path_pts, extension_mm)
    if kind == "pipe":
        return (kind, new_path, part[2])
    return (kind, new_path, part[2], part[3], part[4], part[5])


def pipe_part_with_both_end_path_extension(
    part: tuple[str, tuple, float],
    centre_extension_mm: float,
    *,
    corner_extension_mm: float | None = None,
) -> tuple:
    """Extend pipe path at cell centre and corner before sweep."""
    kind = part[0]
    if kind not in ("pipe", "pipe_ellipse"):
        return part
    centre_ext = float(centre_extension_mm)
    corner_ext = (
        float(corner_extension_mm)
        if corner_extension_mm is not None
        else centre_ext
    )
    path = part[1]
    if centre_ext > 0.0:
        path = extend_pipe_path_past_cell_centre(path, centre_ext)
    if corner_ext > 0.0:
        path = extend_pipe_path_past_corner(path, corner_ext)
    if kind == "pipe":
        return (kind, path, part[2])
    return (kind, path, part[2], part[3], part[4], part[5])


def pipe_parts_with_centre_path_extension(
    pipe_parts: list[tuple[str, tuple, float]],
    *,
    extension_mm: float | None = None,
) -> tuple[list[tuple[str, tuple, float]], float]:
    """Extend every pipe path at the cell centre; return parts and extension used."""
    if not pipe_parts:
        return pipe_parts, 0.0
    sample_radius = _pipe_sweep_nominal_radius(pipe_parts[0])
    ext = (
        float(extension_mm)
        if extension_mm is not None
        else octant_centre_path_extension_mm(sample_radius)
    )
    return [pipe_part_with_centre_path_extension(p, ext) for p in pipe_parts], ext


def pipe_parts_with_both_end_path_extension(
    pipe_parts: list[tuple[str, tuple, float]],
    *,
    centre_extension_mm: float | None = None,
    corner_extension_mm: float | None = None,
) -> tuple[list[tuple[str, tuple, float]], float, float]:
    """Extend every pipe path at centre and corner; return parts and extensions used."""
    if not pipe_parts:
        return pipe_parts, 0.0, 0.0
    sample_radius = _pipe_sweep_nominal_radius(pipe_parts[0])
    centre_ext = (
        float(centre_extension_mm)
        if centre_extension_mm is not None
        else octant_centre_path_extension_mm(sample_radius)
    )
    corner_ext = (
        float(corner_extension_mm)
        if corner_extension_mm is not None
        else centre_ext
    )
    extended = [
        pipe_part_with_both_end_path_extension(
            p,
            centre_ext,
            corner_extension_mm=corner_ext,
        )
        for p in pipe_parts
    ]
    return extended, centre_ext, corner_ext


def unitcell_box_bounds_mm(cell_size_mm: float) -> tuple[float, float, float, float, float, float]:
    """Origin-centred RVE box (matches HuBaiLatticeGenerator single-cell block)."""
    h = 0.5 * float(cell_size_mm)
    return (-h, h, -h, h, -h, h)


def unitcell_octant_corners_mm(
    cell_size_mm: float,
) -> list[tuple[float, float, float]]:
    """
    Eight centre→corner endpoints in generator order (matches octant tree merge).

    Index 0..7 pairs as (x01, x23, x45, x67) then (y0, y1) then z0.
    """
    h = 0.5 * float(cell_size_mm)
    return [
        (-h, -h, -h),
        (h, -h, -h),
        (-h, h, -h),
        (h, h, -h),
        (-h, -h, h),
        (h, -h, h),
        (-h, h, h),
        (h, h, h),
    ]


def unitcell_octant_corner_signs(
    corner: tuple[float, float, float],
    cell_size_mm: float,
) -> tuple[int, int, int]:
    """Return (sx, sy, sz) with each sign in {−1, +1} for a cell corner at ±L/2."""
    h = 0.5 * float(cell_size_mm)
    tol = max(1e-6, 1e-9 * abs(h))
    signs: list[int] = []
    for coord in corner:
        c = float(coord)
        if abs(abs(c) - h) > tol:
            raise ValueError(
                f"octant corner coordinate {c:g} mm is not ±{h:g} mm (L={cell_size_mm:g})"
            )
        signs.append(1 if c > 0.0 else -1)
    return (signs[0], signs[1], signs[2])


def unitcell_octant_nominal_bounds_mm(
    corner: tuple[float, float, float],
    cell_size_mm: float,
) -> tuple[float, float, float, float, float, float]:
    """
    Exact 1/8 block faces on x/y/z=0 and the outer RVE faces at ±L/2.

    Used for alignment QA; OCC cut may extend centre faces by ``center_overlap_mm``.
    """
    h = 0.5 * float(cell_size_mm)
    sx, sy, sz = unitcell_octant_corner_signs(corner, cell_size_mm)

    def axis_bounds(sign: int) -> tuple[float, float]:
        return (-h, 0.0) if sign < 0 else (0.0, h)

    xa, xb = axis_bounds(sx)
    ya, yb = axis_bounds(sy)
    za, zb = axis_bounds(sz)
    return (xa, xb, ya, yb, za, zb)


def verify_unitcell_octant_partition_mm(
    cell_size_mm: float,
    *,
    center_overlap_mm: float = 0.0,
) -> dict[str, Any]:
    """
    Check that eight nominal (or cut) octants tile the origin-centred RVE exactly.

    Outer faces must sit on ±L/2; adjacent octants share x/y/z=0 when pad=0.
    """
    h = 0.5 * float(cell_size_mm)
    rve = unitcell_box_bounds_mm(cell_size_mm)
    corners = unitcell_octant_corners_mm(cell_size_mm)
    nominal = [
        unitcell_octant_nominal_bounds_mm(c, cell_size_mm) for c in corners
    ]
    cut = [
        _octant_bounds_from_corner_mm(
            c,
            cell_size_mm,
            center_overlap_mm=center_overlap_mm,
        )
        for c in corners
    ]
    outer_ok = True
    outer_errors: list[str] = []
    for idx, bounds in enumerate(nominal, start=1):
        xmin, xmax, ymin, ymax, zmin, zmax = bounds
        corner = corners[idx - 1]
        sx, sy, sz = unitcell_octant_corner_signs(corner, cell_size_mm)
        checks = (
            ("xmin", sx < 0, xmin, -h),
            ("xmax", sx > 0, xmax, h),
            ("ymin", sy < 0, ymin, -h),
            ("ymax", sy > 0, ymax, h),
            ("zmin", sz < 0, zmin, -h),
            ("zmax", sz > 0, zmax, h),
        )
        for label, active, value, expected in checks:
            if active and abs(float(value) - float(expected)) > 1e-9:
                outer_ok = False
                outer_errors.append(
                    f"strut {idx} {label}={value:g} expected {expected:g}"
                )

    def _cover_axis(values_lo, values_hi, axis_name: str) -> tuple[bool, str | None]:
        lo = min(values_lo)
        hi = max(values_hi)
        if abs(lo - (-h)) > 1e-9 or abs(hi - h) > 1e-9:
            return False, f"{axis_name} cover [{lo:g}, {hi:g}] != [{-h:g}, {h:g}]"
        return True, None

    cover_errors: list[str] = []
    for axis_idx, axis_name in enumerate(("x", "y", "z")):
        lo_i = axis_idx * 2
        hi_i = lo_i + 1
        ok, err = _cover_axis(
            [b[lo_i] for b in nominal],
            [b[hi_i] for b in nominal],
            axis_name,
        )
        if not ok and err:
            cover_errors.append(err)

    center_planes_aligned = abs(float(center_overlap_mm)) <= 1e-12
    center_errors: list[str] = []
    if not center_planes_aligned:
        for idx, (nom, cut_b) in enumerate(zip(nominal, cut), start=1):
            for axis_idx, axis_name in enumerate(("x", "y", "z")):
                n_lo, n_hi = nom[2 * axis_idx], nom[2 * axis_idx + 1]
                c_lo, c_hi = cut_b[2 * axis_idx], cut_b[2 * axis_idx + 1]
                if abs(n_lo) < 1e-12 and c_lo != n_lo:
                    center_errors.append(
                        f"strut {idx} {axis_name}=0 face shifted to {c_lo:g} (pad)"
                    )
                if abs(n_hi) < 1e-12 and c_hi != n_hi:
                    center_errors.append(
                        f"strut {idx} {axis_name}=0 face shifted to {c_hi:g} (pad)"
                    )

    return {
        "cell_size_mm": float(cell_size_mm),
        "half_cell_mm": h,
        "rve_bounds_mm": list(rve),
        "center_overlap_mm": float(center_overlap_mm),
        "outer_faces_on_rve": outer_ok,
        "outer_face_errors": outer_errors,
        "union_covers_rve": not cover_errors,
        "union_cover_errors": cover_errors,
        "nominal_bisectors_at_zero": outer_ok and not cover_errors,
        "cut_bounds_extend_centre_faces_by_pad": float(center_overlap_mm) > 0.0,
        "cut_bounds_pad_notes": center_errors,
        "nominal_bounds_mm": [
            {"strut_index": i, "bounds": list(b)}
            for i, b in enumerate(nominal, start=1)
        ],
    }


def _octant_bounds_from_corner_mm(
    corner: tuple[float, float, float],
    cell_size_mm: float,
    *,
    center_overlap_mm: float = 0.0,
) -> tuple[float, float, float, float, float, float]:
    """
    Axis-aligned 1/8 virtual box for the corner octant.

    Nominal split planes are x/y/z=0 and outer faces ±L/2. When
    ``center_overlap_mm > 0``, each centre-facing face extends by **half** that
    value across the bisector (symmetric overlap for OCC fuse). Outer RVE
    faces stay at ±L/2.
    """
    xa, xb, ya, yb, za, zb = unitcell_octant_nominal_bounds_mm(corner, cell_size_mm)
    pad = max(0.0, float(center_overlap_mm))
    if pad <= 0.0:
        return (xa, xb, ya, yb, za, zb)

    half = 0.5 * pad
    sx, sy, sz = unitcell_octant_corner_signs(corner, cell_size_mm)
    if sx < 0:
        xb = half
    else:
        xa = -half
    if sy < 0:
        yb = half
    else:
        ya = -half
    if sz < 0:
        zb = half
    else:
        za = -half
    return (xa, xb, ya, yb, za, zb)


def unitcell_octant_assembly_bounds_mm(
    cell_size_mm: float,
) -> tuple[float, float, float, float, float, float]:
    """
    Virtual 1/8 box after origin assembly: junction corner at (0,0,0), extents +L/2.

    Each cut strut is mirrored so its centre-facing cube corner sits on the world
    origin and the block occupies [0, L/2]³ — eight parts meet at one point for CAD
    assembly.
    """
    h = 0.5 * float(cell_size_mm)
    return (0.0, h, 0.0, h, 0.0, h)


def unitcell_octant_assembly_scale(
    corner: tuple[float, float, float],
    cell_size_mm: float,
) -> tuple[float, float, float]:
    """Per-axis ±1 scale about the cell centre for origin assembly reposition."""
    sx, sy, sz = unitcell_octant_corner_signs(corner, cell_size_mm)
    return (float(sx), float(sy), float(sz))


def _occ_reposition_octant_cut_for_origin_assembly(
    cut_vol: tuple[int, int],
    corner: tuple[float, float, float],
    cell_size_mm: float,
    *,
    progress_label: str = "origin-assembly",
) -> tuple[int, int]:
    """
    Mirror a cut strut so the virtual cube corner at the cell centre is (0,0,0).

    World cut coords keep bisectors at x/y/z=0; negative octants live in [-L/2,0].
    Dilate about the origin by (sx, sy, sz) from the path corner signs maps every
    block to [0, L/2]³ for eight-part assembly at one origin.
    """
    import gmsh

    sx, sy, sz = unitcell_octant_assembly_scale(corner, cell_size_mm)
    if sx == 1.0 and sy == 1.0 and sz == 1.0:
        return cut_vol
    gmsh.model.occ.dilate([cut_vol], 0.0, 0.0, 0.0, sx, sy, sz)
    gmsh.model.occ.synchronize()
    h = 0.5 * float(cell_size_mm)
    print(
        f"  {progress_label}: origin assembly scale=({sx:g},{sy:g},{sz:g}) "
        f"-> virtual box [0,{h:g}]^3",
        flush=True,
    )
    return cut_vol


def _occ_add_unitcell_box(cell_size_mm: float) -> tuple[int, int]:
    import gmsh

    h = 0.5 * float(cell_size_mm)
    side = float(cell_size_mm)
    tag = gmsh.model.occ.addBox(-h, -h, -h, side, side, side)
    return (3, int(tag))


def _occ_add_box_from_bounds(
    bounds: tuple[float, float, float, float, float, float],
) -> tuple[int, int]:
    import gmsh

    xmin, xmax, ymin, ymax, zmin, zmax = bounds
    tag = gmsh.model.occ.addBox(
        xmin,
        ymin,
        zmin,
        xmax - xmin,
        ymax - ymin,
        zmax - zmin,
    )
    return (3, int(tag))


def _canonical_corner_from_pipe_path(
    path_pts: tuple[tuple[float, ...], ...],
    cell_size_mm: float,
) -> tuple[float, float, float]:
    """
    RVE corner at ±L/2 along a centre→corner path.

    When the path was extended past the corner, ``path_pts[-1]`` lies outside the
    cell; scan backward for the last point on the nominal corner.
    """
    h = 0.5 * float(cell_size_mm)
    tol = max(1e-3, 1e-6 * abs(h))
    for p in reversed(path_pts):
        corner = (float(p[0]), float(p[1]), float(p[2]))
        if all(abs(abs(corner[i]) - h) <= tol for i in range(3)):
            return corner
    return tuple(float(v) for v in path_pts[-1])


def _occ_octant_cut_single_pipe_tag(
    pipe_tag: tuple[int, int],
    part: tuple[str, tuple, float],
    cell_size_mm: float,
    *,
    center_overlap_mm: float = 0.0,
    progress_label: str = "octant-cut",
) -> tuple[int, int]:
    """Intersect one pipe with the 1/8 cell block for its corner octant."""
    import gmsh

    corner = _canonical_corner_from_pipe_path(part[1], cell_size_mm)
    oct_bounds = _octant_bounds_from_corner_mm(
        corner,
        cell_size_mm,
        center_overlap_mm=center_overlap_mm,
    )
    oct_box = _occ_add_box_from_bounds(oct_bounds)
    gmsh.model.occ.synchronize()
    pipe_copy = list(gmsh.model.occ.copy([pipe_tag]))
    box_copy = list(gmsh.model.occ.copy([oct_box]))
    gmsh.model.occ.synchronize()
    out, _ = gmsh.model.occ.intersect(pipe_copy, box_copy)
    gmsh.model.occ.synchronize()
    gmsh.model.occ.remove([oct_box], recursive=True)
    gmsh.model.occ.synchronize()
    vols = [(3, int(t)) for dim, t in out if dim == 3]
    if not vols:
        raise RuntimeError(
            f"{progress_label}: octant intersect produced no volume (corner={corner})"
        )
    if len(vols) > 1:
        vols = _occ_fuse_dimtags(
            vols,
            progress_label=f"{progress_label} single",
        )
    cut_mass = float(gmsh.model.occ.getMass(3, int(vols[0][1])))
    print(
        f"  {progress_label}: octant cut "
        f"(mass={cut_mass:.1f} mm3, corner={corner}, "
        f"virtual box x=[{oct_bounds[0]:g},{oct_bounds[1]:g}] "
        f"y=[{oct_bounds[2]:g},{oct_bounds[3]:g}] "
        f"z=[{oct_bounds[4]:g},{oct_bounds[5]:g}])",
        flush=True,
    )
    return vols[0]


def _occ_octant_cut_pipe_tags(
    pipe_tags: list[tuple[int, int]],
    pipe_parts: list[tuple[str, tuple, float]],
    cell_size_mm: float,
    *,
    center_overlap_mm: float = 0.0,
    progress_label: str = "octant-cut",
) -> list[tuple[int, int]]:
    """Intersect each pipe with the 1/8 cell block for its corner octant."""
    import gmsh

    canonical_corners = unitcell_octant_corners_mm(cell_size_mm)
    if len(pipe_tags) != len(pipe_parts):
        raise ValueError(
            f"{progress_label}: pipe_tags ({len(pipe_tags)}) != pipe_parts ({len(pipe_parts)})"
        )
    if len(pipe_tags) != len(canonical_corners):
        raise ValueError(
            f"{progress_label}: expected 8 struts, got {len(pipe_tags)}"
        )

    corner_tol = max(1e-3, 1e-6 * float(cell_size_mm))
    cut_vols: list[tuple[int, int]] = []
    for idx, (pipe_tag, part) in enumerate(zip(pipe_tags, pipe_parts), start=1):
        corner = canonical_corners[idx - 1]
        path_pts = part[1]
        path_corner = _canonical_corner_from_pipe_path(path_pts, cell_size_mm)
        if any(abs(path_corner[i] - corner[i]) > corner_tol for i in range(3)):
            raise RuntimeError(
                f"{progress_label}: strut {idx}/{len(pipe_tags)} endpoint "
                f"{path_corner} != canonical octant corner {corner}"
            )
        oct_bounds = _octant_bounds_from_corner_mm(
            corner,
            cell_size_mm,
            center_overlap_mm=center_overlap_mm,
        )
        oct_box = _occ_add_box_from_bounds(oct_bounds)
        gmsh.model.occ.synchronize()
        pipe_copy = list(gmsh.model.occ.copy([pipe_tag]))
        box_copy = list(gmsh.model.occ.copy([oct_box]))
        gmsh.model.occ.synchronize()
        out, _ = gmsh.model.occ.intersect(pipe_copy, box_copy)
        gmsh.model.occ.synchronize()
        gmsh.model.occ.remove([oct_box], recursive=True)
        gmsh.model.occ.synchronize()
        vols = [(3, int(t)) for dim, t in out if dim == 3]
        if not vols:
            raise RuntimeError(
                f"{progress_label}: strut {idx}/{len(pipe_tags)} "
                "octant intersect produced no volume"
            )
        if len(vols) > 1:
            vols = _occ_fuse_dimtags(
                vols,
                progress_label=f"{progress_label} strut {idx}",
            )
        cut_vols.append(vols[0])
        cut_mass = float(gmsh.model.occ.getMass(3, int(vols[0][1])))
        print(
            f"  {progress_label}: strut {idx}/{len(pipe_tags)} octant cut "
            f"(mass={cut_mass:.1f} mm3, corner={corner}, "
            f"virtual box x=[{oct_bounds[0]:g},{oct_bounds[1]:g}] "
            f"y=[{oct_bounds[2]:g},{oct_bounds[3]:g}] "
            f"z=[{oct_bounds[4]:g},{oct_bounds[5]:g}])",
            flush=True,
        )
    return cut_vols


def _occ_build_single_both_ext_octant_cut_step(
    part: tuple[str, tuple, float],
    cell_size_mm: float,
    out_path: str,
    *,
    period_factor: float = 1.0,
    strut_index: int = 1,
    strut_count: int = 8,
    n_segments: int = 24,
    rod_diameter: float = 2.0,
    amplitude: float = 2.0,
    centre_extension_mm: float | None = None,
    corner_extension_mm: float | None = None,
    progress_label: str = "both-ext-cut",
    center_overlap_mm: float = OCTANT_CENTER_OVERLAP_MM,
) -> float:
    """Cut+align one both-end extended strut via an isolated subprocess (stable on Windows)."""
    import subprocess
    import sys

    del part, center_overlap_mm, progress_label  # geometry rebuilt in subprocess

    repo_root = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )
    script = os.path.join(repo_root, "scripts", "export_single_strut_paper_box_cut.py")
    cmd = [
        sys.executable,
        script,
        "--Q",
        str(float(period_factor)),
        "--L",
        str(float(cell_size_mm)),
        "--Af",
        str(float(amplitude)),
        "--rod-d",
        str(float(rod_diameter)),
        "--n-segments",
        str(int(n_segments)),
        "--strut",
        str(int(strut_index)),
        "--both-end-extension",
        "--aligned-cut-out",
        os.path.abspath(out_path),
    ]
    if centre_extension_mm is not None:
        cmd.extend(["--centre-extension-mm", str(float(centre_extension_mm))])
    if corner_extension_mm is not None:
        cmd.extend(["--corner-extension-mm", str(float(corner_extension_mm))])
    subprocess.run(cmd, check=True, cwd=repo_root)
    if not os.path.isfile(out_path):
        raise RuntimeError(
            f"subprocess aligned-cut strut {strut_index}/{strut_count} "
            f"did not write {out_path}"
        )
    return 0.0


def _occ_import_octant_cut_steps(step_paths: list[str]) -> list[tuple[int, int]]:
    """Import per-strut cut STEPs into the current gmsh model."""
    import gmsh

    cut_vols: list[tuple[int, int]] = []
    for idx, step_path in enumerate(step_paths, start=1):
        before = set(_occ_list_volume_dimtags())
        gmsh.model.occ.importShapes(os.path.abspath(step_path))
        gmsh.model.occ.synchronize()
        after = _occ_list_volume_dimtags()
        new_vols = [vol for vol in after if vol not in before]
        if len(new_vols) != 1:
            raise RuntimeError(
                f"import cut strut {idx}/{len(step_paths)}: expected 1 volume, "
                f"got {len(new_vols)} from {step_path}"
            )
        cut_vols.append(new_vols[0])
    return cut_vols


def _occ_align_single_cut_to_virtual_box(
    cut_vol: tuple[int, int],
    corner: tuple[float, float, float],
    cell_size_mm: float,
    *,
    center_overlap_mm: float = 0.0,
    progress_label: str = "octant-align",
) -> tuple[int, int]:
    """Re-intersect one cut strut with its virtual 1/8 box (bisectors at x/y/z=0)."""
    import gmsh

    bounds = _octant_bounds_from_corner_mm(
        corner,
        cell_size_mm,
        center_overlap_mm=center_overlap_mm,
    )
    box = _occ_add_box_from_bounds(bounds)
    gmsh.model.occ.synchronize()
    out, _ = gmsh.model.occ.intersect([cut_vol], [box])
    gmsh.model.occ.synchronize()
    gmsh.model.occ.remove([box], recursive=True)
    gmsh.model.occ.synchronize()
    vols = [(3, int(t)) for dim, t in out if dim == 3]
    if not vols:
        raise RuntimeError(
            f"{progress_label}: virtual-box align produced no volume (corner={corner})"
        )
    keep = vols[0]
    if keep != cut_vol:
        _occ_remove_volumes_in_set({cut_vol}, keep)
    return keep


def _occ_build_aligned_octant_cut_volumes(
    pipe_parts: list[tuple[str, tuple, float]],
    cell_size_mm: float,
    *,
    progress_label: str = "octant-cut",
    pipe_centre_stub: bool = False,
) -> tuple[list[tuple[int, int]], float]:
    """
    Per-strut pipe sweep, 1/8 box cut, and virtual-box align.

    ``pipe_centre_stub=True`` uses a chord cylinder + open-start pipe at the cell
    centre (clean planar faces on x/y/z=0 without centre path extension, which
    breaks OCC sequential fuse). Compound export keeps centre path extension instead.

    Matches the proven single-session build: accumulate eight cuts, then remove
    pipe/debris once (no per-strut prune — that breaks later fragment fuse).
    """
    import gmsh

    cut_vols: list[tuple[int, int]] = []
    pipe_ref_mass = 0.0
    n = len(pipe_parts)
    for idx, part in enumerate(pipe_parts, start=1):
        tag = _occ_dimtags_from_parts([part], pipe_centre_stub=pipe_centre_stub)[0]
        gmsh.model.occ.synchronize()
        pipe_ref_mass += float(gmsh.model.occ.getMass(3, int(tag[1])))
        corner = _canonical_corner_from_pipe_path(part[1], cell_size_mm)
        cut = _occ_octant_cut_single_pipe_tag(
            tag,
            part,
            cell_size_mm,
            center_overlap_mm=OCTANT_CENTER_OVERLAP_MM,
            progress_label=f"{progress_label} strut {idx}/{n}",
        )
        cut = _occ_align_single_cut_to_virtual_box(
            cut,
            corner,
            cell_size_mm,
            center_overlap_mm=OCTANT_CENTER_OVERLAP_MM,
            progress_label=f"{progress_label}-align strut {idx}/{n}",
        )
        cut_vols.append(cut)

    junk = [v for v in _occ_list_volume_dimtags() if v not in set(cut_vols)]
    if junk:
        _occ_remove_volumes_in_set(set(junk), cut_vols[0])
        gmsh.model.occ.synchronize()
    return cut_vols, pipe_ref_mass


def _occ_select_main_octant_fragments(
    frags: list[tuple[int, int]],
    *,
    n_struts: int,
    cut_mass: float,
) -> list[tuple[int, int]]:
    """Drop fragment slivers; keep the ``n_struts`` largest pieces."""
    import gmsh

    if len(frags) <= n_struts:
        return frags
    mean_piece = float(cut_mass) / max(1, n_struts)
    min_mass = 0.25 * mean_piece
    heavy = [
        vol
        for vol in frags
        if float(gmsh.model.occ.getMass(3, int(vol[1]))) >= min_mass
    ]
    if len(heavy) < n_struts:
        heavy = frags
    heavy.sort(
        key=lambda vol: float(gmsh.model.occ.getMass(3, int(vol[1]))),
        reverse=True,
    )
    return heavy[:n_struts]


def _occ_align_octant_cuts_to_virtual_boxes(
    cut_vols: list[tuple[int, int]],
    cell_size_mm: float,
    *,
    center_overlap_mm: float = 0.0,
    progress_label: str = "octant-align",
) -> list[tuple[int, int]]:
    """
    Snap each cut strut to its virtual 1/8 box before pairwise fuse.

    Re-intersects every volume with the same axis-aligned octant bounds used
    for the initial cut so all eight blocks share x/y/z=0 bisectors exactly.
    """
    import gmsh

    corners = unitcell_octant_corners_mm(cell_size_mm)
    if len(cut_vols) != len(corners):
        raise ValueError(
            f"{progress_label}: expected {len(corners)} cut volumes, got {len(cut_vols)}"
        )

    aligned: list[tuple[int, int]] = []
    print(
        f"  {progress_label}: align {len(cut_vols)} strut(s) to virtual 1/8 cube(s)...",
        flush=True,
    )
    for idx, (vol, corner) in enumerate(zip(cut_vols, corners), start=1):
        bounds = _octant_bounds_from_corner_mm(
            corner,
            cell_size_mm,
            center_overlap_mm=center_overlap_mm,
        )
        box = _occ_add_box_from_bounds(bounds)
        gmsh.model.occ.synchronize()
        out, _ = gmsh.model.occ.intersect([vol], [box])
        gmsh.model.occ.synchronize()
        gmsh.model.occ.remove([box], recursive=True)
        gmsh.model.occ.synchronize()
        vols = [(3, int(t)) for dim, t in out if dim == 3]
        if not vols:
            raise RuntimeError(
                f"{progress_label}: strut {idx}/{len(cut_vols)} "
                "virtual-box align produced no volume"
            )
        keep = vols[0]
        if keep != vol:
            _occ_remove_volumes_in_set({vol}, keep)
        aligned.append(keep)
    return aligned


def _occ_fuse_lattice_for_box_cut(
    pipe_parts: list[tuple[str, tuple, float]],
    *,
    progress_label: str = "pipe-fuse",
) -> tuple[list[tuple[int, int]], str]:
    """Fuse struts for paper box-cut export (pipe-only; no junction spheres)."""
    vols = _occ_fuse_unitcell_pipe_first(
        pipe_parts,
        progress_label=progress_label,
        per_strut_corner_caps=False,
    )
    print(f"  {progress_label}: strategy=pipe-first (no junction spheres)", flush=True)
    return vols, "pipe-first (no junction spheres)"


def _occ_box_cut_pipe_tags(
    pipe_tags: list[tuple[int, int]],
    box_vol: tuple[int, int],
    *,
    progress_label: str = "per-strut-box-cut",
) -> list[tuple[int, int]]:
    """Intersect each pipe volume with a copy of the RVE box (inputs stay on the model)."""
    import gmsh

    cut_vols: list[tuple[int, int]] = []
    for idx, pipe_tag in enumerate(pipe_tags, start=1):
        pipe_copy = list(gmsh.model.occ.copy([pipe_tag]))
        box_copy = list(gmsh.model.occ.copy([box_vol]))
        gmsh.model.occ.synchronize()
        out, _ = gmsh.model.occ.intersect(pipe_copy, box_copy)
        gmsh.model.occ.synchronize()
        vols = [(3, int(t)) for dim, t in out if dim == 3]
        if not vols:
            raise RuntimeError(
                f"{progress_label}: strut {idx}/{len(pipe_tags)} "
                "box intersect produced no volume"
            )
        if len(vols) > 1:
            vols = _occ_fuse_dimtags(
                vols,
                progress_label=f"{progress_label} strut {idx}",
            )
        cut_vols.append(vols[0])
        cut_mass = float(gmsh.model.occ.getMass(3, int(vols[0][1])))
        print(
            f"  {progress_label}: strut {idx}/{len(pipe_tags)} cut "
            f"(mass={cut_mass:.1f} mm3)",
            flush=True,
        )
    return cut_vols


def _occ_weld_pipe_tags_at_centre(
    pipe_tags: list[tuple[int, int]],
    pipe_parts: list[tuple[str, tuple, float]],
    *,
    centre_radius_scale: float = Q1_CENTRE_WELD_RADIUS_SCALE,
    progress_label: str = "centre-weld",
) -> list[tuple[int, int]]:
    """Fuse each pipe with a sphere at the path origin (centre node) to aid OCC union."""
    import gmsh

    welded: list[tuple[int, int]] = []
    for idx, (pipe_tag, part) in enumerate(zip(pipe_tags, pipe_parts), start=1):
        path_pts = part[1]
        radius = _pipe_sweep_nominal_radius(part)
        x0, y0, z0 = map(float, path_pts[0])
        centre_r = radius * float(centre_radius_scale)
        centre = _occ_volume_dimtag(gmsh.model.occ.addSphere(x0, y0, z0, centre_r))
        gmsh.model.occ.synchronize()
        fused, _ = gmsh.model.occ.fuse([pipe_tag], [centre])
        gmsh.model.occ.synchronize()
        vols = [(3, int(t)) for dim, t in fused if dim == 3]
        if not vols:
            raise RuntimeError(
                f"{progress_label}: strut {idx}/{len(pipe_tags)} centre weld lost volume"
            )
        welded.append(_occ_primary_volume(vols))
    return welded


def _occ_trim_centre_junction_ball(
    vol: tuple[int, int],
    rod_radius: float,
    *,
    baseline_cut_mass: float,
    trim_radius_scale: float = Q1_CENTRE_TRIM_RADIUS_SCALE,
    progress_label: str = "centre-trim",
) -> tuple[int, int]:
    """Carve the oversized weld junction after merge (Q=1 centre-weld path)."""
    import gmsh

    trim_r = float(rod_radius) * float(trim_radius_scale)
    print(
        f"  {progress_label}: subtract centre sphere r={trim_r:.2f} mm...",
        flush=True,
    )
    cutter = _occ_volume_dimtag(gmsh.model.occ.addSphere(0.0, 0.0, 0.0, trim_r))
    gmsh.model.occ.synchronize()
    gmsh.model.occ.cut([vol], [cutter])
    gmsh.model.occ.synchronize()
    vols = _occ_list_volume_dimtags()
    if len(vols) != 1:
        raise RuntimeError(
            f"{progress_label}: centre trim left {len(vols)} volume(s), expected 1"
        )
    keep = vols[0]
    mass = float(gmsh.model.occ.getMass(3, int(keep[1])))
    min_mass = MIN_CUT_MERGE_MASS_RATIO * float(baseline_cut_mass)
    if baseline_cut_mass > 0.0 and mass < min_mass:
        raise RuntimeError(
            f"{progress_label}: post-trim mass {mass:.1f} mm3 < {min_mass:.1f} mm3"
        )
    _occ_remove_all_volumes_except(keep)
    return keep


def _occ_build_per_strut_box_cuts(
    pipe_parts: list[tuple[str, tuple, float]],
    cell_size_mm: float,
    *,
    progress_label: str = "per-strut-box-cut",
) -> tuple[list[tuple[int, int]], float, float]:
    """Create box-cut strut volumes on the current gmsh model."""
    import gmsh

    gmsh.model.occ.remove(gmsh.model.getEntities(), recursive=True)
    gmsh.model.occ.synchronize()
    _configure_occ_for_fuse()

    pipe_tags = _occ_dimtags_from_parts(pipe_parts)
    gmsh.model.occ.synchronize()
    pipe_ref_mass = _occ_volumes_mass(pipe_tags)
    box_vol = _occ_add_unitcell_box(cell_size_mm)
    gmsh.model.occ.synchronize()

    cut_vols = _occ_box_cut_pipe_tags(
        pipe_tags,
        box_vol,
        progress_label=progress_label,
    )
    cut_mass = _occ_volumes_mass(cut_vols)
    gmsh.model.occ.remove(pipe_tags + [box_vol], recursive=True)
    gmsh.model.occ.synchronize()
    return cut_vols, pipe_ref_mass, cut_mass


def _occ_batch_merge_box_cut_struts(
    cut_vols: list[tuple[int, int]],
    *,
    cut_mass: float,
    progress_label: str = "box-cut-merge",
) -> tuple[int, int]:
    """Single-call OCC union of per-strut box-cut bodies (stable for Q=1 centre weld)."""
    import gmsh

    if len(cut_vols) == 1:
        _occ_remove_all_volumes_except(cut_vols[0])
        return cut_vols[0]

    min_mass = MIN_CUT_MERGE_MASS_RATIO * float(cut_mass) if cut_mass > 0.0 else 0.0
    print(
        f"  {progress_label}: batch fuse {len(cut_vols)} box-cut strut(s)...",
        flush=True,
    )
    fused, _ = gmsh.model.occ.fuse([cut_vols[0]], cut_vols[1:])
    gmsh.model.occ.synchronize()
    vols = [(3, int(t)) for dim, t in fused if dim == 3]
    if not vols:
        raise RuntimeError(f"{progress_label}: batch fuse produced no volume")
    keep = _occ_primary_volume(vols) if len(vols) > 1 else vols[0]
    mass = float(gmsh.model.occ.getMass(3, int(keep[1])))
    if min_mass > 0.0 and mass < min_mass:
        raise RuntimeError(
            f"{progress_label}: batch merged mass {mass:.1f} mm3 < "
            f"{min_mass:.1f} mm3 (cut reference)"
        )
    _occ_remove_all_volumes_except(keep)
    return keep


def _occ_merge_box_cut_struts(
    cut_vols: list[tuple[int, int]],
    *,
    cut_mass: float,
    progress_label: str = "per-strut-box-cut",
) -> tuple[int, int]:
    """Merge per-strut box-cut bodies into one unit-cell solid (required for array fuse)."""
    if len(cut_vols) == 1:
        _occ_remove_all_volumes_except(cut_vols[0])
        return cut_vols[0]

    import gmsh

    errors: list[str] = []
    min_mass = MIN_CUT_MERGE_MASS_RATIO * float(cut_mass) if cut_mass > 0.0 else 0.0

    def _keep_one(vol: tuple[int, int]) -> tuple[int, int]:
        mass = float(gmsh.model.occ.getMass(3, int(vol[1])))
        if min_mass > 0.0 and mass < min_mass:
            raise RuntimeError(
                f"{progress_label}: merged mass {mass:.1f} mm3 < "
                f"{min_mass:.1f} mm3 (cut reference)"
            )
        _occ_remove_all_volumes_except(vol)
        return vol

    def _try_unify(vols: list[tuple[int, int]], label: str) -> tuple[int, int] | None:
        live = [v for v in vols if v in set(_occ_list_volume_dimtags())]
        if len(live) <= 1:
            return _keep_one(live[0]) if live else None
        try:
            _occ_unify_volumes_to_one(progress_label=label)
            prune_occ_for_step_export()
            outs = _occ_list_volume_dimtags()
            if len(outs) == 1:
                return _keep_one(outs[0])
            if outs:
                return _keep_one(_occ_primary_volume(outs))
        except Exception as exc:
            errors.append(f"{label}: {exc}")
        return None

    print(
        f"  {progress_label}: merge {len(cut_vols)} box-cut strut(s) -> 1 solid...",
        flush=True,
    )

    try:
        fused = _fuse_occ_layer_volumes_safe(
            list(cut_vols),
            progress_label=f"{progress_label}-pairwise",
        )
        prune_occ_for_step_export()
        outs = fused if isinstance(fused, list) else [fused]
        outs = [v for v in outs if v in set(_occ_list_volume_dimtags())]
        if len(outs) == 1:
            return _keep_one(outs[0])
        if len(outs) > 1:
            merged = _try_unify(outs, f"{progress_label}-unify")
            if merged is not None:
                return merged
    except Exception as exc:
        errors.append(f"pairwise: {exc}")

    merged = _try_unify(cut_vols, f"{progress_label}-fragment")
    if merged is not None:
        return merged

    try:
        merged = _occ_fuse_sequential(
            [v for v in cut_vols if v in set(_occ_list_volume_dimtags())],
            progress_label=f"{progress_label}-sequential",
            restrict_cleanup=True,
        )
        if len(merged) == 1:
            return _keep_one(merged[0])
        errors.append(f"sequential: produced {len(merged)} volume(s)")
    except Exception as exc:
        errors.append(f"sequential: {exc}")

    try:
        live = [v for v in cut_vols if v in set(_occ_list_volume_dimtags())]
        fused = _occ_fuse_dimtags(
            live,
            progress_label=f"{progress_label}-batch",
        )
        if len(fused) == 1:
            return _keep_one(fused[0])
        errors.append(f"batch: produced {len(fused)} volume(s)")
    except Exception as exc:
        errors.append(f"batch: {exc}")

    raise RuntimeError(
        f"{progress_label}: could not merge {len(cut_vols)} struts to 1 volume "
        f"({'; '.join(errors)})"
    )


def _occ_polish_merged_volume_for_step(*, heal: bool = True) -> None:
    """Remove duplicate OCC faces/edges; optional heal before STEP write."""
    import gmsh

    from src.mesh.occ_pipe import heal_occ_for_step_export

    try:
        gmsh.model.occ.removeAllDuplicates()
        gmsh.model.occ.synchronize()
    except Exception as exc:
        print(f"  [WARN] removeAllDuplicates skipped ({exc})", flush=True)
    if heal:
        try:
            heal_occ_for_step_export()
        except Exception as exc:
            print(f"  [WARN] post-merge heal skipped ({exc})", flush=True)
    try:
        prune_occ_for_step_export()
    except Exception as exc:
        print(f"  [WARN] post-merge prune skipped ({exc})", flush=True)


def _occ_fuse_pair_volumes(
    vol_a: tuple[int, int],
    vol_b: tuple[int, int],
    *,
    progress_label: str = "octant-fuse",
    z_overlap_mm: float = 0.0,
) -> tuple[int, int]:
    """Fuse two OCC volumes; optional −z shift on B for face-only z=0 contact."""
    import gmsh

    vol_b_use = vol_b
    operands: set[tuple[int, int]] = {vol_a, vol_b}
    if z_overlap_mm > 0.0:
        shifted = list(gmsh.model.occ.copy([vol_b]))
        gmsh.model.occ.translate(shifted, 0.0, 0.0, -float(z_overlap_mm))
        gmsh.model.occ.synchronize()
        vol_b_use = shifted[0]
        operands.add(vol_b_use)
    fused, _ = gmsh.model.occ.fuse([vol_a], [vol_b_use])
    gmsh.model.occ.synchronize()
    vols = [(3, int(t)) for dim, t in fused if dim == 3]
    if not vols:
        raise RuntimeError(f"{progress_label}: pair fuse produced no volume")
    keep = _occ_primary_volume(vols) if len(vols) > 1 else vols[0]
    _occ_remove_volumes_in_set(operands, keep)
    return keep


def _occ_prune_extra_volumes(keep_vols: list[tuple[int, int]]) -> None:
    """Remove boolean debris; retain only the listed cut volumes."""
    keep_set = set(keep_vols)
    junk = [v for v in _occ_list_volume_dimtags() if v not in keep_set]
    if junk:
        _occ_remove_volumes_in_set(set(junk), keep_vols[0])


def _occ_order_octant_cut_volumes(
    cut_vols: list[tuple[int, int]],
    order: tuple[int, ...] = OCTANT_SEQUENTIAL_FUSE_ORDER,
) -> list[tuple[int, int]]:
    """Reorder eight cut volumes for stable sequential OCC fuse."""
    if len(cut_vols) != len(order):
        return list(cut_vols)
    return [cut_vols[i] for i in order]


def _occ_fuse_octant_cuts_sequential(
    cut_vols: list[tuple[int, int]],
    *,
    cut_mass: float,
    progress_label: str = "octant-sequential-fuse",
) -> tuple[int, int]:
    """
    Merge octant-cut struts one-at-a-time into the first (stable order).

    Validates mass after each step so face-only ``fuse`` (silent strut drop) fails fast.
    """
    import gmsh

    live = [v for v in cut_vols if v in set(_occ_list_volume_dimtags())]
    if len(live) == 1:
        _occ_remove_all_volumes_except(live[0])
        return live[0]
    if not live:
        raise RuntimeError(f"{progress_label}: no cut volumes to fuse")

    ordered = _occ_order_octant_cut_volumes(live)
    min_mass = MIN_CUT_MERGE_MASS_RATIO * float(cut_mass) if cut_mass > 0.0 else 0.0
    mean_piece = float(cut_mass) / max(1, len(ordered))
    min_step_delta = 0.25 * mean_piece

    print(
        f"  {progress_label}: sequential fuse {len(ordered)} octant cut(s) "
        f"(order={list(OCTANT_SEQUENTIAL_FUSE_ORDER)}, ref={cut_mass:.1f} mm3)...",
        flush=True,
    )

    acc = ordered[0]
    for idx, vol in enumerate(ordered[1:], start=2):
        prev_mass = float(gmsh.model.occ.getMass(3, int(acc[1])))
        vol_mass = float(gmsh.model.occ.getMass(3, int(vol[1])))
        prev_acc = acc
        fused, _ = gmsh.model.occ.fuse([acc], [vol])
        gmsh.model.occ.synchronize()
        vols = [(3, int(t)) for dim, t in fused if dim == 3]
        if not vols:
            raise RuntimeError(
                f"{progress_label}: fuse lost volume at strut {idx}/{len(ordered)}"
            )
        acc = _occ_primary_volume(vols) if len(vols) > 1 else vols[0]
        new_mass = float(gmsh.model.occ.getMass(3, int(acc[1])))
        if new_mass < prev_mass + min_step_delta:
            raise RuntimeError(
                f"{progress_label}: strut {idx}/{len(ordered)} not merged "
                f"(mass {new_mass:.1f} mm3, expected >= "
                f"{prev_mass + min_step_delta:.1f} mm3; strut ~{vol_mass:.1f} mm3)"
            )
        _occ_remove_volumes_in_set({prev_acc, vol}, acc)
        print(
            f"  {progress_label}: fused strut {idx}/{len(ordered)} "
            f"(mass={new_mass:.1f} mm3)",
            flush=True,
        )

    merged_mass = float(gmsh.model.occ.getMass(3, int(acc[1])))
    if cut_mass > 0.0 and merged_mass < min_mass:
        raise RuntimeError(
            f"{progress_label}: merged mass {merged_mass:.1f} mm3 < "
            f"{min_mass:.1f} mm3 (cut sum)"
        )
    print(
        f"  {progress_label}: sequential fuse OK "
        f"(mass={merged_mass:.1f} mm3, ratio={merged_mass / cut_mass:.3f})",
        flush=True,
    )
    _occ_remove_all_volumes_except(acc)
    return acc


def _occ_merge_octant_cut_struts(
    cut_vols: list[tuple[int, int]],
    *,
    cut_mass: float,
    cell_size_mm: float,
    progress_label: str = "octant-box-cut",
    already_aligned: bool = False,
) -> tuple[int, int]:
    """
    Merge eight 1/8 octant struts (sequential pairwise fuse).

    When ``already_aligned=True``, skip the batch align pass (per-strut align already done).
    """
    if len(cut_vols) == 1:
        _occ_remove_all_volumes_except(cut_vols[0])
        return cut_vols[0]
    if len(cut_vols) != 8:
        return _occ_merge_box_cut_struts(
            cut_vols,
            cut_mass=cut_mass,
            progress_label=progress_label,
        )

    if not already_aligned:
        cut_vols = _occ_align_octant_cuts_to_virtual_boxes(
            cut_vols,
            cell_size_mm,
            center_overlap_mm=OCTANT_CENTER_OVERLAP_MM,
            progress_label=f"{progress_label}-align",
        )
    _occ_prune_extra_volumes(cut_vols)
    return _occ_fuse_octant_cuts_sequential(
        cut_vols,
        cut_mass=cut_mass,
        progress_label=f"{progress_label}-sequential",
    )


def _occ_paper_box_fuse_then_cut(
    pipe_parts: list[tuple[str, tuple, float]],
    cell_size_mm: float,
    *,
    centre_radius_scale: float = Q1_CENTRE_WELD_RADIUS_SCALE,
    progress_label: str = "fuse-then-cut",
) -> dict[str, Any]:
    """
    Q=1: fuse eight struts into one solid, then clip with the virtual RVE L³ box.

    Raw spline pipes fail OCC union at the cell centre; a temporary centre weld
    bridges each pipe before the batch fuse. The weld ball is carved out after the
    RVE cut so the exported solid has no junction spheres.
    """
    import gmsh

    _, pipe_ref_mass, baseline_cut_mass = _occ_build_per_strut_box_cuts(
        pipe_parts,
        cell_size_mm,
        progress_label=f"{progress_label}-ref",
    )
    gmsh.model.occ.remove(gmsh.model.getEntities(), recursive=True)
    gmsh.model.occ.synchronize()

    pipe_tags = _occ_dimtags_from_parts(pipe_parts)
    gmsh.model.occ.synchronize()
    welded = _occ_weld_pipe_tags_at_centre(
        pipe_tags,
        pipe_parts,
        centre_radius_scale=centre_radius_scale,
        progress_label=progress_label,
    )
    print(
        f"  {progress_label}: batch fuse {len(welded)} centre-welded strut(s) "
        f"(pipe ref={pipe_ref_mass:.1f} mm3)...",
        flush=True,
    )
    fused_vol = _occ_batch_merge_box_cut_struts(
        welded,
        cut_mass=pipe_ref_mass,
        progress_label=f"{progress_label}-fuse",
    )
    fused_mass = float(gmsh.model.occ.getMass(3, int(fused_vol[1])))
    cut_vol = _occ_intersect_volumes_with_box(
        [fused_vol],
        cell_size_mm,
        progress_label=f"{progress_label}-box-cut",
    )
    rod_radius = _pipe_sweep_nominal_radius(pipe_parts[0])
    merged_vol = _occ_trim_centre_junction_ball(
        cut_vol,
        rod_radius,
        baseline_cut_mass=baseline_cut_mass,
        progress_label=f"{progress_label}-centre-trim",
    )
    merged_mass = float(gmsh.model.occ.getMass(3, int(merged_vol[1])))
    min_mass = MIN_CUT_MERGE_MASS_RATIO * float(baseline_cut_mass)
    if baseline_cut_mass > 0.0 and merged_mass < min_mass:
        raise RuntimeError(
            f"{progress_label}: merged mass {merged_mass:.1f} mm3 < "
            f"{min_mass:.1f} mm3 ({MIN_CUT_MERGE_MASS_RATIO:.0%} of naked cut reference)"
        )
    _occ_remove_all_volumes_except(merged_vol)
    _occ_polish_merged_volume_for_step()
    return {
        "kind": "fused",
        "vol": merged_vol,
        "pipe_ref_mass": pipe_ref_mass,
        "fused_mass": fused_mass,
        "cut_mass": baseline_cut_mass,
        "baseline_cut_mass": baseline_cut_mass,
        "merge_strategy": (
            f"centre weld (r×{centre_radius_scale:g}) + batch fuse 8 struts "
            f"+ RVE L³ box-cut + centre trim (r×{Q1_CENTRE_TRIM_RADIUS_SCALE:g})"
        ),
    }


def _occ_paper_box_octant_cut(
    pipe_parts: list[tuple[str, tuple, float]],
    cell_size_mm: float,
    *,
    progress_label: str = "octant-box-cut",
) -> dict[str, Any]:
    """
    Q=1: clip each strut to its corner 1/8 block, then merge to 1 solid.

    Adjacent struts meet on x/y/z=0 planes with a thin centre overlap (no weld sphere).

    Pipes use a centre chord stub (not path extension) for clean cell-centre faces
    while keeping OCC sequential fuse stable (see ``OCTANT_SEQUENTIAL_FUSE_ORDER``).
    Centre path extension is reserved for the compound export (manual CAD fuse).
    """
    import gmsh

    partition = verify_unitcell_octant_partition_mm(
        cell_size_mm,
        center_overlap_mm=OCTANT_CENTER_OVERLAP_MM,
    )
    if not partition.get("nominal_bisectors_at_zero"):
        raise RuntimeError(
            f"{progress_label}: octant virtual cubes not aligned to RVE "
            f"({partition.get('outer_face_errors') or partition.get('union_cover_errors')})"
        )
    print(
        f"  {progress_label}: octant partition OK "
        f"(nominal virtual cubes on x/y/z=0 ±L/2; "
        f"symmetric fuse overlap={OCTANT_CENTER_OVERLAP_MM:g} mm total per bisector)",
        flush=True,
    )

    cut_vols, pipe_ref_mass = _occ_build_aligned_octant_cut_volumes(
        pipe_parts,
        cell_size_mm,
        progress_label=progress_label,
        pipe_centre_stub=True,
    )
    octant_cut_mass = _occ_volumes_mass(cut_vols)
    merged_vol = _occ_merge_octant_cut_struts(
        cut_vols,
        cut_mass=octant_cut_mass,
        cell_size_mm=cell_size_mm,
        progress_label=progress_label,
        already_aligned=True,
    )
    merged_mass = float(gmsh.model.occ.getMass(3, int(merged_vol[1])))
    min_mass = MIN_CUT_MERGE_MASS_RATIO * float(octant_cut_mass)
    if octant_cut_mass > 0.0 and merged_mass < min_mass:
        raise RuntimeError(
            f"{progress_label}: merged mass {merged_mass:.1f} mm3 < "
            f"{min_mass:.1f} mm3 ({MIN_CUT_MERGE_MASS_RATIO:.0%} of octant cut sum)"
        )
    _occ_remove_all_volumes_except(merged_vol)
    return {
        "kind": "fused",
        "vol": merged_vol,
        "pipe_ref_mass": pipe_ref_mass,
        "cut_mass": octant_cut_mass,
        "baseline_cut_mass": octant_cut_mass,
        "merge_strategy": (
            "centre chord stub + per-strut octant cut+align + sequential fuse "
            f"(order {list(OCTANT_SEQUENTIAL_FUSE_ORDER)})"
        ),
    }


def _occ_paper_box_octant_cut_both_ext(
    pipe_parts: list[tuple[str, tuple, float]],
    cell_size_mm: float,
    *,
    progress_label: str = "octant-box-cut-both-ext",
    centre_extension_mm: float | None = None,
    corner_extension_mm: float | None = None,
    center_overlap_mm: float | None = None,
    fuse_only: bool = True,
    period_factor: float = 1.0,
    n_segments: int = 24,
    rod_diameter: float = 2.0,
    amplitude: float = 2.0,
) -> dict[str, Any]:
    """
    Q=1: both-end path extension, per-strut octant cut+align, sequential fuse.

    Centre and corner stubs move pipe end caps past bisector / RVE faces so cut
    caps are planar; extension lengths default to ``octant_centre_path_extension_mm``.
    """
    import gmsh

    partition = verify_unitcell_octant_partition_mm(
        cell_size_mm,
        center_overlap_mm=OCTANT_CENTER_OVERLAP_MM,
    )
    if not partition.get("nominal_bisectors_at_zero"):
        raise RuntimeError(
            f"{progress_label}: octant virtual cubes not aligned to RVE "
            f"({partition.get('outer_face_errors') or partition.get('union_cover_errors')})"
        )
    print(
        f"  {progress_label}: octant partition OK "
        f"(symmetric fuse overlap={OCTANT_CENTER_OVERLAP_MM:g} mm per bisector)",
        flush=True,
    )

    extended, centre_ext_mm, corner_ext_mm = pipe_parts_with_both_end_path_extension(
        pipe_parts,
        centre_extension_mm=centre_extension_mm,
        corner_extension_mm=corner_extension_mm,
    )
    overlap_mm = (
        float(center_overlap_mm)
        if center_overlap_mm is not None
        else OCTANT_CENTER_OVERLAP_MM
    )
    print(
        f"  {progress_label}: both-end path extension "
        f"centre={centre_ext_mm:g} mm corner={corner_ext_mm:g} mm "
        f"fuse_overlap={overlap_mm:g} mm (isolated per-strut cut)",
        flush=True,
    )

    import tempfile

    from src.paths import hubai_temp_dir

    pipe_ref_mass = 0.0
    step_paths: list[str] = []
    tmp_dir = hubai_temp_dir(prefix="both_ext_octant_")
    try:
        n = len(extended)
        for idx, part in enumerate(extended, start=1):
            step_path = os.path.join(tmp_dir, f"strut_{idx:02d}.step")
            _occ_build_single_both_ext_octant_cut_step(
                part,
                cell_size_mm,
                step_path,
                period_factor=period_factor,
                strut_index=idx,
                strut_count=n,
                n_segments=n_segments,
                rod_diameter=rod_diameter,
                amplitude=amplitude,
                centre_extension_mm=centre_ext_mm,
                corner_extension_mm=corner_ext_mm,
                progress_label=progress_label,
                center_overlap_mm=overlap_mm,
            )
            step_paths.append(step_path)

        if gmsh.isInitialized():
            gmsh.finalize()
        gmsh.initialize()
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add(f"{progress_label}_import")
        _configure_occ_for_fuse()
        cut_vols = _occ_import_octant_cut_steps(step_paths)
        octant_cut_mass = _occ_volumes_mass(cut_vols)
    finally:
        for step_path in step_paths:
            try:
                os.remove(step_path)
            except OSError:
                pass
        try:
            os.rmdir(tmp_dir)
        except OSError:
            pass

    if not fuse_only:
        _occ_prune_extra_volumes(cut_vols)
        if len(cut_vols) != 8:
            raise RuntimeError(
                f"{progress_label}: expected 8 cut volumes, got {len(cut_vols)}"
            )
        return {
            "kind": "compound",
            "vols": cut_vols,
            "pipe_ref_mass": pipe_ref_mass,
            "cut_mass": octant_cut_mass,
            "baseline_cut_mass": octant_cut_mass,
            "centre_path_extension_mm": centre_ext_mm,
            "corner_path_extension_mm": corner_ext_mm,
            "center_overlap_mm": overlap_mm,
            "merge_strategy": (
                "both-end path extension + 8 octant-cut struts compound STEP"
            ),
        }

    merged_vol = _occ_merge_octant_cut_struts(
        cut_vols,
        cut_mass=octant_cut_mass,
        cell_size_mm=cell_size_mm,
        progress_label=progress_label,
        already_aligned=True,
    )
    merged_mass = float(gmsh.model.occ.getMass(3, int(merged_vol[1])))
    min_mass = MIN_CUT_MERGE_MASS_RATIO * float(octant_cut_mass)
    if octant_cut_mass > 0.0 and merged_mass < min_mass:
        raise RuntimeError(
            f"{progress_label}: merged mass {merged_mass:.1f} mm3 < "
            f"{min_mass:.1f} mm3 ({MIN_CUT_MERGE_MASS_RATIO:.0%} of octant cut sum)"
        )
    _occ_remove_all_volumes_except(merged_vol)
    return {
        "kind": "fused",
        "vol": merged_vol,
        "pipe_ref_mass": pipe_ref_mass,
        "cut_mass": octant_cut_mass,
        "baseline_cut_mass": octant_cut_mass,
        "centre_path_extension_mm": centre_ext_mm,
        "corner_path_extension_mm": corner_ext_mm,
        "center_overlap_mm": overlap_mm,
        "merge_strategy": (
            "both-end path extension + per-strut octant cut+align + sequential fuse "
            f"(order {list(OCTANT_SEQUENTIAL_FUSE_ORDER)})"
        ),
    }


def _occ_paper_box_octant_cut_compound(
    pipe_parts: list[tuple[str, tuple, float]],
    cell_size_mm: float,
    *,
    progress_label: str = "octant-box-cut-compound",
) -> dict[str, Any]:
    """
    Q=1: eight octant-cut struts in one STEP (no boolean merge).

    Uses centre path extension for clean cell-centre faces (manual fuse in CAD).
    """
    partition = verify_unitcell_octant_partition_mm(
        cell_size_mm,
        center_overlap_mm=OCTANT_CENTER_OVERLAP_MM,
    )
    if not partition.get("nominal_bisectors_at_zero"):
        raise RuntimeError(
            f"{progress_label}: octant virtual cubes not aligned to RVE "
            f"({partition.get('outer_face_errors') or partition.get('union_cover_errors')})"
        )
    print(
        f"  {progress_label}: octant partition OK; writing 8-body compound STEP...",
        flush=True,
    )

    pipe_parts, centre_ext_mm = pipe_parts_with_centre_path_extension(pipe_parts)
    if centre_ext_mm > 0.0:
        print(
            f"  {progress_label}: centre path extension={centre_ext_mm:g} mm",
            flush=True,
        )

    cut_vols, pipe_ref_mass = _occ_build_aligned_octant_cut_volumes(
        pipe_parts,
        cell_size_mm,
        progress_label=progress_label,
    )
    _occ_prune_extra_volumes(cut_vols)
    octant_cut_mass = _occ_volumes_mass(cut_vols)
    if len(cut_vols) != 8:
        raise RuntimeError(
            f"{progress_label}: expected 8 cut volumes, got {len(cut_vols)}"
        )
    return {
        "kind": "compound",
        "vols": cut_vols,
        "pipe_ref_mass": pipe_ref_mass,
        "cut_mass": octant_cut_mass,
        "baseline_cut_mass": octant_cut_mass,
        "merge_strategy": (
            "8 octant-cut struts compound STEP (centre extend; manual fuse in CAD)"
        ),
    }


def _occ_paper_box_centre_weld_cut(
    pipe_parts: list[tuple[str, tuple, float]],
    cell_size_mm: float,
    *,
    centre_radius_scale: float = Q1_CENTRE_WELD_RADIUS_SCALE,
    progress_label: str = "centre-weld-box-cut",
) -> dict[str, Any]:
    """
    Q=1 fallback: weld each pipe to a centre sphere, box-cut per strut, merge to 1 solid.

    The centre weld is consumed in the final boolean union; it only bridges the junction
    where raw spline pipes fail OCC fuse for −A_f·sin (Q=1).
    """
    import gmsh

    _, pipe_ref_mass, baseline_cut_mass = _occ_build_per_strut_box_cuts(
        pipe_parts,
        cell_size_mm,
        progress_label=f"{progress_label}-ref",
    )
    gmsh.model.occ.remove(gmsh.model.getEntities(), recursive=True)
    gmsh.model.occ.synchronize()

    pipe_tags = _occ_dimtags_from_parts(pipe_parts)
    gmsh.model.occ.synchronize()
    welded = _occ_weld_pipe_tags_at_centre(
        pipe_tags,
        pipe_parts,
        centre_radius_scale=centre_radius_scale,
        progress_label=progress_label,
    )
    box_vol = _occ_add_unitcell_box(cell_size_mm)
    gmsh.model.occ.synchronize()
    cut_vols = _occ_box_cut_pipe_tags(
        welded,
        box_vol,
        progress_label=progress_label,
    )
    cut_mass = _occ_volumes_mass(cut_vols)
    merged_vol = _occ_batch_merge_box_cut_struts(
        cut_vols,
        cut_mass=baseline_cut_mass,
        progress_label=progress_label,
    )
    merged_vol = _occ_intersect_volumes_with_box(
        [merged_vol],
        cell_size_mm,
        progress_label=f"{progress_label}-trim",
    )
    rod_radius = _pipe_sweep_nominal_radius(pipe_parts[0])
    merged_vol = _occ_trim_centre_junction_ball(
        merged_vol,
        rod_radius,
        baseline_cut_mass=baseline_cut_mass,
        progress_label=f"{progress_label}-centre-trim",
    )
    merged_mass = float(gmsh.model.occ.getMass(3, int(merged_vol[1])))
    min_mass = MIN_CUT_MERGE_MASS_RATIO * float(baseline_cut_mass)
    if baseline_cut_mass > 0.0 and merged_mass < min_mass:
        raise RuntimeError(
            f"{progress_label}: merged mass {merged_mass:.1f} mm3 < "
            f"{min_mass:.1f} mm3 ({MIN_CUT_MERGE_MASS_RATIO:.0%} of naked cut reference)"
        )
    gmsh.model.occ.remove(pipe_tags + [box_vol], recursive=True)
    gmsh.model.occ.synchronize()
    _occ_polish_merged_volume_for_step()
    return {
        "kind": "fused",
        "vol": merged_vol,
        "pipe_ref_mass": pipe_ref_mass,
        "cut_mass": cut_mass,
        "baseline_cut_mass": baseline_cut_mass,
        "merge_strategy": (
            f"centre weld (r×{centre_radius_scale:g}) + per-strut box-cut + "
            f"batch merge + centre trim (r×{Q1_CENTRE_TRIM_RADIUS_SCALE:g})"
        ),
    }


def _occ_paper_box_per_strut_cut(
    pipe_parts: list[tuple[str, tuple, float]],
    cell_size_mm: float,
    *,
    progress_label: str = "per-strut-box-cut",
) -> dict[str, Any]:
    """
    Paper box-cut without central pipe fuse: clip each strut, then merge to 1 solid.

    Used when pipe-first fuse fails (Q=1, high-Q SFBLS). Array fuse
    requires a single-volume unit-cell STEP — no 8-body compound export.
    """
    cut_vols, pipe_ref_mass, cut_mass = _occ_build_per_strut_box_cuts(
        pipe_parts,
        cell_size_mm,
        progress_label=progress_label,
    )
    merged_vol = _occ_merge_box_cut_struts(
        cut_vols,
        cut_mass=cut_mass,
        progress_label=progress_label,
    )
    return {
        "kind": "fused",
        "vol": merged_vol,
        "pipe_ref_mass": pipe_ref_mass,
        "cut_mass": cut_mass,
        "merge_strategy": "per-strut box-cut + strut merge",
    }


def _occ_intersect_volumes_with_box(
    lattice_vols: list[tuple[int, int]],
    cell_size_mm: float,
    *,
    progress_label: str = "box-cut",
) -> tuple[int, int]:
    """Boolean-intersect fused lattice volume(s) with the virtual RVE hexahedron."""
    import gmsh

    if not lattice_vols:
        raise RuntimeError(f"{progress_label}: no lattice volumes to clip")

    box_vol = _occ_add_unitcell_box(cell_size_mm)
    gmsh.model.occ.synchronize()
    print(
        f"  {progress_label}: intersect {len(lattice_vols)} lattice volume(s) "
        f"with L={cell_size_mm:g} mm RVE box...",
        flush=True,
    )
    out, _ = gmsh.model.occ.intersect(lattice_vols, [box_vol])
    gmsh.model.occ.synchronize()
    cut_vols = [(3, int(t)) for dim, t in out if dim == 3]
    if not cut_vols:
        raise RuntimeError(f"{progress_label}: box intersect produced no volume")
    if len(cut_vols) > 1:
        print(
            f"  {progress_label}: unify {len(cut_vols)} fragment(s) after intersect...",
            flush=True,
        )
        cut_vols = _occ_fuse_dimtags(cut_vols, progress_label=progress_label)
    keep = cut_vols[0]
    _occ_remove_all_volumes_except(keep)
    return keep


def _bbox_mm(vol: tuple[int, int]) -> tuple[float, float, float, float, float, float]:
    """Return (xmin, xmax, ymin, ymax, zmin, zmax) from gmsh OCC bounding box."""
    import gmsh

    xmin, ymin, zmin, xmax, ymax, zmax = (
        float(v) for v in gmsh.model.occ.getBoundingBox(*vol)
    )
    return (xmin, xmax, ymin, ymax, zmin, zmax)


def _bbox_union_mm(
    vols: list[tuple[int, int]],
) -> tuple[float, float, float, float, float, float]:
    boxes = [_bbox_mm(vol) for vol in vols]
    return (
        min(b[0] for b in boxes),
        max(b[1] for b in boxes),
        min(b[2] for b in boxes),
        max(b[3] for b in boxes),
        min(b[4] for b in boxes),
        max(b[5] for b in boxes),
    )


def _paper_box_report_from_cut_vol(
    *,
    path: str,
    nodes: list,
    beams: list,
    polylines: list[dict] | None,
    pipe_count: int,
    cell_size_mm: float,
    expected: tuple[float, float, float, float, float, float],
    cut_result: dict[str, Any],
    method: str,
    step_report: dict[str, Any],
    fused_volume_count: int,
    cut_vol: tuple[int, int] | None = None,
    post_mass_mm3: float | None = None,
    bbox_mm: tuple[float, float, float, float, float, float] | None = None,
) -> dict[str, Any]:
    """Build export manifest after a per-strut cut + merge path wrote a STEP."""
    if cut_vol is not None:
        import gmsh

        post_mass = float(gmsh.model.occ.getMass(3, int(cut_vol[1])))
        bbox = _bbox_mm(cut_vol)
    else:
        if post_mass_mm3 is None or bbox_mm is None:
            raise ValueError("Provide cut_vol or both post_mass_mm3 and bbox_mm.")
        post_mass = float(post_mass_mm3)
        bbox = bbox_mm

    pre_mass = float(cut_result["pipe_ref_mass"])
    cut_mass = float(
        cut_result.get("baseline_cut_mass") or cut_result.get("cut_mass") or 0.0
    )
    fuse_strategy = str(cut_result["merge_strategy"])
    mass_ratio_after_cut = post_mass / cut_mass if cut_mass > 0.0 else None

    step_report = _postprocess_written_step(
        path,
        step_report,
        fused_single=True,
        max_flatten_bodies=1,
    )
    fused_volume_count = int(step_report.get("solid_count", fused_volume_count))
    if not step_report.get("solidworks_safe"):
        raise RuntimeError(
            f"STEP not SolidWorks-safe (orphan PRODUCTs → multi-window): "
            f"{step_report.get('validation_error') or step_report}"
        )

    tol = max(0.5, 0.05 * float(cell_size_mm))
    h = 0.5 * float(cell_size_mm)
    overshoot = max(
        (-h) - bbox[0],
        bbox[1] - h,
        (-h) - bbox[2],
        bbox[3] - h,
        (-h) - bbox[4],
        bbox[5] - h,
    )
    return {
        "step_path": path,
        "pipe_count": pipe_count,
        "cell_size_mm": float(cell_size_mm),
        "fused_volume_count": fused_volume_count,
        "step_product_count": step_report.get("product_count"),
        "step_solidworks_safe": step_report.get("solidworks_safe"),
        "fuse_strategy": fuse_strategy,
        "mass_mm3_before_cut": pre_mass,
        "mass_mm3_after_cut": post_mass,
        "mass_ratio_after_cut": mass_ratio_after_cut,
        "bbox_mm": bbox,
        "bbox_expected_mm": expected,
        "bbox_overshoot_mm": overshoot,
        "bbox_overshoot_tolerance_mm": tol,
        "bbox_within_rve": overshoot <= tol,
        "node_count": len(nodes),
        "beam_count": len(beams),
        "polyline_count": len(polylines or []),
        "method": method,
        "q1_paper_orientation": q1_paper_orientation_label(),
    }


def _paper_box_report_from_octant_compound(
    *,
    path: str,
    nodes: list,
    beams: list,
    polylines: list[dict] | None,
    pipe_count: int,
    cell_size_mm: float,
    expected: tuple[float, float, float, float, float, float],
    cut_result: dict[str, Any],
    method: str,
    step_report: dict[str, Any],
    body_count: int,
    post_mass_mm3: float,
    bbox_mm: tuple[float, float, float, float, float, float],
) -> dict[str, Any]:
    """Build export manifest for an eight-body octant compound STEP."""
    pre_mass = float(cut_result["pipe_ref_mass"])
    cut_mass = float(
        cut_result.get("baseline_cut_mass") or cut_result.get("cut_mass") or 0.0
    )
    fuse_strategy = str(cut_result["merge_strategy"])
    mass_ratio_after_cut = post_mass_mm3 / cut_mass if cut_mass > 0.0 else None

    step_report = _postprocess_written_step(
        path,
        step_report,
        fused_single=False,
        max_flatten_bodies=max(8, body_count),
    )
    solid_count = int(step_report.get("solid_count", body_count))

    tol = max(0.5, 0.05 * float(cell_size_mm))
    h = 0.5 * float(cell_size_mm)
    overshoot = max(
        (-h) - bbox_mm[0],
        bbox_mm[1] - h,
        (-h) - bbox_mm[2],
        bbox_mm[3] - h,
        (-h) - bbox_mm[4],
        bbox_mm[5] - h,
    )
    return {
        "step_path": path,
        "pipe_count": pipe_count,
        "cell_size_mm": float(cell_size_mm),
        "fused_volume_count": solid_count,
        "step_product_count": step_report.get("product_count"),
        "step_solidworks_safe": step_report.get("solidworks_safe"),
        "fuse_strategy": fuse_strategy,
        "mass_mm3_before_cut": pre_mass,
        "mass_mm3_after_cut": float(post_mass_mm3),
        "mass_ratio_after_cut": mass_ratio_after_cut,
        "bbox_mm": bbox_mm,
        "bbox_expected_mm": expected,
        "bbox_overshoot_mm": overshoot,
        "bbox_overshoot_tolerance_mm": tol,
        "bbox_within_rve": overshoot <= tol,
        "node_count": len(nodes),
        "beam_count": len(beams),
        "polyline_count": len(polylines or []),
        "method": method,
        "q1_paper_orientation": q1_paper_orientation_label(),
        "compound_bodies": body_count,
        "manual_fuse_required": True,
    }


def _try_q1_paper_box_cut_path(
    pipe_parts: list[tuple[str, tuple, float]],
    path: str,
    *,
    nodes: list,
    beams: list,
    polylines: list[dict] | None,
    pipe_count: int,
    cell_size_mm: float,
    expected: tuple[float, float, float, float, float, float],
    allow_compound_fallback: bool = True,
    both_end_extension: bool = True,
    centre_extension_mm: float | None = None,
    corner_extension_mm: float | None = None,
    both_ext_compound: bool = False,
    n_segments_hint: int = 24,
    rod_diameter_mm: float = 2.0,
    amplitude_mm: float = 2.0,
    period_factor: float | None = None,
) -> dict[str, Any] | None:
    """Q=1: octant 1/8 cut + sequential fuse; optional compound STEP fallback."""
    import gmsh

    tmp_path = f"{os.path.abspath(path)}.__q1__.step"
    gmsh_session_open = False

    def _write_fused(cut_result: dict[str, Any], *, method: str) -> dict[str, Any]:
        cut_vol = cut_result["vol"]
        baseline = float(
            cut_result.get("baseline_cut_mass")
            or cut_result.get("cut_mass")
            or 0.0
        )
        post_mass = float(gmsh.model.occ.getMass(3, int(cut_vol[1])))
        bbox = _bbox_mm(cut_vol)
        if baseline > 0.0 and post_mass < MIN_CUT_MERGE_MASS_RATIO * baseline:
            raise RuntimeError(
                f"merged mass {post_mass:.1f} mm3 < "
                f"{MIN_CUT_MERGE_MASS_RATIO:.0%} of reference {baseline:.1f} mm3"
            )
        step_report = _finalize_occ_step_write(
            tmp_path, fuse=True, validate_step=False
        )
        fused_volume_count = int(step_report.get("solid_count", 0))
        gmsh.finalize()
        report = _paper_box_report_from_cut_vol(
            path=tmp_path,
            nodes=nodes,
            beams=beams,
            polylines=polylines,
            pipe_count=pipe_count,
            cell_size_mm=cell_size_mm,
            expected=expected,
            cut_result=cut_result,
            method=method,
            step_report=step_report,
            fused_volume_count=fused_volume_count,
            post_mass_mm3=post_mass,
            bbox_mm=bbox,
        )
        os.replace(tmp_path, os.path.abspath(path))
        report["step_path"] = os.path.abspath(path)
        return report

    try:
        if both_end_extension:
            print(
                "  Paper box-cut: Q=1 octant-box-cut "
                "(both-end extension + sequential fuse)...",
                flush=True,
            )
            cut_result = _occ_paper_box_octant_cut_both_ext(
                pipe_parts,
                cell_size_mm,
                progress_label="octant-box-cut-both-ext",
                centre_extension_mm=centre_extension_mm,
                corner_extension_mm=corner_extension_mm,
                fuse_only=not both_ext_compound,
                period_factor=float(period_factor or 1.0),
                n_segments=int(n_segments_hint or 24),
                rod_diameter=float(rod_diameter_mm or 2.0),
                amplitude=float(amplitude_mm or 2.0),
            )
            gmsh_session_open = gmsh.isInitialized()
            if cut_result.get("kind") == "compound":
                vols = list(cut_result["vols"])
                post_mass = _occ_volumes_mass(vols)
                bbox = _bbox_union_mm(vols)
                step_report = _finalize_occ_step_write(
                    tmp_path, fuse=False, validate_step=False
                )
                gmsh.finalize()
                gmsh_session_open = False
                report = _paper_box_report_from_octant_compound(
                    path=tmp_path,
                    nodes=nodes,
                    beams=beams,
                    polylines=polylines,
                    pipe_count=pipe_count,
                    cell_size_mm=cell_size_mm,
                    expected=expected,
                    cut_result=cut_result,
                    method="gmsh_occ_octant_box_cut_both_ext_compound",
                    step_report=step_report,
                    body_count=len(vols),
                    post_mass_mm3=post_mass,
                    bbox_mm=bbox,
                )
                os.replace(tmp_path, os.path.abspath(path))
                report["step_path"] = os.path.abspath(path)
                print(
                    f"  Paper box-cut: both-ext compound STEP OK "
                    f"({report.get('compound_bodies')} bodies, manual fuse in CAD)",
                    flush=True,
                )
                return report
            method = "gmsh_occ_octant_box_cut_both_ext"
        else:
            gmsh.initialize()
            gmsh_session_open = True
            gmsh.option.setNumber("General.Terminal", 0)
            gmsh.model.add(
                os.path.splitext(os.path.basename(path))[0] or "unitcell_box_cut"
            )
            _configure_occ_for_fuse()
            print("  Paper box-cut: Q=1 octant-box-cut (sequential fuse)...", flush=True)
            cut_result = _occ_paper_box_octant_cut(
                pipe_parts,
                cell_size_mm,
                progress_label="octant-box-cut",
            )
            method = "gmsh_occ_octant_box_cut"
        report = _write_fused(
            cut_result,
            method=method,
        )
        gmsh_session_open = False
        return report
    except Exception as exc:
        print(
            f"  Paper box-cut: Q=1 sequential fuse failed ({exc}); "
            + (
                "writing 8-body compound STEP..."
                if allow_compound_fallback
                else "no compound fallback."
            ),
            flush=True,
        )
    finally:
        if gmsh_session_open:
            try:
                gmsh.finalize()
            except Exception:
                pass
            gmsh_session_open = False

    if not allow_compound_fallback:
        return None

    if both_end_extension:
        try:
            return _export_q1_both_ext_compound_step(
                pipe_parts,
                path,
                nodes=nodes,
                beams=beams,
                polylines=polylines,
                pipe_count=pipe_count,
                cell_size_mm=cell_size_mm,
                expected=expected,
                centre_extension_mm=centre_extension_mm,
                corner_extension_mm=corner_extension_mm,
            )
        except Exception as exc:
            print(
                f"  Paper box-cut: Q=1 both-ext compound export failed ({exc})",
                flush=True,
            )
            return None

    try:
        return _export_q1_octant_compound_step(
            pipe_parts,
            path,
            nodes=nodes,
            beams=beams,
            polylines=polylines,
            pipe_count=pipe_count,
            cell_size_mm=cell_size_mm,
            expected=expected,
        )
    except Exception as exc:
        print(f"  Paper box-cut: Q=1 compound export failed ({exc})", flush=True)
    return None


def _export_q1_both_ext_compound_step(
    pipe_parts: list[tuple[str, tuple, float]],
    path: str,
    *,
    nodes: list,
    beams: list,
    polylines: list[dict] | None,
    pipe_count: int,
    cell_size_mm: float,
    expected: tuple[float, float, float, float, float, float],
    centre_extension_mm: float | None = None,
    corner_extension_mm: float | None = None,
) -> dict[str, Any]:
    """Q=1: eight both-end extended octant-cut struts in one compound STEP."""
    import gmsh

    tmp_path = f"{os.path.abspath(path)}.__q1__.step"
    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add(
            os.path.splitext(os.path.basename(path))[0] or "unitcell_box_cut_both_ext"
        )
        _configure_occ_for_fuse()
        print(
            "  Paper box-cut: Q=1 both-ext octant compound (8 cut struts)...",
            flush=True,
        )
        cut_result = _occ_paper_box_octant_cut_both_ext(
            pipe_parts,
            cell_size_mm,
            progress_label="octant-box-cut-both-ext-compound",
            centre_extension_mm=centre_extension_mm,
            corner_extension_mm=corner_extension_mm,
            fuse_only=False,
        )
        vols = list(cut_result["vols"])
        post_mass = _occ_volumes_mass(vols)
        bbox = _bbox_union_mm(vols)
        step_report = _finalize_occ_step_write(
            tmp_path, fuse=False, validate_step=False
        )
        gmsh.finalize()
        report = _paper_box_report_from_octant_compound(
            path=tmp_path,
            nodes=nodes,
            beams=beams,
            polylines=polylines,
            pipe_count=pipe_count,
            cell_size_mm=cell_size_mm,
            expected=expected,
            cut_result=cut_result,
            method="gmsh_occ_octant_box_cut_both_ext_compound",
            step_report=step_report,
            body_count=len(vols),
            post_mass_mm3=post_mass,
            bbox_mm=bbox,
        )
        os.replace(tmp_path, os.path.abspath(path))
        report["step_path"] = os.path.abspath(path)
        print(
            f"  Paper box-cut: both-ext compound STEP OK "
            f"({report.get('compound_bodies')} bodies, manual fuse in CAD)",
            flush=True,
        )
        return report
    except Exception:
        try:
            gmsh.finalize()
        except Exception:
            pass
        raise


def _export_q1_octant_compound_step(
    pipe_parts: list[tuple[str, tuple, float]],
    path: str,
    *,
    nodes: list,
    beams: list,
    polylines: list[dict] | None,
    pipe_count: int,
    cell_size_mm: float,
    expected: tuple[float, float, float, float, float, float],
) -> dict[str, Any]:
    """Q=1: eight centre-extended octant-cut struts in one compound STEP (manual CAD fuse)."""
    import gmsh

    tmp_path = f"{os.path.abspath(path)}.__q1__.step"
    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add(
            os.path.splitext(os.path.basename(path))[0] or "unitcell_box_cut_compound"
        )
        _configure_occ_for_fuse()
        print(
            "  Paper box-cut: Q=1 octant compound (8 cut struts, centre extend)...",
            flush=True,
        )
        cut_result = _occ_paper_box_octant_cut_compound(
            pipe_parts,
            cell_size_mm,
            progress_label="octant-box-cut-compound",
        )
        vols = list(cut_result["vols"])
        post_mass = _occ_volumes_mass(vols)
        bbox = _bbox_union_mm(vols)
        step_report = _finalize_occ_step_write(
            tmp_path, fuse=False, validate_step=False
        )
        gmsh.finalize()
        report = _paper_box_report_from_octant_compound(
            path=tmp_path,
            nodes=nodes,
            beams=beams,
            polylines=polylines,
            pipe_count=pipe_count,
            cell_size_mm=cell_size_mm,
            expected=expected,
            cut_result=cut_result,
            method="gmsh_occ_octant_box_cut_compound",
            step_report=step_report,
            body_count=len(vols),
            post_mass_mm3=post_mass,
            bbox_mm=bbox,
        )
        os.replace(tmp_path, os.path.abspath(path))
        report["step_path"] = os.path.abspath(path)
        print(
            f"  Paper box-cut: compound STEP OK "
            f"({report.get('compound_bodies')} bodies, manual fuse in CAD)",
            flush=True,
        )
        return report
    except Exception:
        try:
            gmsh.finalize()
        except Exception:
            pass
        raise


def export_unitcell_step_paper_box_cut(
    nodes: list,
    beams: list,
    path: str,
    *,
    polylines: list[dict] | None = None,
    cell_size_mm: float = 20.0,
    n_segments_hint: int = 24,
    period_factor: float | None = None,
    q1_mode: str = "auto",
    both_end_extension: bool = True,
    centre_extension_mm: float | None = None,
    corner_extension_mm: float | None = None,
    both_ext_compound: bool = False,
    rod_diameter_mm: float = 2.0,
    amplitude_mm: float = 2.0,
    solid_profile: str = "circle",
    ellipse_minor_ratio: float = 0.6,
    compression_axis: tuple[float, float, float] = (0.0, 0.0, 1.0),
    ellipse_align_to_compression: str = "minor",
) -> dict[str, Any]:
    """
    Export one fused unit-cell STEP using paper-style virtual hexahedron cutting.

    ``q1_mode`` for Q=1:
    - ``auto``: sequential fuse, compound STEP fallback on failure
    - ``fuse``: sequential fuse only
    - ``compound``: 8 centre-extended octant-cut struts in one STEP (manual CAD fuse)

    ``both_end_extension=True`` extends each pipe at centre and corner before
    octant cut (Q=1 sequential fuse trial path).
    """
    try:
        import gmsh
    except ImportError as exc:
        raise ImportError(
            "Paper box-cut STEP export requires gmsh. Install: pip install gmsh"
        ) from exc

    _, pipe_parts_only = _collect_solid_primitives(
        nodes,
        beams,
        polylines=polylines,
        junction_spheres=False,
        trim_for_junctions=False,
        polyline_sweep="pipe",
        solid_profile=solid_profile,
        ellipse_minor_ratio=ellipse_minor_ratio,
        compression_axis=compression_axis,
        ellipse_align_to_compression=ellipse_align_to_compression,
    )
    pipe_parts = [p for p in pipe_parts_only if p[0] in ("pipe", "pipe_ellipse")]
    pipe_count = len(pipe_parts)
    if pipe_count == 0:
        raise ValueError("No pipe primitives for paper box-cut export.")

    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    expected = unitcell_box_bounds_mm(cell_size_mm)
    q1 = period_factor is not None and is_q1_period(period_factor)
    # Ellipse pipe-first routinely drops rods while still clearing the old 0.80/0.85
    # mass gates; force the Q=1 octant sequential recipe for all Q.
    force_octant = str(solid_profile or "circle").strip().lower() == "ellipse"
    use_octant = bool(q1 or force_octant)
    q1_mode_norm = str(q1_mode or "auto").strip().lower()
    if q1_mode_norm not in ("auto", "fuse", "compound"):
        raise ValueError(f"q1_mode must be auto|fuse|compound, got {q1_mode!r}")

    if use_octant:
        if q1_mode_norm == "compound":
            return _export_q1_octant_compound_step(
                pipe_parts,
                path,
                nodes=nodes,
                beams=beams,
                polylines=polylines,
                pipe_count=pipe_count,
                cell_size_mm=cell_size_mm,
                expected=expected,
            )
        q1_report = _try_q1_paper_box_cut_path(
            pipe_parts,
            path,
            nodes=nodes,
            beams=beams,
            polylines=polylines,
            pipe_count=pipe_count,
            cell_size_mm=cell_size_mm,
            expected=expected,
            allow_compound_fallback=(q1_mode_norm == "auto"),
            both_end_extension=both_end_extension,
            centre_extension_mm=centre_extension_mm,
            corner_extension_mm=corner_extension_mm,
            both_ext_compound=both_ext_compound,
            n_segments_hint=n_segments_hint,
            rod_diameter_mm=rod_diameter_mm,
            amplitude_mm=amplitude_mm,
            period_factor=period_factor,
        )
        if q1_report is not None:
            from src.export.sw_parasolid import recenter_step_bbox_to_origin

            recenter = recenter_step_bbox_to_origin(path)
            if recenter.get("shifted"):
                print(
                    f"  recenter 1x1 bbox mid → origin: "
                    f"dx={float(recenter['dx']):+.4f} dy={float(recenter['dy']):+.4f} "
                    f"dz={float(recenter['dz']):+.4f} mm",
                    flush=True,
                )
            q1_report = dict(q1_report)
            q1_report["bbox_recenter"] = recenter
            q1_report["both_end_extension"] = bool(both_end_extension)
            return q1_report
        if force_octant and not q1:
            # Ellipse Q≠1: per-strut merge can hang for hours on OCC (seen Q=1.5).
            # Fail fast here so the batch ladder can try OCP / dedicated attempts.
            raise RuntimeError(
                "Paper box-cut: ellipse octant failed "
                f"(period_factor={period_factor}); skip hang-prone per-strut "
                "(batch will try OCP / other strategies)."
            )
        if q1:
            print(
                "  Paper box-cut: Q=1 octant path failed; "
                "falling back to per-strut box-cut...",
                flush=True,
            )

    pipe_first_ok = False
    fuse_strategy = ""
    method = "gmsh_occ_pipe_box_cut"
    pre_mass = 0.0
    post_mass = 0.0
    mass_ratio_after_cut: float | None = None
    bbox: tuple[float, float, float, float, float, float] | None = None
    step_report: dict[str, Any] = {}
    fused_volume_count = 0

    # Skip pipe-first when octant was required (ellipse / Q=1): it drops rods.
    if not use_octant:
        gmsh.initialize()
        try:
            gmsh.option.setNumber("General.Terminal", 0)
            gmsh.model.add(os.path.splitext(os.path.basename(path))[0] or "unitcell_box_cut")
            _configure_occ_for_fuse()

            print(
                f"  Paper box-cut: {pipe_count} pipe(s), L={cell_size_mm:g} mm, "
                "junction spheres=off...",
                flush=True,
            )
            pipe_tags = _occ_dimtags_from_parts(pipe_parts)
            gmsh.model.occ.synchronize()
            pipe_ref_mass = _occ_volumes_mass(pipe_tags)
            gmsh.model.occ.remove(gmsh.model.getEntities(), recursive=True)
            gmsh.model.occ.synchronize()

            fused_vols, fuse_strategy = _occ_fuse_lattice_for_box_cut(
                pipe_parts,
                progress_label="intra-fuse",
            )
            pre_mass = _occ_volumes_mass(fused_vols)
            # Softer than merge gate: catch missing struts, allow small OCC loss.
            if (
                pipe_ref_mass > 0.0
                and pre_mass < PIPE_FIRST_INTRA_FUSE_MIN_MASS_RATIO * pipe_ref_mass
            ):
                raise RuntimeError(
                    f"intra-fuse mass ratio {pre_mass / pipe_ref_mass:.2f} "
                    f"({pre_mass:.1f}/{pipe_ref_mass:.1f} mm3)"
                )
            cut_vol = _occ_intersect_volumes_with_box(
                fused_vols,
                cell_size_mm,
                progress_label="box-cut",
            )
            fuse_strategy = f"{fuse_strategy} + RVE box intersect"
            post_mass = float(gmsh.model.occ.getMass(3, int(cut_vol[1])))
            mass_ratio_after_cut = post_mass / pre_mass if pre_mass > 0.0 else None
            bbox = _bbox_mm(cut_vol)
            step_report = _finalize_occ_step_write(path, fuse=True, validate_step=False)
            fused_volume_count = int(step_report.get("solid_count", 0))
            pipe_first_ok = True
        except Exception as exc:
            print(
                f"  Paper box-cut: pipe-first fuse-then-cut failed ({exc})",
                flush=True,
            )
        finally:
            gmsh.finalize()

    if not pipe_first_ok:
        print(
            "  Paper box-cut: → per-strut box-cut "
            f"(q1={q1}, ellipse_force_octant={force_octant})...",
            flush=True,
        )
        gmsh.initialize()
        try:
            gmsh.option.setNumber("General.Terminal", 0)
            gmsh.model.add(
                os.path.splitext(os.path.basename(path))[0] or "unitcell_per_strut"
            )
            _configure_occ_for_fuse()
            cut_result = _occ_paper_box_per_strut_cut(
                pipe_parts,
                cell_size_mm,
                progress_label="per-strut-box-cut",
            )
            cut_vol = cut_result["vol"]
            step_report = _finalize_occ_step_write(path, fuse=True, validate_step=False)
            fused_volume_count = int(step_report.get("solid_count", 0))
            return _paper_box_report_from_cut_vol(
                path=path,
                nodes=nodes,
                beams=beams,
                polylines=polylines,
                pipe_count=pipe_count,
                cell_size_mm=cell_size_mm,
                expected=expected,
                cut_result=cut_result,
                method="gmsh_occ_per_strut_pipe_box_cut",
                step_report=step_report,
                fused_volume_count=fused_volume_count,
                cut_vol=cut_vol,
            )
        finally:
            gmsh.finalize()

    step_report = _postprocess_written_step(
        path,
        step_report,
        fused_single=True,
        max_flatten_bodies=1,
    )
    fused_volume_count = int(step_report.get("solid_count", fused_volume_count))

    from src.export.sw_parasolid import recenter_step_bbox_to_origin

    recenter = recenter_step_bbox_to_origin(path)
    if recenter.get("shifted"):
        print(
            f"  recenter 1x1 COM → origin: "
            f"dx={float(recenter['dx']):+.4f} dy={float(recenter['dy']):+.4f} "
            f"dz={float(recenter['dz']):+.4f} mm",
            flush=True,
        )
        bb = recenter.get("bbox_mm") or {}
        if isinstance(bb, dict) and "x" in bb and "y" in bb and "z" in bb:
            bbox = (
                float(bb["x"][0]),
                float(bb["x"][1]),
                float(bb["y"][0]),
                float(bb["y"][1]),
                float(bb["z"][0]),
                float(bb["z"][1]),
            )

    tol = max(0.5, 0.05 * float(cell_size_mm))
    h = 0.5 * float(cell_size_mm)
    assert bbox is not None
    overshoot = max(
        (-h) - bbox[0],
        bbox[1] - h,
        (-h) - bbox[2],
        bbox[3] - h,
        (-h) - bbox[4],
        bbox[5] - h,
    )
    bbox_ok = overshoot <= tol

    return {
        "step_path": path,
        "pipe_count": pipe_count,
        "cell_size_mm": float(cell_size_mm),
        "fused_volume_count": fused_volume_count,
        "step_product_count": step_report.get("product_count"),
        "step_solidworks_safe": step_report.get("solidworks_safe"),
        "fuse_strategy": fuse_strategy,
        "mass_mm3_before_cut": pre_mass,
        "mass_mm3_after_cut": post_mass,
        "mass_ratio_after_cut": mass_ratio_after_cut,
        "bbox_mm": bbox,
        "bbox_expected_mm": expected,
        "bbox_overshoot_mm": overshoot,
        "bbox_overshoot_tolerance_mm": tol,
        "bbox_within_rve": bbox_ok,
        "bbox_recenter": recenter,
        "node_count": len(nodes),
        "beam_count": len(beams),
        "polyline_count": len(polylines or []),
        "method": method,
        "q1_paper_orientation": (
            q1_paper_orientation_label()
            if period_factor is not None and is_q1_period(period_factor)
            else None
        ),
    }
