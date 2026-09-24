"""Design-domain solids for trimmed lattice fill (square−cylinder and STEP).

Keep interior unit cells undistorted: Cartesian cell map + gate + Common(Ω).
"""

from __future__ import annotations

import os
from typing import Any, Literal, Sequence

from src.export.ocp_unitcell_fuse import (
    _box_from_bounds,
    _require_ocp,
    ocp_common,
    ocp_cut,
    ocp_mass,
)

GateMode = Literal["intersect", "full_only"]

# Volume fraction of L³ box retained inside Ω to count as "fully inside".
FULL_ONLY_MASS_RATIO = 0.99
# Minimum Common(box, Ω) / L³ to count as intersecting.
INTERSECT_MASS_RATIO = 1e-4


def make_square_prism(
    side_mm: float,
    height_mm: float,
    *,
    center_xy: tuple[float, float] = (0.0, 0.0),
    z_center: float = 0.0,
) -> Any:
    """Axis-aligned square prism centred on (cx, cy, z_center)."""
    s = float(side_mm)
    h = float(height_mm)
    if s <= 0.0 or h <= 0.0:
        raise ValueError(f"side and height must be > 0, got S={side_mm}, H={height_mm}")
    cx, cy = float(center_xy[0]), float(center_xy[1])
    hz = 0.5 * h
    hs = 0.5 * s
    z0 = float(z_center)
    return _box_from_bounds(
        (cx - hs, cx + hs, cy - hs, cy + hs, z0 - hz, z0 + hz)
    )


def make_cylinder_z_extent(
    radius_mm: float,
    height_mm: float,
    *,
    overshoot_mm: float = 0.1,
    center_xy: tuple[float, float] = (0.0, 0.0),
    z_center: float = 0.0,
) -> Any:
    """
    Solid cylinder along +Z (no ``2R < L`` constraint; for design domains).

    Extends slightly past ±H/2 so boolean cuts clear the prism faces.
    """
    r = float(radius_mm)
    h = float(height_mm)
    if r <= 0.0 or h <= 0.0:
        raise ValueError(f"radius and height must be > 0, got R={radius_mm}, H={height_mm}")
    eps = max(0.0, float(overshoot_mm))
    height = h + 2.0 * eps
    z0 = float(z_center) - 0.5 * h - eps
    cx, cy = float(center_xy[0]), float(center_xy[1])
    ocp = _require_ocp()
    ax = ocp["gp_Ax2"](
        ocp["gp_Pnt"](cx, cy, z0),
        ocp["gp_Dir"](0.0, 0.0, 1.0),
    )
    return ocp["BRepPrimAPI_MakeCylinder"](ax, r, height).Shape()


def make_square_minus_cylinder_domain(
    *,
    side_mm: float,
    height_mm: float,
    hole_radius_mm: float,
    center_xy: tuple[float, float] = (0.0, 0.0),
    z_center: float = 0.0,
    overshoot_mm: float = 0.1,
) -> tuple[Any, dict[str, Any]]:
    """
    Ω = square prism − coaxial cylinder (outer square, inner round hole).

    Returns ``(domain_shape, meta)``.
    """
    s = float(side_mm)
    r = float(hole_radius_mm)
    if 2.0 * r >= s:
        raise ValueError(
            f"hole diameter 2*R={2.0 * r:g} must be < outer side S={s:g}"
        )
    outer = make_square_prism(
        s, float(height_mm), center_xy=center_xy, z_center=z_center
    )
    hole = make_cylinder_z_extent(
        r,
        float(height_mm),
        overshoot_mm=overshoot_mm,
        center_xy=center_xy,
        z_center=z_center,
    )
    domain = ocp_cut(outer, hole, label="square_minus_cylinder")
    meta = {
        "kind": "square_minus_cylinder",
        "side_mm": s,
        "height_mm": float(height_mm),
        "hole_radius_mm": r,
        "center_xy": (float(center_xy[0]), float(center_xy[1])),
        "z_center": float(z_center),
        "mass_mm3": ocp_mass(domain),
    }
    return domain, meta


def validate_frame_skin_clearance(
    *,
    side_mm: float,
    hole_radius_mm: float,
    skin_mm: float | None = None,
    inner_wall_mm: float | None = None,
    outer_wall_mm: float | None = None,
) -> None:
    """Skins must not collide: R+t_inner < S/2 − t_outer."""
    s = float(side_mm)
    r = float(hole_radius_mm)
    t_in = float(inner_wall_mm if inner_wall_mm is not None else skin_mm)
    t_out = float(outer_wall_mm if outer_wall_mm is not None else skin_mm)
    if t_in <= 0.0:
        raise ValueError(f"inner_wall_mm must be > 0, got {t_in}")
    if t_out <= 0.0:
        raise ValueError(f"outer_wall_mm must be > 0, got {t_out}")
    inner_outer = r + t_in
    outer_inner = 0.5 * s - t_out
    if inner_outer >= outer_inner:
        raise ValueError(
            f"skins collide: R+t_inner={inner_outer:g} mm >= S/2−t_outer={outer_inner:g} mm "
            f"(S={s:g}, R={r:g}, t_inner={t_in:g}, t_outer={t_out:g})"
        )


def make_inner_cylinder_liner(
    *,
    hole_radius_mm: float,
    skin_mm: float,
    height_mm: float,
    side_mm: float,
    center_xy: tuple[float, float] = (0.0, 0.0),
    z_center: float = 0.0,
    overshoot_mm: float = 0.1,
) -> Any:
    """
    Hollow cylinder lining the hole: inner radius R, outer R+t, height H.

    Intersected with the outer square so the liner cannot leave the frame.
    """
    r = float(hole_radius_mm)
    t = float(skin_mm)
    outer_cyl = make_cylinder_z_extent(
        r + t,
        float(height_mm),
        overshoot_mm=overshoot_mm,
        center_xy=center_xy,
        z_center=z_center,
    )
    inner_cyl = make_cylinder_z_extent(
        r,
        float(height_mm),
        overshoot_mm=overshoot_mm,
        center_xy=center_xy,
        z_center=z_center,
    )
    liner = ocp_cut(outer_cyl, inner_cyl, label="inner_cylinder_liner")
    prism = make_square_prism(
        float(side_mm),
        float(height_mm),
        center_xy=center_xy,
        z_center=z_center,
    )
    clipped = ocp_common(liner, prism)
    if ocp_mass(clipped) <= 0.0:
        raise RuntimeError("inner cylinder liner empty after square clip")
    return clipped


def make_outer_square_frame(
    *,
    side_mm: float,
    skin_mm: float,
    height_mm: float,
    center_xy: tuple[float, float] = (0.0, 0.0),
    z_center: float = 0.0,
) -> Any:
    """Picture-frame wall: outer square S minus inner square S−2t."""
    s = float(side_mm)
    t = float(skin_mm)
    inner_side = s - 2.0 * t
    if inner_side <= 0.0:
        raise ValueError(f"skin too thick for outer frame: S={s:g}, t={t:g}")
    outer = make_square_prism(
        s, float(height_mm), center_xy=center_xy, z_center=z_center
    )
    inner = make_square_prism(
        inner_side, float(height_mm), center_xy=center_xy, z_center=z_center
    )
    return ocp_cut(outer, inner, label="outer_square_frame")


def make_frame_skins(
    *,
    side_mm: float,
    height_mm: float,
    hole_radius_mm: float,
    skin_mm: float | None = None,
    inner_wall_mm: float | None = None,
    outer_wall_mm: float | None = None,
    center_xy: tuple[float, float] = (0.0, 0.0),
    z_center: float = 0.0,
) -> tuple[Any, Any, dict[str, Any]]:
    """Return ``(inner_liner, outer_frame, meta)``.

    Wall thicknesses: prefer ``inner_wall_mm`` / ``outer_wall_mm``;
    if omitted, both fall back to ``skin_mm``.
    """
    if skin_mm is None and (inner_wall_mm is None or outer_wall_mm is None):
        raise ValueError("provide skin_mm, or both inner_wall_mm and outer_wall_mm")
    t_in = float(inner_wall_mm if inner_wall_mm is not None else skin_mm)
    t_out = float(outer_wall_mm if outer_wall_mm is not None else skin_mm)
    validate_frame_skin_clearance(
        side_mm=side_mm,
        hole_radius_mm=hole_radius_mm,
        inner_wall_mm=t_in,
        outer_wall_mm=t_out,
    )
    inner = make_inner_cylinder_liner(
        hole_radius_mm=hole_radius_mm,
        skin_mm=t_in,
        height_mm=height_mm,
        side_mm=side_mm,
        center_xy=center_xy,
        z_center=z_center,
    )
    outer = make_outer_square_frame(
        side_mm=side_mm,
        skin_mm=t_out,
        height_mm=height_mm,
        center_xy=center_xy,
        z_center=z_center,
    )
    meta = {
        "skin_mm": float(skin_mm) if skin_mm is not None else None,
        "inner_wall_mm": t_in,
        "outer_wall_mm": t_out,
        "inner_liner_mass_mm3": ocp_mass(inner),
        "outer_frame_mass_mm3": ocp_mass(outer),
    }
    return inner, outer, meta


def domain_from_step(
    path: str,
    *,
    require_one_solid: bool = True,
) -> tuple[Any, dict[str, Any]]:
    """Load an arbitrary design-domain solid from STEP (future freeform outlines)."""
    from OCP.STEPControl import STEPControl_Reader

    from src.export.ocp_unitcell_fuse import ocp_shape_topology

    path = os.path.abspath(path)
    if not os.path.isfile(path):
        raise FileNotFoundError(path)
    reader = STEPControl_Reader()
    if reader.ReadFile(path) != 1:
        raise RuntimeError(f"STEP read failed: {path}")
    reader.TransferRoots()
    shape = reader.OneShape()
    topo = ocp_shape_topology(shape, count_faces=False, check_brep=True)
    n_solids = int(topo.get("solids") or 0)
    if require_one_solid and n_solids != 1:
        raise RuntimeError(
            f"domain STEP must be 1 solid, got {n_solids}: {path}"
        )
    meta = {
        "kind": "step",
        "step_path": path,
        "mass_mm3": float(topo["mass_mm3"]),
        "solids": n_solids,
        "brep_valid": bool(topo.get("brep_valid")),
    }
    return shape, meta


def cell_box_bounds(
    center_xyz: tuple[float, float, float],
    cell_size_mm: float,
) -> tuple[float, float, float, float, float, float]:
    h = 0.5 * float(cell_size_mm)
    cx, cy, cz = map(float, center_xyz)
    return (cx - h, cx + h, cy - h, cy + h, cz - h, cz + h)


def cell_box_shape(
    center_xyz: tuple[float, float, float],
    cell_size_mm: float,
) -> Any:
    return _box_from_bounds(cell_box_bounds(center_xyz, cell_size_mm))


def cartesian_cell_centers(
    nx: int,
    ny: int,
    nz: int,
    cell_size_mm: float,
    *,
    origin: tuple[float, float, float] = (0.0, 0.0, 0.0),
) -> list[tuple[float, float, float]]:
    """
    Origin-centred integer grid of cell centres with spacing ``L``.

    For nx=4, L=20: centres at x = −30, −10, 10, 30 (same for y/z when n>1).
    """
    if min(int(nx), int(ny), int(nz)) < 1:
        raise ValueError(f"nx,ny,nz must be >= 1, got {nx},{ny},{nz}")
    L = float(cell_size_mm)
    ox, oy, oz = map(float, origin)

    def _axis(n: int, o: float) -> list[float]:
        if n == 1:
            return [o]
        start = o - 0.5 * (n - 1) * L
        return [start + i * L for i in range(n)]

    xs = _axis(int(nx), ox)
    ys = _axis(int(ny), oy)
    zs = _axis(int(nz), oz)
    return [(x, y, z) for z in zs for y in ys for x in xs]


def grid_counts_from_frame(
    *,
    side_mm: float,
    height_mm: float,
    cell_size_mm: float,
    tol_mm: float = 1e-3,
) -> tuple[int, int, int, dict[str, Any]]:
    """
    Derive ``(nx, ny, nz)`` so the Cartesian grid fills the square×height frame.

    Uses ``n = round(length / L)`` with ``n >= 1``. If ``length`` is not an
    integer multiple of ``L`` within ``tol_mm``, the returned meta flags
    ``snapped`` and suggests ``side_mm = nx*L``, ``height_mm = nz*L``.
    """
    L = float(cell_size_mm)
    if L <= 0.0:
        raise ValueError(f"cell_size_mm must be > 0, got {cell_size_mm}")
    s = float(side_mm)
    h = float(height_mm)
    if s <= 0.0 or h <= 0.0:
        raise ValueError(f"side/height must be > 0, got S={side_mm}, H={height_mm}")

    def _n_along(length: float, label: str) -> tuple[int, float, bool]:
        n_ideal = length / L
        n = max(1, int(round(n_ideal)))
        span = n * L
        snapped = abs(span - length) > float(tol_mm)
        if snapped:
            print(
                f"  [WARN] {label}={length:g} is not an integer×L={L:g} "
                f"(ideal n={n_ideal:g}); using n={n} → span={span:g} mm",
                flush=True,
            )
        return n, span, snapped

    nx, span_xy, snap_xy = _n_along(s, "S")
    ny = nx  # square outer → same count in X/Y
    nz, span_z, snap_z = _n_along(h, "H")
    meta = {
        "nx": nx,
        "ny": ny,
        "nz": nz,
        "L_mm": L,
        "side_span_mm": span_xy,
        "height_span_mm": span_z,
        "snapped_xy": snap_xy,
        "snapped_z": snap_z,
        "requested_S_mm": s,
        "requested_H_mm": h,
    }
    return nx, ny, nz, meta


def _safe_common_mass(a: Any, b: Any) -> float:
    try:
        return float(ocp_mass(ocp_common(a, b)))
    except RuntimeError:
        return 0.0


def classify_cell_vs_domain(
    center_xyz: tuple[float, float, float],
    cell_size_mm: float,
    domain: Any,
    *,
    mode: GateMode,
    full_only_ratio: float = FULL_ONLY_MASS_RATIO,
    intersect_ratio: float = INTERSECT_MASS_RATIO,
) -> dict[str, Any]:
    """
    Gate one L³ cell box against domain Ω.

    - ``intersect``: keep if Common(box, Ω) has meaningful volume
    - ``full_only``: keep only if almost the entire L³ box lies in Ω
    """
    L = float(cell_size_mm)
    box_vol = L ** 3
    box = cell_box_shape(center_xyz, L)
    common_mass = _safe_common_mass(box, domain)
    frac = common_mass / box_vol if box_vol > 0.0 else 0.0
    if mode == "intersect":
        keep = frac >= float(intersect_ratio)
    elif mode == "full_only":
        keep = frac >= float(full_only_ratio)
    else:
        raise ValueError(f"unknown gate mode: {mode!r}")
    return {
        "center": (float(center_xyz[0]), float(center_xyz[1]), float(center_xyz[2])),
        "box_volume_mm3": box_vol,
        "common_mass_mm3": common_mass,
        "common_fraction": frac,
        "keep": bool(keep),
        "mode": mode,
    }


def gate_cell_centers(
    centers: Sequence[tuple[float, float, float]],
    cell_size_mm: float,
    domain: Any,
    *,
    mode: GateMode,
) -> tuple[list[tuple[float, float, float]], list[dict[str, Any]]]:
    """Return (kept_centers, per-cell reports)."""
    kept: list[tuple[float, float, float]] = []
    reports: list[dict[str, Any]] = []
    for c in centers:
        rep = classify_cell_vs_domain(c, cell_size_mm, domain, mode=mode)
        reports.append(rep)
        if rep["keep"]:
            kept.append(rep["center"])
    return kept, reports
