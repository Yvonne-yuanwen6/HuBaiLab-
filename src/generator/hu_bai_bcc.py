"""
Hu & Bai 2024 — BCC / SFBLS lattice generator (Chongqing University thesis).

Unit cell: body-centered cubic with eight struts from cell centre to cube corners.
The block is **origin-centred**: unit-cell centre at (0,0,0), corners at (±L/2, ±L/2, ±L/2),
and an nx×ny×nz array is mirrored about the global origin.

SFBLS replaces straight struts with sinusoidal buckling rods (Eq. 2.1):

    f(s) = A_f * sin(2 * pi * Q * s),   s in [0, 1] along the strut chord

Buckling displacement uses a fixed global axis (default +Z) projected ⊥ to each strut.
The sign is chosen so every half-rod bulges **outward** toward its corner octant (paper Fig.).

Q = 0  → classic straight-rod BCC (SFBLS-AF2Q0).
Paper block: 4×4×4 cells, L = 20 mm, rod diameter d = 2 mm, A_f = 2 mm.
"""

from __future__ import annotations

import math

import numpy as np

_DEFAULT_BUCKLING_REF = np.array([0.0, 0.0, 1.0])


def _bulge_direction_global(
    e_t: np.ndarray,
    global_ref: np.ndarray = _DEFAULT_BUCKLING_REF,
) -> np.ndarray:
    """Fallback: global axis projected ⊥ to strut."""
    refs = [np.asarray(global_ref, dtype=float), np.array([0.0, 1.0, 0.0]), np.array([1.0, 0.0, 0.0])]
    for g in refs:
        n = g - float(np.dot(g, e_t)) * e_t
        n_norm = float(np.linalg.norm(n))
        if n_norm >= 1e-12:
            return n / n_norm
    return np.array([0.0, 1.0, 0.0])


def _bulge_direction_outward(
    p_centre: np.ndarray,
    p_corner: np.ndarray,
    global_ref: np.ndarray = _DEFAULT_BUCKLING_REF,
) -> np.ndarray:
    """
    Outward-convex half-rod (paper SFBLS): global axis projected ⊥ to strut.

    Same buckling plane for all struts; sign flips per corner octant so each rod
    bows away from the cell centre toward its corner (not inward / crossed pairs).
    """
    chord = np.asarray(p_corner, dtype=float) - np.asarray(p_centre, dtype=float)
    length = float(np.linalg.norm(chord))
    if length < 1e-12:
        return _bulge_direction_global(chord, global_ref)

    e_t = chord / length
    refs = [np.asarray(global_ref, dtype=float), np.array([0.0, 1.0, 0.0]), np.array([1.0, 0.0, 0.0])]
    n: np.ndarray | None = None
    for g in refs:
        proj = g - float(np.dot(g, e_t)) * e_t
        n_norm = float(np.linalg.norm(proj))
        if n_norm >= 1e-12:
            n = proj / n_norm
            break
    if n is None:
        return np.array([0.0, 1.0, 0.0])

    octant = np.sign(chord)
    octant[octant == 0.0] = 1.0
    if float(np.dot(n, octant)) < 0.0:
        n = -n
    return n


def sinusoidal_path_points(
    p0: np.ndarray | list[float],
    p1: np.ndarray | list[float],
    *,
    amplitude: float,
    period_factor: float,
    n_segments: int = 12,
    bulge_direction: np.ndarray | None = None,
    buckling_ref: np.ndarray | None = None,
) -> list[np.ndarray]:
    """
    Sample a centre-to-corner strut between p0 and p1 (paper Eq. 2.1).

    P(s) = p0 + s*(p1-p0) + A_f*sin(2*pi*Q*s)*n_hat,  s in [0, 1].
    Q=0 or A_f=0 → straight chord (two endpoints only).
    """
    p0a = np.asarray(p0, dtype=float)
    p1a = np.asarray(p1, dtype=float)
    chord = p1a - p0a
    length = float(np.linalg.norm(chord))
    if length < 1e-12:
        return [p0a.copy(), p1a.copy()]

    q = float(period_factor)
    af = float(amplitude)
    if abs(q) < 1e-12 or abs(af) < 1e-12:
        return [p0a.copy(), p1a.copy()]

    e_t = chord / length
    ref = _DEFAULT_BUCKLING_REF if buckling_ref is None else np.asarray(buckling_ref, dtype=float)
    n_hat = (
        np.asarray(bulge_direction, dtype=float)
        if bulge_direction is not None
        else _bulge_direction_outward(p0a, p1a, ref)
    )
    n_hat = n_hat - float(np.dot(n_hat, e_t)) * e_t
    n_norm = float(np.linalg.norm(n_hat))
    if n_norm < 1e-12:
        n_hat = _bulge_direction_outward(p0a, p1a, ref)
    else:
        n_hat /= n_norm

    points: list[np.ndarray] = []
    for i in range(n_segments + 1):
        s = i / n_segments
        w = af * math.sin(2.0 * math.pi * q * s)
        points.append(p0a + s * chord + w * n_hat)
    points[0] = p0a.copy()
    points[-1] = p1a.copy()
    return points


class HuBaiLatticeGenerator:
    """BCC / SFBLS lattice (Hu & Bai 2024), origin-centred about (0,0,0)."""

    def __init__(
        self,
        *,
        cell_size: float = 20.0,
        rod_diameter: float = 2.0,
        amplitude: float = 2.0,
        period_factor: float = 0.0,
        n_segments: int = 16,
        buckling_ref: tuple[float, float, float] = (0.0, 0.0, 1.0),
    ) -> None:
        self.L = float(cell_size)
        self.rod_diameter = float(rod_diameter)
        self.r_strut = 0.5 * self.rod_diameter
        self.amplitude = float(amplitude)
        self.period_factor = float(period_factor)
        self.n_segments = max(4, int(n_segments))
        self.buckling_ref = np.asarray(buckling_ref, dtype=float)
        self.height_ratio = 0.0

        self.nodes: list[list[float | int]] = []
        self.beams: list[list[float | int | str]] = []
        self.polylines: list[dict] = []
        self.node_map: dict[tuple[float, float, float], int] = {}
        self.node_id = 1
        self.beam_id = 1

    @property
    def variant_name(self) -> str:
        af = int(round(self.amplitude))
        q_tag = str(self.period_factor).replace(".", "p")
        if abs(self.period_factor - round(self.period_factor)) < 1e-9:
            q_tag = str(int(round(self.period_factor)))
        if abs(self.period_factor) < 1e-9:
            return f"BCC_AF{af}Q0"
        return f"SFBLS_AF{af}Q{q_tag}"

    def add_node(self, x: float, y: float, z: float) -> int:
        key = tuple(np.round([x, y, z], 6))
        if key not in self.node_map:
            self.node_map[key] = self.node_id
            self.nodes.append([self.node_id, float(x), float(y), float(z)])
            self.node_id += 1
        return self.node_map[key]

    def add_beam(self, n1: int, n2: int, radius: float, beam_type: str) -> None:
        self.beams.append([self.beam_id, int(n1), int(n2), float(radius), str(beam_type)])
        self.beam_id += 1

    def add_polyline_beam(
        self,
        points: list[np.ndarray],
        radius: float,
        beam_type: str,
    ) -> None:
        if len(points) < 2:
            return
        node_ids = [self.add_node(float(p[0]), float(p[1]), float(p[2])) for p in points]
        self.polylines.append(
            {
                "id": self.beam_id,
                "nodes": node_ids,
                "radius": float(radius),
                "type": str(beam_type),
            }
        )
        self.beam_id += 1

    def cell_center_mm(self, index: int, count: int) -> float:
        return (index - (count - 1) / 2.0) * self.L

    def lattice_bounds_mm(self, nx: int, ny: int, nz: int) -> tuple[float, float, float, float, float, float]:
        """Axis-aligned bounds (xmin, xmax, ymin, ymax, zmin, zmax) for origin-centred block."""
        half = 0.5 * self.L
        ex = nx * self.L
        ey = ny * self.L
        ez = nz * self.L
        return (-0.5 * ex, 0.5 * ex, -0.5 * ey, 0.5 * ey, -0.5 * ez, 0.5 * ez)

    def _corner_offsets_half(self) -> list[tuple[float, float, float]]:
        h = 0.5 * self.L
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

    def _strut_beam_type(self) -> str:
        if abs(self.period_factor) < 1e-12 or abs(self.amplitude) < 1e-12:
            return "bcc"
        return "sfbls"

    def _add_strut(self, p_centre: np.ndarray, p_corner: np.ndarray) -> None:
        """Centre-to-corner strut via Eq. 2.1; Q=0 gives a straight chord."""
        pts = sinusoidal_path_points(
            p_centre,
            p_corner,
            amplitude=self.amplitude,
            period_factor=self.period_factor,
            n_segments=self.n_segments,
            buckling_ref=self.buckling_ref,
        )
        self.add_polyline_beam(pts, self.r_strut, self._strut_beam_type())

    def create_unitcell_at_center(self, cx: float, cy: float, cz: float) -> None:
        p_centre = np.array([cx, cy, cz], dtype=float)

        for dx, dy, dz in self._corner_offsets_half():
            p_corner = np.array([cx + dx, cy + dy, cz + dz], dtype=float)
            self._add_strut(p_centre, p_corner)

    def build_lattice(self, nx: int, ny: int, nz: int) -> None:
        self.nodes.clear()
        self.beams.clear()
        self.polylines.clear()
        self.node_map.clear()
        self.node_id = 1
        self.beam_id = 1

        for ix in range(int(nx)):
            for iy in range(int(ny)):
                for iz in range(int(nz)):
                    self._add_unitcell_at_indices(ix, iy, iz, int(nx), int(ny), int(nz))

    def build_lattice_z_layer(
        self,
        nx: int,
        ny: int,
        nz_total: int,
        iz: int,
    ) -> None:
        """
        One z-slab (fixed ``iz``) of an ``nx×ny×nz_total`` origin-centred block.

        Cell centres match ``build_lattice(nx, ny, nz_total)`` so layer slabs
        align for hierarchical OCC fuse (e.g. 4×4×1 slabs → 4×4×4).
        """
        self.nodes.clear()
        self.beams.clear()
        self.polylines.clear()
        self.node_map.clear()
        self.node_id = 1
        self.beam_id = 1

        iz_i = int(iz)
        nz_i = int(nz_total)
        if iz_i < 0 or iz_i >= nz_i:
            raise ValueError(f"iz={iz_i} out of range for nz_total={nz_i}")

        nx_i, ny_i = int(nx), int(ny)
        for ix in range(nx_i):
            for iy in range(ny_i):
                self._add_unitcell_at_indices(ix, iy, iz_i, nx_i, ny_i, nz_i)

    def _add_unitcell_at_indices(
        self,
        ix: int,
        iy: int,
        iz: int,
        nx: int,
        ny: int,
        nz: int,
    ) -> None:
        cx = self.cell_center_mm(ix, nx)
        cy = self.cell_center_mm(iy, ny)
        cz = self.cell_center_mm(iz, nz)
        self.create_unitcell_at_center(cx, cy, cz)

    def build_unitcell(self) -> None:
        self.build_lattice(1, 1, 1)

    def footprint_mm(self) -> tuple[float, float, float]:
        return self.L, self.L, self.L

    def lattice_extent_mm(self, nx: int, ny: int, nz: int) -> tuple[float, float, float]:
        return nx * self.L, ny * self.L, nz * self.L

    def get_data(self, *, copy: bool = False) -> tuple[list, list, list]:
        """Return lattice data. Pass ``copy=True`` to snapshot (safe across rebuilds)."""
        if not copy:
            return self.nodes, self.beams, self.polylines
        import copy as _copy

        nodes = [list(n) for n in self.nodes]
        beams = [list(b) for b in self.beams]
        polylines = _copy.deepcopy(self.polylines)
        return nodes, beams, polylines

    def resolved_support_vertical_angle_deg(self) -> float:
        return 0.0

    def resolved_edge_z_frac(self) -> float:
        return 0.5
