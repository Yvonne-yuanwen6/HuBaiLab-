"""4×4×4 paper_box array fuse via OCP GlueShift (same layered workflow as gmsh route)."""

from __future__ import annotations

import os
from typing import Any

from src.export.export_sw import (
    _collect_solid_primitives,
    _lattice_cell_offset_xyz_mm,
    _rewrite_and_analyze_fused_step,
)
from src.export.ocp_unitcell_fuse import (
    GlueMode,
    build_q1_octant_cut_shapes,
    fuse_octant_shapes,
    ocp_fuse_batch,
    ocp_fuse_pair,
    ocp_clip_to_periodic_cell,
    ocp_heal_fused_solid,
    ocp_mass,
    ocp_readback_step,
    ocp_shape_topology,
    ocp_write_step_via_gmsh_brep_heal,
)
from src.export.paper_box_array_fuse import (
    export_paper_box_zslab_copies,
    paper_box_seed_step,
)
from src.generator.hu_bai_bcc import HuBaiLatticeGenerator

DEFAULT_OCP_GLUE: GlueMode = "shift"
DEFAULT_OCP_ROW_GLUE: GlueMode = "full"
DEFAULT_OCP_INTER_ROW_GLUE: GlueMode = "shift"
DEFAULT_OCP_INTER_CELL_GLUE: GlueMode = "full"  # legacy alias for row glue
DEFAULT_OCP_FUZZY_MM = 0.02
DEFAULT_OCP_ROW_FUZZY_MM = 0.05
DEFAULT_OCP_INTER_ROW_FUZZY_MM = 0.02
DEFAULT_OCP_INTER_CELL_FUZZY_MM = 0.05  # legacy alias for row fuzzy
DEFAULT_OCP_CELL_STRATEGY = "sequential_glue_shift"
InterCellFuseMode = str  # "hierarchical_batch" | "sequential"
DEFAULT_OCP_INTER_CELL_FUSE_MODE = "hierarchical_batch"


def ocp_default_q1_seed_step() -> str:
    from src.paths import CAD_ROOT

    return os.path.join(
        str(CAD_ROOT),
        "_ocp_glue_pilot",
        "unitcell_af2q1_L20_ocp_stub_sequential-glue-shift.step",
    )


def load_q1_pipe_parts(
    *,
    cell_size: float = 20.0,
    rod_d: float = 2.0,
    amplitude: float = 2.0,
    n_segments: int = 24,
) -> list[tuple[str, tuple, float]]:
    gen = HuBaiLatticeGenerator(
        cell_size=float(cell_size),
        rod_diameter=float(rod_d),
        amplitude=float(amplitude),
        period_factor=1.0,
        n_segments=max(3, int(n_segments)),
    )
    gen.build_unitcell()
    nodes, beams, polylines = gen.get_data(copy=True)
    _, pipes_only = _collect_solid_primitives(
        nodes,
        beams,
        polylines=polylines,
        junction_spheres=False,
        trim_for_junctions=False,
        polyline_sweep="pipe",
    )
    pipe_parts = [p for p in pipes_only if p[0] == "pipe"]
    if len(pipe_parts) != 8:
        raise RuntimeError(f"expected 8 pipe parts, got {len(pipe_parts)}")
    return pipe_parts


def _translate_pipe_parts(
    pipe_parts: list[tuple[str, tuple, float]],
    dx: float,
    dy: float,
    dz: float,
) -> list[tuple[str, tuple, float]]:
    if abs(dx) < 1e-12 and abs(dy) < 1e-12 and abs(dz) < 1e-12:
        return list(pipe_parts)
    out: list[tuple[str, tuple, float]] = []
    for kind, path, radius in pipe_parts:
        new_path = tuple(
            (float(p[0]) + dx, float(p[1]) + dy, float(p[2]) + dz) for p in path
        )
        out.append((kind, new_path, radius))
    return out


def _build_ocp_unitcell_at_offset(
    pipe_parts: list[tuple[str, tuple, float]],
    offset: tuple[float, float, float],
    *,
    cell_size: float,
    cell_strategy: str = DEFAULT_OCP_CELL_STRATEGY,
    fuzzy_mm: float = DEFAULT_OCP_FUZZY_MM,
) -> tuple[Any, float]:
    """Build one fused OCP unit cell at grid offset (local octant cut → translate)."""
    dx, dy, dz = offset
    cut_shapes, _, cut_mass = build_q1_octant_cut_shapes(pipe_parts, float(cell_size))
    cell_shape, _ = fuse_octant_shapes(
        cut_shapes,
        cut_mass=cut_mass,
        strategy=cell_strategy,  # type: ignore[arg-type]
        fuzzy_mm=float(fuzzy_mm),
        cell_size_mm=float(cell_size),
    )
    if abs(dx) > 1e-12 or abs(dy) > 1e-12 or abs(dz) > 1e-12:
        from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
        from OCP.gp import gp_Trsf, gp_Vec

        trsf = gp_Trsf()
        trsf.SetTranslation(gp_Vec(float(dx), float(dy), float(dz)))
        cell_shape = BRepBuilderAPI_Transform(cell_shape, trsf, True).Shape()
    return cell_shape, ocp_mass(cell_shape)


def _ocp_fuse_group_sequential(
    shapes: list[Any],
    *,
    glue: GlueMode,
    fuzzy_mm: float,
    label: str,
    ref_mass_per_piece: float,
) -> Any:
    if not shapes:
        raise RuntimeError(f"{label}: no shapes")
    if len(shapes) == 1:
        return shapes[0]

    acc = shapes[0]
    min_step_delta = 0.20 * float(ref_mass_per_piece)
    for idx, shape in enumerate(shapes[1:], start=2):
        prev_mass = ocp_mass(acc)
        acc = ocp_fuse_pair(
            acc,
            shape,
            glue=glue,
            fuzzy_mm=fuzzy_mm,
            label=f"{label} {idx}/{len(shapes)}",
        )
        new_mass = ocp_mass(acc)
        if new_mass < prev_mass + min_step_delta:
            raise RuntimeError(
                f"{label}: fuse step {idx}/{len(shapes)} mass drop "
                f"({new_mass:.1f} < {prev_mass + min_step_delta:.1f} mm³)"
            )
        print(
            f"  {label}: fused {idx}/{len(shapes)} mass={new_mass:.1f} mm³",
            flush=True,
        )
    return acc


def _ocp_fuse_group_batch(
    shapes: list[Any],
    *,
    glue: GlueMode,
    fuzzy_mm: float,
    label: str,
    ref_mass_per_piece: float,
) -> Any:
    if not shapes:
        raise RuntimeError(f"{label}: no shapes")
    if len(shapes) == 1:
        return shapes[0]

    expected = ref_mass_per_piece * len(shapes)
    min_mass = 0.85 * expected
    fused = ocp_fuse_batch(
        shapes,
        glue=glue,
        fuzzy_mm=fuzzy_mm,
        label=label,
    )
    fused_mass = ocp_mass(fused)
    if fused_mass < min_mass:
        raise RuntimeError(
            f"{label}: batch fuse mass {fused_mass:.1f} mm³ "
            f"< 85% of expected {expected:.1f} mm³ "
            f"(glue={glue}, fuzzy={fuzzy_mm:g} mm)"
        )
    print(
        f"  {label}: batch fused {len(shapes)} piece(s) "
        f"mass={fused_mass:.1f} mm³ (glue={glue}, fuzzy={fuzzy_mm:g} mm)",
        flush=True,
    )
    return fused


def _ocp_fuse_zslab_cells(
    cell_shapes: list[Any],
    *,
    nx: int,
    ny: int,
    iz: int,
    seed_mass: float,
    fuse_mode: str = DEFAULT_OCP_INTER_CELL_FUSE_MODE,
    row_glue: GlueMode = DEFAULT_OCP_ROW_GLUE,
    row_fuzzy_mm: float = DEFAULT_OCP_ROW_FUZZY_MM,
    inter_row_glue: GlueMode = DEFAULT_OCP_INTER_ROW_GLUE,
    inter_row_fuzzy_mm: float = DEFAULT_OCP_INTER_ROW_FUZZY_MM,
) -> Any:
    """Fuse nx×ny translated unit cells: row GlueFull batch, inter-row GlueShift."""
    nx_i, ny_i = int(nx), int(ny)
    iz_i = int(iz)
    use_batch = fuse_mode == "hierarchical_batch"
    row_fuser = _ocp_fuse_group_batch if use_batch else _ocp_fuse_group_sequential
    inter_fuser = _ocp_fuse_group_batch if use_batch else _ocp_fuse_group_sequential

    row_shapes: list[Any] = []
    for iy in range(ny_i):
        row = cell_shapes[iy * nx_i : (iy + 1) * nx_i]
        print(
            f"  OCP z-slab iz={iz_i}: row iy={iy} fuse {len(row)} cell(s) "
            f"({fuse_mode}, glue={row_glue})...",
            flush=True,
        )
        row_shapes.append(
            row_fuser(
                row,
                glue=row_glue,
                fuzzy_mm=row_fuzzy_mm,
                label=f"ocp-zslab-iz{iz_i}-row{iy}",
                ref_mass_per_piece=seed_mass,
            )
        )

    if len(row_shapes) == 1:
        return row_shapes[0]

    print(
        f"  OCP z-slab iz={iz_i}: inter-row fuse {len(row_shapes)} row(s) "
        f"({fuse_mode}, glue={inter_row_glue})...",
        flush=True,
    )
    return inter_fuser(
        row_shapes,
        glue=inter_row_glue,
        fuzzy_mm=inter_row_fuzzy_mm,
        label=f"ocp-zslab-iz{iz_i}-inter-row",
        ref_mass_per_piece=seed_mass * nx_i,
    )


def _ocp_write_fused_step(shape: Any, path: str, *, skip_gmsh_heal: bool = False) -> dict[str, Any]:
    export_shape = ocp_heal_fused_solid(shape)
    readback = ocp_write_step_via_gmsh_brep_heal(
        export_shape, path, skip_gmsh_heal=skip_gmsh_heal
    )
    step_report = _rewrite_and_analyze_fused_step(
        path,
        prior={
            "solid_count": int(readback.get("solids") or 1),
            "product_count": 1,
            "solidworks_safe": bool(readback.get("brep_valid")),
        },
    )
    return step_report


def ocp_read_step_shape(path: str) -> Any:
    from OCP.STEPControl import STEPControl_Reader

    path = os.path.abspath(path)
    reader = STEPControl_Reader()
    if reader.ReadFile(path) != 1:
        raise RuntimeError(f"OCP STEP read failed: {path}")
    reader.TransferRoots()
    shape = reader.OneShape()
    stats = ocp_shape_topology(shape)
    if int(stats.get("solids") or 0) != 1:
        raise RuntimeError(
            f"OCP STEP must be 1 solid, got {stats.get('solids')} solid(s): {path}"
        )
    return shape


def ocp_translate_shape(
    shape: Any,
    dx: float,
    dy: float,
    dz: float,
) -> Any:
    """Copy + translate one fused unit-cell solid (periodic array placement)."""
    if abs(dx) < 1e-12 and abs(dy) < 1e-12 and abs(dz) < 1e-12:
        return shape
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
    from OCP.gp import gp_Trsf, gp_Vec

    trsf = gp_Trsf()
    trsf.SetTranslation(gp_Vec(float(dx), float(dy), float(dz)))
    return BRepBuilderAPI_Transform(shape, trsf, True).Shape()


def load_ocp_unitcell_shape(
    seed_step: str,
    *,
    cell_size: float = 20.0,
    cell_strategy: str = DEFAULT_OCP_CELL_STRATEGY,
    fuzzy_mm: float = DEFAULT_OCP_FUZZY_MM,
    rebuild_from_geometry: bool = False,
) -> tuple[Any, float]:
    """
    Load one fused unit-cell OCP solid.

    Default: read existing 1-volume seed STEP (no octant re-build).
    ``rebuild_from_geometry=True``: only when seed STEP is missing / debug.
    """
    seed_step = os.path.abspath(seed_step)
    if not rebuild_from_geometry and os.path.isfile(seed_step):
        shape = ocp_read_step_shape(seed_step)
        return shape, ocp_mass(shape)

    print(
        f"  [WARN] Rebuilding unit cell from pipe geometry "
        f"(seed missing or rebuild_from_geometry=True)",
        flush=True,
    )
    pipe_parts = load_q1_pipe_parts(cell_size=float(cell_size))
    return _build_ocp_unitcell_at_offset(
        pipe_parts,
        (0.0, 0.0, 0.0),
        cell_size=float(cell_size),
        cell_strategy=cell_strategy,
        fuzzy_mm=fuzzy_mm,
    )


def place_ocp_unitcell_grid(
    seed_shape: Any,
    offsets: list[tuple[float, float, float]],
    *,
    cell_size: float = 20.0,
    clip_to_periodic_box: bool = True,
) -> list[Any]:
    """Place one unit-cell solid at each lattice offset (copy + translate only)."""
    shapes: list[Any] = []
    cell_l = float(cell_size)
    for idx, (dx, dy, dz) in enumerate(offsets):
        if idx == 0 and abs(dx) < 1e-12 and abs(dy) < 1e-12 and abs(dz) < 1e-12:
            placed = seed_shape
        else:
            placed = ocp_translate_shape(seed_shape, dx, dy, dz)
        if clip_to_periodic_box:
            placed = ocp_clip_to_periodic_cell(placed, (dx, dy, dz), cell_l)
        shapes.append(placed)
    return shapes


def build_ocp_adjacent_unit_cells(
    seed_step: str,
    *,
    cell_size: float = 20.0,
    axis: str = "x",
    rebuild_from_geometry: bool = False,
    clip_to_periodic_box: bool = True,
) -> tuple[Any, Any, float]:
    """Two adjacent cells: load seed once → translate neighbour (no second build)."""
    cell_l = float(cell_size)
    c0, m0 = load_ocp_unitcell_shape(
        seed_step,
        cell_size=cell_l,
        rebuild_from_geometry=rebuild_from_geometry,
    )
    if axis.lower() == "x":
        off = (cell_l, 0.0, 0.0)
    elif axis.lower() == "y":
        off = (0.0, cell_l, 0.0)
    elif axis.lower() == "z":
        off = (0.0, 0.0, cell_l)
    else:
        raise ValueError(f"axis must be x/y/z, got {axis!r}")
    c1 = ocp_translate_shape(c0, *off)
    if clip_to_periodic_box:
        c0 = ocp_clip_to_periodic_cell(c0, (0.0, 0.0, 0.0), cell_l)
        c1 = ocp_clip_to_periodic_cell(c1, off, cell_l)
        m0 = ocp_mass(c0)
    return c0, c1, m0


def probe_ocp_two_cell_fuse(
    seed_step: str,
    *,
    glue: GlueMode = "shift",
    fuzzy_mm: float = 0.05,
    cell_size: float = 20.0,
    axis: str = "x",
    rebuild_from_geometry: bool = False,
) -> dict[str, Any]:
    """Try fusing two adjacent cells: seed load once + translate + Fuse(fuzzy)."""
    c0, c1, cell_mass = build_ocp_adjacent_unit_cells(
        seed_step,
        cell_size=cell_size,
        axis=axis,
        rebuild_from_geometry=rebuild_from_geometry,
    )
    m0 = ocp_mass(c0)
    m1 = ocp_mass(c1)
    expected = m0 + m1
    try:
        fused = ocp_fuse_pair(
            c0,
            c1,
            glue=glue,
            fuzzy_mm=float(fuzzy_mm),
            label=f"2cell-{axis}",
        )
        fused_mass = ocp_mass(fused)
        ratio = fused_mass / expected if expected > 0 else 0.0
        ok = fused_mass >= 0.85 * expected
        return {
            "ok": ok,
            "glue": glue,
            "fuzzy_mm": float(fuzzy_mm),
            "axis": axis,
            "cell_mass_mm3": cell_mass,
            "m0_mm3": m0,
            "m1_mm3": m1,
            "fused_mass_mm3": fused_mass,
            "expected_mm3": expected,
            "mass_ratio": ratio,
            "error": None,
        }
    except Exception as exc:
        return {
            "ok": False,
            "glue": glue,
            "fuzzy_mm": float(fuzzy_mm),
            "axis": axis,
            "cell_mass_mm3": cell_mass,
            "m0_mm3": m0,
            "m1_mm3": m1,
            "fused_mass_mm3": 0.0,
            "expected_mm3": expected,
            "mass_ratio": 0.0,
            "error": str(exc),
        }


def export_ocp_paper_box_zslab_fuse(
    seed_step: str,
    path: str,
    *,
    nx: int = 4,
    ny: int = 4,
    iz: int = 0,
    nz_total: int = 4,
    cell_size: float = 20.0,
    glue: GlueMode = DEFAULT_OCP_GLUE,
    fuzzy_mm: float = DEFAULT_OCP_FUZZY_MM,
    cell_strategy: str = DEFAULT_OCP_CELL_STRATEGY,
    rebuild_from_geometry: bool = False,
    inter_cell_fuse_mode: str = DEFAULT_OCP_INTER_CELL_FUSE_MODE,
    row_glue: GlueMode = DEFAULT_OCP_ROW_GLUE,
    row_fuzzy_mm: float = DEFAULT_OCP_ROW_FUZZY_MM,
    inter_row_glue: GlueMode = DEFAULT_OCP_INTER_ROW_GLUE,
    inter_row_fuzzy_mm: float = DEFAULT_OCP_INTER_ROW_FUZZY_MM,
    build_mode: str = "strut_cell_glue",
    periodic_overlap_mm: float = 0.02,
) -> dict[str, Any]:
    """
    Fuse one nx×ny z-slab: load 1-volume seed → translate grid → row/inter-row fuse.

    The unit cell is **not** re-built per grid site; only copy+translate of the seed
    solid (same idea as gmsh ``_write_translated_unitcell_step_copy``).
    """
    seed_step = os.path.abspath(seed_step)
    path = os.path.abspath(path)
    nx_i, ny_i = int(nx), int(ny)
    iz_i = int(iz)
    cell_l = float(cell_size)
    n_cells = nx_i * ny_i

    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    print(
        f"  OCP z-slab iz={iz_i}: {n_cells} cell(s) "
        f"({nx_i}x{ny_i}, L={cell_l:g} mm, fuse={inter_cell_fuse_mode}, "
        f"row_glue={row_glue}, inter_row_glue={inter_row_glue})...",
        flush=True,
    )
    print(f"  Seed STEP (load once, then translate): {seed_step}", flush=True)

    seed_shape, seed_mass = load_ocp_unitcell_shape(
        seed_step,
        cell_size=cell_l,
        cell_strategy=cell_strategy,
        fuzzy_mm=fuzzy_mm,
        rebuild_from_geometry=rebuild_from_geometry,
    )
    offsets: list[tuple[float, float, float]] = []
    for iy in range(ny_i):
        for ix in range(nx_i):
            offsets.append(
                _lattice_cell_offset_xyz_mm(
                    ix,
                    iy,
                    iz_i,
                    nx=nx_i,
                    ny=ny_i,
                    nz=int(nz_total),
                    cell_size=cell_l,
                    origin_centered=False,
                )
            )
    print(
        f"  OCP place grid: 1 seed solid → {len(offsets)} translate(s)...",
        flush=True,
    )
    cell_shapes = place_ocp_unitcell_grid(
        seed_shape,
        offsets,
        cell_size=cell_l,
        clip_to_periodic_box=True,
    )

    cell_mass = ocp_mass(cell_shapes[0])
    print(
        f"  OCP unit-cell mass seed={seed_mass:.1f} clipped={cell_mass:.1f} mm³",
        flush=True,
    )

    fused = _ocp_fuse_zslab_cells(
        cell_shapes,
        nx=nx_i,
        ny=ny_i,
        iz=iz_i,
        seed_mass=cell_mass,
        fuse_mode=inter_cell_fuse_mode,
        row_glue=row_glue,
        row_fuzzy_mm=row_fuzzy_mm,
        inter_row_glue=inter_row_glue,
        inter_row_fuzzy_mm=inter_row_fuzzy_mm,
    )

    fused_mass = ocp_mass(fused)
    expected_mass = cell_mass * n_cells
    if fused_mass < 0.85 * expected_mass:
        raise RuntimeError(
            f"OCP z-slab iz={iz_i} mass {fused_mass:.1f} mm³ "
            f"< 85% of expected {expected_mass:.1f} mm³"
        )

    step_report = _ocp_write_fused_step(fused, path)
    readback = ocp_readback_step(path)
    expected_xy = cell_l * nx_i
    expected_z = cell_l  # one z-slab thickness
    return {
        "step_path": path,
        "seed_step": seed_step,
        "iz": iz_i,
        "cell_count": n_cells,
        "fused_volume_count": int(step_report.get("solid_count", 0)),
        "step_product_count": step_report.get("product_count"),
        "step_solidworks_safe": step_report.get("solidworks_safe"),
        "merged_mass_mm3": fused_mass,
        "expected_mass_mm3": expected_mass,
        "bbox_mm": {
            "x": [0.0, expected_xy],
            "y": [0.0, expected_xy],
            "z": [float(iz_i) * cell_l, float(iz_i) * cell_l + expected_z],
        },
        "method": "ocp_paper_box_zslab_seed_translate_fuse",
        "glue": glue,
        "fuzzy_mm": float(fuzzy_mm),
        "readback": readback,
    }


def export_ocp_paper_box_array_from_zslabs(
    zslab_steps: list[str],
    path: str,
    *,
    glue: GlueMode = DEFAULT_OCP_INTER_ROW_GLUE,
    fuzzy_mm: float = DEFAULT_OCP_INTER_ROW_FUZZY_MM,
    progress_label: str = "ocp-inter-slab",
    fuse_mode: str = DEFAULT_OCP_INTER_CELL_FUSE_MODE,
    skip_gmsh_heal: bool = False,
) -> dict[str, Any]:
    """Merge fused z-slab STEPs → one array solid (GlueShift batch or sequential)."""
    zslab_steps = [os.path.abspath(p) for p in zslab_steps]
    path = os.path.abspath(path)
    for p in zslab_steps:
        if not os.path.isfile(p):
            raise FileNotFoundError(f"Missing z-slab STEP: {p}")

    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    print(
        f"  OCP inter-slab merge: {len(zslab_steps)} slab(s)...",
        flush=True,
    )
    shapes = [ocp_read_step_shape(p) for p in zslab_steps]
    slab_masses = [ocp_mass(s) for s in shapes]
    ref = sum(slab_masses) / max(1, len(slab_masses))

    fuser = (
        _ocp_fuse_group_batch
        if fuse_mode == "hierarchical_batch"
        else _ocp_fuse_group_sequential
    )
    fused = fuser(
        shapes,
        glue=glue,
        fuzzy_mm=fuzzy_mm,
        label=progress_label,
        ref_mass_per_piece=ref,
    )
    fused_mass = ocp_mass(fused)
    expected = sum(slab_masses)
    if fused_mass < 0.85 * expected:
        raise RuntimeError(
            f"OCP array merge mass {fused_mass:.1f} < 85% of {expected:.1f} mm³"
        )

    step_report = _ocp_write_fused_step(fused, path, skip_gmsh_heal=skip_gmsh_heal)
    return {
        "step_path": path,
        "zslab_inputs": zslab_steps,
        "fused_volume_count": int(step_report.get("solid_count", 0)),
        "step_product_count": step_report.get("product_count"),
        "step_solidworks_safe": step_report.get("solidworks_safe"),
        "merged_mass_mm3": fused_mass,
        "method": "ocp_paper_box_zslab_merge",
        "glue": glue,
    }


def export_ocp_paper_box_array_ladder_from_zslabs(
    zslab_steps: list[str],
    path: str,
    *,
    glue: GlueMode = DEFAULT_OCP_INTER_ROW_GLUE,
    fuzzy_mm: float = DEFAULT_OCP_INTER_ROW_FUZZY_MM,
    progress_label: str = "ocp-inter-slab-ladder",
    skip_gmsh_heal: bool = True,
) -> dict[str, Any]:
    """Merge z-slabs as (iz0+iz1) + (iz2+iz3), then fuse the two halves."""
    zslab_steps = [os.path.abspath(p) for p in zslab_steps]
    path = os.path.abspath(path)
    if len(zslab_steps) != 4:
        raise ValueError("ladder merge expects exactly 4 z-slabs")
    for p in zslab_steps:
        if not os.path.isfile(p):
            raise FileNotFoundError(f"Missing z-slab STEP: {p}")

    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    print(f"  OCP ladder inter-slab merge: 2+2 -> 1...", flush=True)
    shapes = [ocp_read_step_shape(p) for p in zslab_steps]
    slab_masses = [ocp_mass(s) for s in shapes]
    ref = sum(slab_masses) / max(1, len(slab_masses))

    half01 = _ocp_fuse_group_sequential(
        shapes[0:2],
        glue=glue,
        fuzzy_mm=fuzzy_mm,
        label=f"{progress_label}-half01",
        ref_mass_per_piece=ref,
    )
    half23 = _ocp_fuse_group_sequential(
        shapes[2:4],
        glue=glue,
        fuzzy_mm=fuzzy_mm,
        label=f"{progress_label}-half23",
        ref_mass_per_piece=ref,
    )
    fused = _ocp_fuse_group_sequential(
        [half01, half23],
        glue=glue,
        fuzzy_mm=fuzzy_mm,
        label=f"{progress_label}-final",
        ref_mass_per_piece=ref * 2.0,
    )
    fused_mass = ocp_mass(fused)
    expected = sum(slab_masses)
    if fused_mass < 0.85 * expected:
        raise RuntimeError(
            f"OCP ladder merge mass {fused_mass:.1f} < 85% of {expected:.1f} mm³"
        )

    step_report = _ocp_write_fused_step(fused, path, skip_gmsh_heal=skip_gmsh_heal)
    return {
        "step_path": path,
        "zslab_inputs": zslab_steps,
        "fused_volume_count": int(step_report.get("solid_count", 0)),
        "step_product_count": step_report.get("product_count"),
        "step_solidworks_safe": step_report.get("solidworks_safe"),
        "merged_mass_mm3": fused_mass,
        "method": "ocp_paper_box_zslab_ladder_merge",
        "glue": glue,
    }


def export_ocp_paper_box_layered_array_fuse(
    seed_step: str,
    array_step: str,
    *,
    nx: int = 4,
    ny: int = 4,
    nz: int = 4,
    cell_size: float = 20.0,
    zslab_paths: list[str] | None = None,
    force: bool = False,
    glue: GlueMode = DEFAULT_OCP_GLUE,
    fuzzy_mm: float = DEFAULT_OCP_FUZZY_MM,
) -> dict[str, Any]:
    """
    Layered 4×4×4: OCP fuse iz=0 → copy iz=1..3 → OCP merge z-slabs.

    Same stage order as ``export_paper_box_layered_array_fuse`` (gmsh route).
    """
    n = int(nx)
    if int(ny) != n or int(nz) != n:
        raise ValueError("layered array fuse expects cubic nx=ny=nz")
    cell_l = float(cell_size)
    array_step = os.path.abspath(array_step)
    out_dir = os.path.dirname(array_step) or "."
    os.makedirs(out_dir, exist_ok=True)

    if zslab_paths is None:
        zslab_paths = [
            os.path.join(out_dir, f"zslab_iz{iz}_{n}x{n}_paper_box_fused.step")
            for iz in range(n)
        ]

    manifest: dict[str, Any] = {
        "method": "ocp_paper_box_layered_fuse",
        "seed_step": os.path.abspath(seed_step),
        "array_step": array_step,
        "cells": [n, n, n],
        "glue": glue,
        "fuzzy_mm": float(fuzzy_mm),
        "zslabs": [],
        "array_merge": None,
    }

    iz0_path = zslab_paths[0]
    if force or not os.path.isfile(iz0_path):
        print(f"\n=== OCP layered fuse iz=0 ({n}x{n}) ===", flush=True)
        print(f"  Seed: {seed_step}", flush=True)
        print(f"  Out:  {iz0_path}", flush=True)
        iz0_report = export_ocp_paper_box_zslab_fuse(
            seed_step,
            iz0_path,
            nx=n,
            ny=n,
            iz=0,
            nz_total=n,
            cell_size=cell_l,
            glue=glue,
            fuzzy_mm=fuzzy_mm,
        )
        manifest["zslabs"].append(iz0_report)
    else:
        print(f"  [skip] iz=0 exists -> {iz0_path}", flush=True)
        manifest["zslabs"].append({"step_path": iz0_path, "iz": 0, "skipped": True})

    copy_paths = zslab_paths[1:]
    if copy_paths:
        to_copy = [
            (iz, path)
            for iz, path in enumerate(zslab_paths[1:], start=1)
            if force or not os.path.isfile(path)
        ]
        if to_copy:
            print(
                f"\n=== Copy fused iz=0 -> iz=1..{n - 1} (dz={cell_l} mm) ===",
                flush=True,
            )
            for iz, path in to_copy:
                reports = export_paper_box_zslab_copies(
                    iz0_path,
                    [path],
                    cell_size=cell_l,
                    start_iz=iz,
                )
                manifest["zslabs"].append(reports[0])
        else:
            for iz, path in enumerate(zslab_paths[1:], start=1):
                print(f"  [skip] iz={iz} exists -> {path}", flush=True)

    missing = [p for p in zslab_paths if not os.path.isfile(p)]
    if missing:
        raise FileNotFoundError(
            "Missing z-slab STEP(s) before merge:\n  " + "\n  ".join(missing)
        )

    print(f"\n=== OCP merge {n} z-slabs -> array ===", flush=True)
    for iz, path in enumerate(zslab_paths):
        print(f"  input iz={iz}: {path}", flush=True)
    print(f"  Out: {array_step}", flush=True)
    merge_report = export_ocp_paper_box_array_from_zslabs(
        zslab_paths,
        array_step,
        glue=glue,
        fuzzy_mm=fuzzy_mm,
        progress_label="ocp-paper-box-inter-slab",
    )
    manifest["array_merge"] = merge_report
    if int(merge_report.get("fused_volume_count") or 0) != 1:
        raise RuntimeError(
            f"Array merge produced {merge_report.get('fused_volume_count')} volume(s), "
            "expected 1."
        )
    return manifest


def resolve_paper_box_seed(q: float, seed: str = "") -> str:
    """Prefer explicit seed; else OCP Q1 seed; else gmsh paper_box seed."""
    if seed.strip():
        return os.path.abspath(seed.strip())
    ocp = ocp_default_q1_seed_step()
    if os.path.isfile(ocp):
        return ocp
    return paper_box_seed_step(q)
