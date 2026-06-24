"""Abaqus compression BC: rigid plate, fixed end, displacement + hard contact."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, TextIO

import numpy as np
import re

# Hu & Bai (2024) §2.4 — quasi-static compression (Fig. 2.6 / 3.3)
HU_BAI_LOAD_RATE_MM_MIN = 5.0
HU_BAI_TARGET_ENGINEERING_STRAIN = 0.70
HU_BAI_FRICTION = 0.1
HU_BAI_EXPLICIT_DT = 1.0e-4
HU_BAI_EXPLICIT_MASS_SCALING = 50.0
HU_BAI_AMPLITUDE_HOLD_FRACTION = 0.05
# TPU matrix (§2.3.2 tensile / §2.4.1 simulation): E=25 MPa, nu=0.47, rho=1.135 g/cm³
HU_BAI_E_MODULUS_MPA = 25.0
HU_BAI_POISSON = 0.47
HU_BAI_YIELD_MPA = 4.69
HU_BAI_DENSITY_KG_M3 = 1135.0
HU_BAI_MESH_MM = 0.6


def hu_bai_neo_hooke_c10(e_mpa: float = HU_BAI_E_MODULUS_MPA, nu: float = HU_BAI_POISSON) -> float:
    """Neo-Hooke C10 from small-strain modulus (soft TPU: E ≈ 6·C10 when nu ≈ 0.5)."""
    _ = nu
    return float(e_mpa) / 6.0


def hu_bai_density_abq(kg_m3: float = HU_BAI_DENSITY_KG_M3) -> float:
    """Abaqus mm–tonne–s density from kg/m³."""
    return float(kg_m3) * 1.0e-12
# Fig.3.3 fast80: 80% strain @ 1.2 mm; 5 mm/min quasi-static, dt=5e-4, hold 5%
HU_BAI_FAST80_TARGET_STRAIN = 0.80
HU_BAI_FAST80_MESH_MM = 1.2
HU_BAI_FAST80_EXPLICIT_DT = 5.0e-4
# Explicit *Restart NUMBER INTERVAL = time-slice count in the step (NOT increment count).
EXPLICIT_RESTART_MAX_NUMBER_INTERVAL = 50
EXPLICIT_RESTART_DEFAULT_NUMBER_INTERVAL = 8
# Fig.2.6 explicit validation only (not 5 mm/min strain rate)
HU_BAI_FIG26_STEP_TIME_S = 0.64


def validate_explicit_restart_inp(text: str) -> None:
    """
    Reject Explicit restart lines that can flood disk.

    Abaqus/Explicit NUMBER INTERVAL is the count of equal time slices in the step
    (n+1 restart states), not an increment stride. Must use OVERLAY to overwrite
    prior restart state instead of retaining every write.
    """
    for line in text.splitlines():
        if not re.match(r"^\*Restart,\s*write", line, re.I):
            continue
        if "overlay" not in line.lower():
            raise ValueError(
                "Unsafe *Restart in INP: missing OVERLAY. "
                "Use: *Restart, write, overlay, number interval=8"
            )
        m = re.search(r"number\s+interval\s*=\s*(\d+)", line, re.I)
        if not m:
            raise ValueError(
                "Unsafe *Restart in INP: missing NUMBER INTERVAL. "
                "Use: *Restart, write, overlay, number interval=8"
            )
        n = int(m.group(1))
        if n < 1 or n > EXPLICIT_RESTART_MAX_NUMBER_INTERVAL:
            raise ValueError(
                f"Unsafe *Restart NUMBER INTERVAL={n}. "
                f"Must be 1..{EXPLICIT_RESTART_MAX_NUMBER_INTERVAL} (time-slice count, not increment count)."
            )
        return


def hu_bai_quasi_static_step_time(
    compression_displacement_mm: float,
    *,
    load_rate_mm_min: float = HU_BAI_LOAD_RATE_MM_MIN,
) -> float:
    """Step duration [s] for constant crosshead rate (paper: 5 mm/min)."""
    rate_mm_s = float(load_rate_mm_min) / 60.0
    if rate_mm_s <= 0.0:
        raise ValueError("load_rate_mm_min must be positive")
    return float(compression_displacement_mm) / rate_mm_s


def hu_bai_compression_displacement(
    nz: int,
    cell_size: float,
    *,
    target_strain: float = HU_BAI_TARGET_ENGINEERING_STRAIN,
) -> float:
    """Prescribed plate stroke [mm] for engineering strain target."""
    return float(target_strain) * float(nz) * float(cell_size)


@dataclass
class CompressionSettings:
    """Compression test setup for lattice + rigid loading plate."""

    nx: int
    ny: int
    nz: int
    cell_size: float
    height_ratio: float

    # top_down: 顶板向下压，底面固定（默认）
    # bottom_up: 底板向上压，顶面固定
    loading_direction: str = "top_down"

    compression_displacement: float = 1.0
    step_time: float = 1.0

    contact_friction: float = 0.0
    contact_slip_tolerance: float = 0.005
    # 1/MPa；过小(如 1e-9)会使体积模量极大、点阵几乎不变形（.dat 有 WARNING）
    tpu_d1: float = 0.05
    # direct_top：顶面节点直接施加 U3（不依赖 Coupling/接触，CAE 导入最稳）
    # coupling_nodes：顶面节点运动学耦合 PLATE_REF（勿用 CAE 改 INP）
    # general / pair / coupling / tie：备用
    contact_mode: str = "direct_top"
    # 点阵实体外表面自接触，防止大变形后内部杆件相互穿模
    lattice_self_contact: bool = True
    tie_position_tolerance: float | None = None
    plate_divisions: tuple[int, int] = (12, 12)
    plate_margin: float | None = None
    plate_thickness: float = 0.05
    # 杆件半径 [mm]，用于板面包络（mesh 节点 + 半径 + margin）
    rod_radius: float | None = None
    # 板接触面与实体包络之间的间隙 [mm]（正值=板在点阵外侧，避免初始穿模）
    plate_standoff: float | None = None
    # 顶板相对点阵实体最高点的初始嵌入量（消除间隙，避免前段无接触、U≈0）
    plate_embed: float | None = None
    bottom_z_tol: float | None = None
    top_fix_z_tol: float | None = None
    # 筛选顶面单元面时，距 mesh Zmax 的带宽（mm）
    top_surface_z_band: float | None = None
    # 顶面加载节点集带宽（mm）；应大于 top_surface_z_band，覆盖整层节点
    top_node_z_band: float | None = None
    # 顶面外表面法向 +Z 分量下限（CAD 起伏顶面需放宽，默认 0.85 仅近水平面）
    top_face_normal_z_min: float | None = None
    # 底面外表面法向 +Z 分量上限（负值，对称放宽）
    bottom_face_normal_z_max: float | None = None
    # bottom_up：底面加载面 / 节点集带宽（mm）
    bottom_surface_z_band: float | None = None
    bottom_node_z_band: float | None = None
    # bottom_up：是否在顶面加固定刚体板（双压板试验，CAE 可视化更直观）
    passive_counter_plate: bool | None = None
    # top_down：底面固定刚体板 + 面接触（Hu & Bai 2024 Fig.2.6）
    fixed_bottom_plate: bool = False

    analysis: str = "explicit"
    step_name: str = "Compression"
    displacement_amplitude_name: str = "COMP-DISP"
    # Explicit 时间增量 [s]：fixed 模式下为恒定 Δt；automatic 模式下为 Δt 上限
    explicit_dt: float = 0.0005
    # fixed = *Dynamic, Explicit, direct user control；automatic = 按稳定步长自适应（可带上限）
    explicit_dt_mode: str = "fixed"
    # 若 explicit_dt 为 None，则用 step_time / explicit_n_increments
    explicit_n_increments: int = 10000
    # 幅值曲线：前段保持 0 再线性加载（占总步长比例，减轻冲击）
    amplitude_hold_fraction: float = 0.4
    # 准静态显式：*Fixed Mass Scaling（None=不写；勿用 *Mass Scaling，CAE 无法识别）
    explicit_mass_scaling_factor: float | None = None
    # True：仅 type=BELOW MIN + dt（与 factor 二选一，更稳）
    explicit_mass_scaling_dt_only: bool = True
    # 顶面全部节点的 History（RF/U）会在 CAE 中产生数千条记录，默认关闭
    history_lattice_top_nodes: bool = False
    # Explicit 断点续算：NUMBER INTERVAL = 步内等分时间间隔数（非增量数！），配合 overlay 避免磁盘暴涨
    explicit_restart_write: bool = True
    explicit_restart_number_interval: int | None = None  # None → 8 份（约每 12.5% 步长）
    # *Bulk Viscosity linear, quadratic — 略增可抑制自接触高频振荡
    bulk_viscosity_linear: float = 0.12
    bulk_viscosity_quadratic: float = 1.6
    contact_init_interference_fit: bool = False
    contact_init_step_fraction: float = 0.15
    # Explicit 自接触软化：SCALE FACTOR 的 s0（general contact；None=HARD）
    contact_soft_clearance_mm: float | None = None
    # Explicit 两步：先 ContactSettle（零位移 + 极软自接触），再 Compression
    explicit_contact_settle: bool = False
    contact_settle_time_fraction: float = 0.15
    contact_settle_soft_s0: float = 0.02
    contact_settle_friction: float = 0.0
    contact_settle_step_name: str = "ContactSettle"
    # Explicit general contact: STORE OFFSETS 替代 t=0 nodal adjustment（避免大过盈推畸变）
    contact_overclosure_store_offsets: bool = False

    def use_explicit_contact_settle(self) -> bool:
        return (
            self.explicit_contact_settle
            and self.analysis.lower() == "explicit"
            and self.lattice_self_contact
        )

    @property
    def top_plane_z(self) -> float:
        h = self.height_ratio * self.cell_size
        return self.nz * self.cell_size + h

    @property
    def compression_velocity(self) -> float:
        if self.step_time <= 0:
            raise ValueError("step_time must be positive")
        return self.compression_displacement / self.step_time

    def resolved_margin(self) -> float:
        return self.plate_margin if self.plate_margin is not None else 0.1 * self.cell_size

    def resolved_rod_radius(self) -> float:
        return float(self.rod_radius) if self.rod_radius is not None else 0.0

    def resolved_plate_standoff(self) -> float:
        if self.plate_standoff is not None:
            return float(self.plate_standoff)
        return max(0.02, 0.005 * self.cell_size)

    def resolved_bottom_tol(self) -> float:
        if self.bottom_z_tol is not None:
            return self.bottom_z_tol
        return max(1e-6, 0.02 * self.cell_size)

    def resolved_plate_embed(self) -> float:
        if self.plate_embed is not None:
            return self.plate_embed
        return max(0.02, 0.01 * self.cell_size)

    def resolved_top_surface_z_band(self) -> float:
        if self.top_surface_z_band is not None:
            return self.top_surface_z_band
        return max(0.35, 0.12 * self.cell_size)

    def resolved_top_node_z_band(self) -> float:
        if self.top_node_z_band is not None:
            return self.top_node_z_band
        # 顶面一整层单胞（mm）
        return max(2.0, self.height_ratio * self.cell_size + 0.15 * self.cell_size)

    def resolved_top_face_normal_z_min(self) -> float:
        if self.top_face_normal_z_min is not None:
            return float(self.top_face_normal_z_min)
        return 0.85

    def resolved_bottom_face_normal_z_max(self) -> float:
        if self.bottom_face_normal_z_max is not None:
            return float(self.bottom_face_normal_z_max)
        return -0.85

    def resolved_tie_position_tolerance(self) -> float:
        if self.tie_position_tolerance is not None:
            return self.tie_position_tolerance
        return max(0.5, 0.05 * self.cell_size)

    def resolved_explicit_dt(self) -> float:
        if self.explicit_dt is not None and self.explicit_dt > 0.0:
            return float(self.explicit_dt)
        n = max(100, int(self.explicit_n_increments))
        return self.step_time / n

    def resolved_explicit_n_increments(self) -> int:
        dt = self.resolved_explicit_dt()
        return max(100, int(round(self.step_time / dt)))

    def resolved_restart_number_interval(self) -> int:
        """Abaqus/Explicit: NUMBER INTERVAL = equally spaced time slices in the step (not increment count)."""
        if self.explicit_restart_number_interval is not None:
            return max(1, min(EXPLICIT_RESTART_MAX_NUMBER_INTERVAL, int(self.explicit_restart_number_interval)))
        return EXPLICIT_RESTART_DEFAULT_NUMBER_INTERVAL

    def is_bottom_up(self) -> bool:
        return self.loading_direction.lower() in ("bottom_up", "up", "from_bottom")

    def use_passive_counter_plate(self) -> bool:
        if self.passive_counter_plate is not None:
            return bool(self.passive_counter_plate)
        return self.is_bottom_up()

    def use_fixed_bottom_plate(self) -> bool:
        return bool(self.fixed_bottom_plate) and not self.is_bottom_up()

    def resolved_fixed_tol(self) -> float:
        """Z-band for fixing the passive end (bottom for top_down, top for bottom_up)."""
        return self.resolved_bottom_tol() if not self.is_bottom_up() else self.resolved_top_fix_tol()

    def resolved_top_fix_tol(self) -> float:
        if self.top_fix_z_tol is not None:
            return self.top_fix_z_tol
        return max(1e-6, 0.02 * self.cell_size)

    def resolved_bottom_surface_z_band(self) -> float:
        if self.bottom_surface_z_band is not None:
            return self.bottom_surface_z_band
        return max(0.35, 0.12 * self.cell_size)

    def resolved_load_surface_z_band(self) -> float:
        """Z-band for collecting load-side element faces."""
        if self.is_bottom_up():
            if self.bottom_surface_z_band is not None:
                return self.bottom_surface_z_band
            return max(0.35, 0.12 * self.cell_size)
        return self.resolved_top_surface_z_band()

    def resolved_load_node_z_band(self) -> float:
        """Z-band for collecting load-side coupling nodes."""
        if self.is_bottom_up():
            if self.bottom_node_z_band is not None:
                return self.bottom_node_z_band
            return max(2.0, self.height_ratio * self.cell_size + 0.15 * self.cell_size)
        return self.resolved_top_node_z_band()

    def signed_compression_displacement(self) -> float:
        """Plate / coupled-node U3 target (negative = down, positive = up)."""
        if self.is_bottom_up():
            return self.compression_displacement
        return -self.compression_displacement


def lattice_bounds(nodes: list) -> tuple[float, float, float, float, float, float]:
    xs = [float(n[1]) for n in nodes]
    ys = [float(n[2]) for n in nodes]
    zs = [float(n[3]) for n in nodes]
    return min(xs), max(xs), min(ys), max(ys), min(zs), max(zs)


def compute_plate_xy_extent(
    mesh_nodes: list,
    settings: CompressionSettings,
) -> tuple[float, float, float, float]:
    """Plate footprint: solid mesh bounds + rod radius + extra margin per side."""
    xmin, xmax, ymin, ymax, _, _ = lattice_bounds(mesh_nodes)
    pad = settings.resolved_rod_radius() + settings.resolved_margin()
    return xmin - pad, xmax + pad, ymin - pad, ymax + pad


def compute_loading_plate_z(
    mesh_z_extreme: float,
    *,
    half_thk: float,
    settings: CompressionSettings,
    bottom_up: bool,
) -> float:
    """S4R midplane Z for the moving load plate (contact face on lattice side)."""
    if settings.plate_embed is not None:
        embed = settings.plate_embed
        if bottom_up:
            return mesh_z_extreme + embed - half_thk
        return mesh_z_extreme - embed + half_thk
    standoff = settings.resolved_plate_standoff()
    rod_r = settings.resolved_rod_radius()
    if bottom_up:
        # PLATE_TOP (SPOS) contacts lattice bottom at mesh_z_min - rod_r - standoff
        return mesh_z_extreme - rod_r - standoff + half_thk
    # PLATE_BOT (SNEG) contacts lattice top at mesh_z_max + rod_r + standoff
    return mesh_z_extreme + rod_r + standoff + half_thk


def compute_passive_plate_z(
    mesh_z_extreme: float,
    *,
    half_thk: float,
    settings: CompressionSettings,
    bottom_up: bool,
) -> float:
    """S4R midplane Z for passive fixed-end plate (counter or fixed bottom)."""
    if settings.plate_embed is not None:
        embed = settings.resolved_plate_embed()
        if bottom_up:
            return mesh_z_extreme - embed + half_thk
        return mesh_z_extreme + embed - half_thk
    standoff = settings.resolved_plate_standoff()
    rod_r = settings.resolved_rod_radius()
    if bottom_up:
        return mesh_z_extreme + rod_r + standoff + half_thk
    return mesh_z_extreme - rod_r - standoff - half_thk


def build_plate_mesh(
    x0: float,
    x1: float,
    y0: float,
    y1: float,
    z: float,
    nx_div: int,
    ny_div: int,
    node_id_start: int,
    elem_id_start: int,
) -> tuple[list[tuple[int, float, float, float]], list[tuple[int, int, int, int, int]], list[int]]:
    """Rectangular S4R plate in XY plane at z (CCW from +Z)."""
    nodes: list[tuple[int, float, float, float]] = []
    elements: list[tuple[int, int, int, int, int]] = []
    grid: list[list[int]] = []

    nid = node_id_start
    for j in range(ny_div + 1):
        row: list[int] = []
        y = y0 + (y1 - y0) * j / ny_div
        for i in range(nx_div + 1):
            x = x0 + (x1 - x0) * i / nx_div
            nodes.append((nid, x, y, z))
            row.append(nid)
            nid += 1
        grid.append(row)

    eid = elem_id_start
    for j in range(ny_div):
        for i in range(nx_div):
            n1 = grid[j][i]
            n2 = grid[j][i + 1]
            n3 = grid[j + 1][i + 1]
            n4 = grid[j + 1][i]
            elements.append((eid, n1, n2, n3, n4))
            eid += 1

    plate_node_ids = [n[0] for n in nodes]
    return nodes, elements, plate_node_ids


def collect_bottom_node_ids(
    mesh_nodes: Iterable[tuple[int, float, float, float]],
    z_tol: float,
) -> list[int]:
    return [nid for nid, _, _, z in mesh_nodes if z <= z_tol + 1e-9]


def collect_top_node_ids(
    mesh_nodes: Iterable[tuple[int, float, float, float]],
    z_tol: float,
) -> list[int]:
    z_max = max(z for _, _, _, z in mesh_nodes)
    z_cut = z_max - z_tol
    return [nid for nid, _, _, z in mesh_nodes if z >= z_cut - 1e-9]


# C3D4：Si 为节点 i 的对侧面（Abaqus 标准）
_C3D4_FACE_CORNERS: dict[str, tuple[int, int, int]] = {
    "S1": (1, 2, 3),
    "S2": (0, 2, 3),
    "S3": (0, 1, 3),
    "S4": (0, 1, 2),
}


# C3D8：Si 为节点 i 的对侧面（Abaqus 标准，0-based corner indices）
_C3D8_FACE_CORNERS: dict[str, tuple[int, int, int, int]] = {
    "S1": (0, 1, 2, 3),
    "S2": (0, 1, 5, 4),
    "S3": (1, 2, 6, 5),
    "S4": (2, 3, 7, 6),
    "S5": (3, 0, 4, 7),
    "S6": (4, 5, 6, 7),
}


def _face_normal_outward(
    coords: dict[int, np.ndarray],
    elem_center: np.ndarray,
    face_nids: list[int],
) -> np.ndarray | None:
    unique: list[int] = []
    seen: set[int] = set()
    for n in face_nids:
        if n not in seen:
            seen.add(n)
            unique.append(n)
    if len(unique) < 3:
        return None
    pts = [coords[n] for n in unique]
    if len(unique) >= 4:
        edge1 = pts[1] - pts[0]
        edge2 = pts[3] - pts[0]
        normal = np.cross(edge1, edge2)
    else:
        edge1 = pts[1] - pts[0]
        edge2 = pts[2] - pts[0]
        normal = np.cross(edge1, edge2)
    nlen = float(np.linalg.norm(normal))
    if nlen < 1e-15:
        return None
    normal /= nlen
    face_center = sum(pts) / len(pts)
    outward = face_center - elem_center
    if float(np.dot(normal, outward)) <= 0.0:
        normal = -normal
    return normal


def collect_c3d8_top_element_faces(
    mesh_nodes: Iterable[tuple[int, float, float, float]],
    mesh_elements: Iterable[tuple[int, ...]],
    *,
    z_band: float,
    normal_z_min: float = 0.85,
) -> list[tuple[int, str]]:
    """Outward top faces on C3D8/C3D8R lattice elements (+Z normal, near z_max)."""
    coords: dict[int, np.ndarray] = {
        nid: np.array([x, y, z], dtype=float) for nid, x, y, z in mesh_nodes
    }
    if not coords:
        return []

    z_max = max(p[2] for p in coords.values())
    z_cut = z_max - z_band
    top_faces: list[tuple[int, str]] = []

    for row in mesh_elements:
        eid = int(row[0])
        nids = tuple(int(n) for n in row[1:9])
        elem_center = sum(coords[n] for n in nids) / 8.0
        for label, corners in _C3D8_FACE_CORNERS.items():
            face_nids = [nids[i] for i in corners]
            pts = [coords[n] for n in face_nids]
            face_center = sum(pts) / 4.0
            if face_center[2] < z_cut - 1e-9:
                continue
            normal = _face_normal_outward(coords, elem_center, face_nids)
            if normal is None or normal[2] < normal_z_min:
                continue
            top_faces.append((eid, label))

    return top_faces


def collect_c3d8_bottom_element_faces(
    mesh_nodes: Iterable[tuple[int, float, float, float]],
    mesh_elements: Iterable[tuple[int, ...]],
    *,
    z_band: float,
    normal_z_max: float = -0.85,
) -> list[tuple[int, str]]:
    """Outward bottom faces on C3D8/C3D8R lattice elements (-Z normal, near z_min)."""
    coords: dict[int, np.ndarray] = {
        nid: np.array([x, y, z], dtype=float) for nid, x, y, z in mesh_nodes
    }
    if not coords:
        return []

    z_min = min(p[2] for p in coords.values())
    z_cut = z_min + z_band
    bottom_faces: list[tuple[int, str]] = []

    for row in mesh_elements:
        eid = int(row[0])
        nids = tuple(int(n) for n in row[1:9])
        elem_center = sum(coords[n] for n in nids) / 8.0
        for label, corners in _C3D8_FACE_CORNERS.items():
            face_nids = [nids[i] for i in corners]
            pts = [coords[n] for n in face_nids]
            face_center = sum(pts) / 4.0
            if face_center[2] > z_cut + 1e-9:
                continue
            normal = _face_normal_outward(coords, elem_center, face_nids)
            if normal is None or normal[2] > normal_z_max:
                continue
            bottom_faces.append((eid, label))

    return bottom_faces


def collect_c3d4_bottom_element_faces(
    mesh_nodes: Iterable[tuple[int, float, float, float]],
    mesh_elements: Iterable[tuple[int, int, int, int, int]],
    *,
    z_band: float,
    normal_z_max: float = -0.85,
) -> list[tuple[int, str]]:
    """Outward bottom faces on C3D4 lattice elements (-Z normal, near z_min)."""
    coords: dict[int, np.ndarray] = {
        nid: np.array([x, y, z], dtype=float) for nid, x, y, z in mesh_nodes
    }
    if not coords:
        return []

    z_min = min(p[2] for p in coords.values())
    z_cut = z_min + z_band
    bottom_faces: list[tuple[int, str]] = []

    for eid, n1, n2, n3, n4 in mesh_elements:
        nids = (n1, n2, n3, n4)
        elem_center = sum(coords[n] for n in nids) / 4.0
        for label, corners in _C3D4_FACE_CORNERS.items():
            face_nids = [nids[i] for i in corners]
            normal = _face_normal_outward(coords, elem_center, face_nids)
            if normal is None:
                continue
            pts = [coords[n] for n in face_nids]
            face_center = sum(pts) / 3.0
            if face_center[2] > z_cut + 1e-9:
                continue
            if normal[2] > normal_z_max:
                continue
            bottom_faces.append((eid, label))

    return bottom_faces


def collect_c3d4_top_element_faces(
    mesh_nodes: Iterable[tuple[int, float, float, float]],
    mesh_elements: Iterable[tuple[int, int, int, int, int]],
    *,
    z_band: float,
    normal_z_min: float = 0.85,
) -> list[tuple[int, str]]:
    """
    筛选点阵顶面 C3D4 外表面（法向朝 +Z 且相对单元质心向外），避免 Abaqus 报
    improperly defined surface。
    """
    coords: dict[int, np.ndarray] = {
        nid: np.array([x, y, z], dtype=float) for nid, x, y, z in mesh_nodes
    }
    if not coords:
        return []

    z_max = max(p[2] for p in coords.values())
    z_cut = z_max - z_band
    top_faces: list[tuple[int, str]] = []

    for eid, n1, n2, n3, n4 in mesh_elements:
        nids = (n1, n2, n3, n4)
        elem_center = sum(coords[n] for n in nids) / 4.0
        for label, corners in _C3D4_FACE_CORNERS.items():
            face_nids = [nids[i] for i in corners]
            normal = _face_normal_outward(coords, elem_center, face_nids)
            if normal is None:
                continue
            pts = [coords[n] for n in face_nids]
            face_center = sum(pts) / 3.0
            if face_center[2] < z_cut - 1e-9:
                continue
            if normal[2] < normal_z_min:
                continue
            top_faces.append((eid, label))

    return top_faces


def collect_c3d4_exterior_faces(
    mesh_nodes: Iterable[tuple[int, float, float, float]],
    mesh_elements: Iterable[tuple[int, int, int, int, int]],
) -> list[tuple[int, str]]:
    """All outward C3D4 faces (for general-contact self-contact surface)."""
    coords: dict[int, np.ndarray] = {
        nid: np.array([x, y, z], dtype=float) for nid, x, y, z in mesh_nodes
    }
    if not coords:
        return []

    exterior: list[tuple[int, str]] = []
    for eid, n1, n2, n3, n4 in mesh_elements:
        nids = (n1, n2, n3, n4)
        elem_center = sum(coords[n] for n in nids) / 4.0
        for label, corners in _C3D4_FACE_CORNERS.items():
            face_nids = [nids[i] for i in corners]
            pts = [coords[n] for n in face_nids]
            face_center = sum(pts) / 3.0
            edge1 = pts[1] - pts[0]
            edge2 = pts[2] - pts[0]
            normal = np.cross(edge1, edge2)
            nlen = float(np.linalg.norm(normal))
            if nlen < 1e-15:
                continue
            normal /= nlen
            outward = face_center - elem_center
            if float(np.dot(normal, outward)) <= 0.0:
                continue
            exterior.append((eid, label))
    return exterior


def collect_lattice_top_node_ids(
    mesh_nodes: Iterable[tuple[int, float, float, float]],
    *,
    z_band: float,
) -> list[int]:
    """点阵顶面附近节点（用于检查 / 可选 NODE 型耦合面）。"""
    z_max = max(z for _, _, _, z in mesh_nodes)
    z_cut = z_max - z_band
    return [nid for nid, _, _, z in mesh_nodes if z >= z_cut - 1e-9]


def collect_lattice_bottom_node_ids(
    mesh_nodes: Iterable[tuple[int, float, float, float]],
    *,
    z_band: float,
) -> list[int]:
    """点阵底面附近节点（用于 bottom_up 加载 / 耦合）。"""
    z_min = min(z for _, _, _, z in mesh_nodes)
    z_cut = z_min + z_band
    return [nid for nid, _, _, z in mesh_nodes if z <= z_cut + 1e-9]


def write_element_surface(
    f: TextIO,
    name: str,
    element_faces: Iterable[tuple[int, str]],
    *,
    pairs_per_line: int = 8,
) -> None:
    """Write *Surface, type=ELEMENT with explicit (element, face) pairs."""
    pairs = list(element_faces)
    if not pairs:
        raise ValueError(f"No element faces for surface {name!r}")

    f.write(f"*Surface, type=ELEMENT, name={name}\n")
    buf: list[str] = []
    for eid, face in pairs:
        buf.extend((str(eid), face))
        if len(buf) >= pairs_per_line * 2:
            f.write(", ".join(buf) + "\n")
            buf = []
    if buf:
        f.write(", ".join(buf) + "\n")


def write_surface_interaction(
    f: TextIO,
    *,
    name: str,
    settings: CompressionSettings,
    soft_s0: float | None = None,
    friction: float | None = None,
    scale_overclosure_r: float = 0.25,
) -> None:
    """*Surface Interaction for plate–lattice or lattice self-contact."""
    mu = settings.contact_friction if friction is None else friction
    soft = settings.contact_soft_clearance_mm if soft_s0 is None else soft_s0
    f.write(f"\n*Surface Interaction, name={name}\n")
    if soft is not None and soft > 0.0 and settings.analysis.lower() == "explicit":
        f.write("*Surface Behavior, pressure-overclosure=SCALE FACTOR\n")
        f.write(f"{scale_overclosure_r:.6g}, , 2.0, {soft:.6g}\n")
    else:
        f.write("*Surface Behavior, pressure-overclosure=HARD\n")
    if mu > 0.0:
        if settings.analysis.lower() == "explicit":
            f.write(f"*Friction\n{mu:.6g}\n")
        else:
            mu_tol = settings.contact_slip_tolerance
            f.write(f"*Friction, slip tolerance={mu_tol:.6g}\n{mu:.6g}\n")


def write_hard_contact_interaction(f: TextIO, settings: CompressionSettings) -> None:
    write_surface_interaction(f, name="HARD-CONTACT", settings=settings)


def write_model_contact_interactions(f: TextIO, settings: CompressionSettings) -> None:
    if settings.use_explicit_contact_settle():
        write_surface_interaction(
            f,
            name="SETTLE-CONTACT",
            settings=settings,
            soft_s0=settings.contact_settle_soft_s0,
            friction=settings.contact_settle_friction,
            scale_overclosure_r=0.25,
        )
        write_surface_interaction(f, name="HARD-CONTACT", settings=settings)
    else:
        write_surface_interaction(f, name="HARD-CONTACT", settings=settings)


def _write_explicit_dynamic_block(
    f: TextIO, settings: CompressionSettings, step_time: float
) -> None:
    dt = settings.resolved_explicit_dt()
    dt_mode = (settings.explicit_dt_mode or "fixed").lower()
    ms = settings.explicit_mass_scaling_factor
    mass_line = ""
    if settings.explicit_mass_scaling_dt_only:
        mass_line = f"*Fixed Mass Scaling, type=BELOW MIN, dt={dt:.12g}\n"
    elif ms is not None and ms > 0.0:
        mass_line = (
            f"*Fixed Mass Scaling, elset=ALLSOLID, factor={ms:.12g}, "
            f"type=BELOW MIN, dt={dt:.12g}\n"
        )
    if dt_mode in ("automatic", "auto", "adaptive"):
        f.write(
            f"** Explicit automatic dt (limit {dt:.6g}s); step {step_time:.12g}s\n"
            f"*Dynamic, Explicit\n"
            f", {step_time:.12g}\n"
        )
    else:
        n_inc = max(1, int(round(step_time / dt)))
        f.write(
            f"** Explicit fixed dt={dt:.6g}s (~{n_inc} increments)\n"
            f"*Dynamic, Explicit, direct user control\n"
            f"{dt:.12g}, {step_time:.12g}\n"
        )
    f.write(
        f"{mass_line}*Bulk Viscosity\n"
        f"{settings.bulk_viscosity_linear:.12g}, {settings.bulk_viscosity_quadratic:.12g}\n"
    )


def write_contact_initialization_data(
    f: TextIO, settings: CompressionSettings
) -> None:
    if not settings.contact_init_interference_fit:
        return
    if settings.analysis.lower() != "explicit":
        return
    frac = max(0.01, min(1.0, float(settings.contact_init_step_fraction)))
    f.write(
        f"""** Interference fit: resolve initial overclosures over first {frac:.0%} of step
*Contact Initialization Data, name=LAT-INIT, INTERFERENCE FIT, STEP FRACTION={frac:.6g}, SEARCH BELOW=0.35
"""
    )


def write_contact_initialization_assignment(
    f: TextIO,
    settings: CompressionSettings,
    plate_surface_pairs: list[tuple[str, str]] | None = None,
    *,
    lattice_exterior_surface: str | None = None,
) -> None:
    if not settings.contact_init_interference_fit:
        return
    if settings.analysis.lower() != "explicit":
        return
    pairs = list(plate_surface_pairs or [])
    if not pairs:
        return
    for slave, master in pairs:
        f.write(f"*Contact Initialization Assignment\n{slave}, {master}, LAT-INIT\n")


def write_contact_initialization_if_needed(
    f: TextIO,
    settings: CompressionSettings,
    plate_surface_pairs: list[tuple[str, str]] | None = None,
) -> None:
    write_contact_initialization_assignment(f, settings, plate_surface_pairs)


def write_contact_overclosure_resolution(
    f: TextIO,
    settings: CompressionSettings,
    *,
    method: str = "STORE OFFSETS",
) -> None:
    if not settings.contact_overclosure_store_offsets:
        return
    if settings.analysis.lower() != "explicit":
        return
    f.write(
        f"** Initial overclosure: {method} (no strain-free nodal adjustment)\n"
        "*Contact Controls Assignment, AUTOMATIC OVERCLOSURE RESOLUTION\n"
        f", , {method}\n"
    )


def write_lattice_general_contact_model(
    f: TextIO,
    *,
    interaction: str | None = "HARD-CONTACT",
    plate_surface_pairs: list[tuple[str, str]] | None = None,
    settings: CompressionSettings | None = None,
) -> None:
    """
    Model-level general contact (solid exterior facets).

    Explicit *Contact Pair cannot use element-based solid surfaces; ALL EXTERIOR
    with no extra data lines avoids comma-leading INP lines that pre rejects.
    Optional plate_surface_pairs add named plate–lattice inclusions before ALL EXTERIOR.
    """
    if settings is not None:
        write_contact_initialization_data(f, settings)
    f.write(
        "** Lattice self-contact + plate–lattice (general contact)\n"
        "*Contact\n"
    )
    for slave, master in plate_surface_pairs or []:
        f.write(f"*Contact Inclusions\n{slave}, {master}\n")
    f.write("*Contact Inclusions, ALL EXTERIOR\n")
    if settings is not None:
        write_contact_initialization_assignment(
            f,
            settings,
            plate_surface_pairs,
            lattice_exterior_surface=(
                "LATTICE_EXT"
                if settings.contact_init_interference_fit
                and settings.lattice_self_contact
                else None
            ),
        )
    if interaction:
        f.write(f"*Contact Property Assignment\n, , {interaction}\n")
    if settings is not None:
        write_contact_overclosure_resolution(f, settings)


def write_plate_pair_general_contact(
    f: TextIO,
    surface_pairs: list[tuple[str, str]],
    *,
    interaction: str = "HARD-CONTACT",
) -> None:
    """
    Plate–lattice hard contact for Abaqus/Explicit.

    *Contact Pair + type=SURFACE TO SURFACE is Standard-only and rejects C3D8R
    element-based slave surfaces. General contact inclusions between named
    lattice/plate surfaces matches Fig. 2.6 without rod self-contact.
    """
    if not surface_pairs:
        return
    f.write(
        "** Plate–lattice general contact (Explicit; pair mode, no rod self-contact)\n"
        "*Contact\n"
    )
    for slave, master in surface_pairs:
        f.write(f"*Contact Inclusions\n{slave}, {master}\n")
    f.write(f"*Contact Property Assignment\n, , {interaction}\n")


def write_nset(f: TextIO, name: str, node_ids: Iterable[int], *, lines: int = 16) -> None:
    ids = list(node_ids)
    if not ids:
        return
    f.write(f"*Nset, nset={name}\n")
    for i in range(0, len(ids), lines):
        f.write(", ".join(str(n) for n in ids[i : i + lines]) + "\n")


def write_compression_sections(
    f: TextIO,
    settings: CompressionSettings,
    *,
    fixed_node_ids: list[int],
    ref_node_id: int,
    plate_elem_ids: list[int],
    lattice_elem_ids: list[int],
    lattice_load_faces: list[tuple[int, str]],
    lattice_load_node_ids: list[int] | None = None,
    plate_z: float | None = None,
    mesh_z_max: float | None = None,
    # Legacy aliases (top_down export still passes these names)
    bottom_node_ids: list[int] | None = None,
    lattice_top_faces: list[tuple[int, str]] | None = None,
    lattice_top_node_ids: list[int] | None = None,
    counter_plate_elem_ids: list[int] | None = None,
    counter_ref_node_id: int | None = None,
    counter_lattice_node_ids: list[int] | None = None,
    fixed_plate_elem_ids: list[int] | None = None,
    fixed_ref_node_id: int | None = None,
    lattice_bottom_faces: list[tuple[int, str]] | None = None,
    lattice_exterior_faces: list[tuple[int, str]] | None = None,
) -> None:
    """Write materials, interactions, step, BC, contact for compression."""
    if bottom_node_ids is not None and not fixed_node_ids:
        fixed_node_ids = bottom_node_ids
    if lattice_top_faces is not None and not lattice_load_faces:
        lattice_load_faces = lattice_top_faces
    if lattice_top_node_ids is not None and lattice_load_node_ids is None:
        lattice_load_node_ids = lattice_top_node_ids

    bottom_up = settings.is_bottom_up()
    disp = settings.signed_compression_displacement()
    t_total = settings.step_time
    plate_thk = settings.plate_thickness

    fixed_nset = "TOP_FIX" if bottom_up else "BOTTOM_FIX"
    load_face_surf = "LATTICE_BOTTOM" if bottom_up else "LATTICE_TOP"
    load_node_nset = "LATTICE_BOTTOM_NODES" if bottom_up else "LATTICE_TOP_NODES"
    load_node_surf = "LATTICE_BOTTOM_NODAL" if bottom_up else "LATTICE_TOP_NODAL"
    plate_surf = "PLATE_TOP" if bottom_up else "PLATE_BOT"
    plate_face = "SPOS" if bottom_up else "SNEG"
    plate_label = "底板" if bottom_up else "顶板"
    load_end_label = "底面" if bottom_up else "顶面"
    use_counter = bottom_up and bool(counter_plate_elem_ids) and counter_ref_node_id is not None

    use_counter = bottom_up and bool(counter_plate_elem_ids) and counter_ref_node_id is not None
    use_fixed_bottom = settings.use_fixed_bottom_plate() and bool(fixed_plate_elem_ids) and fixed_ref_node_id is not None

    if not use_counter and not use_fixed_bottom:
        write_nset(f, fixed_nset, fixed_node_ids)
    write_nset(f, "PLATE_REF", [ref_node_id])

    _write_elset(f, "PLATE", plate_elem_ids)
    _write_elset(f, "LATTICE", lattice_elem_ids)

    mode = (settings.contact_mode or "tie").lower()
    needs_plate_surface = mode not in ("coupling_nodes", "direct_top")
    needs_hard_contact = settings.lattice_self_contact or needs_plate_surface

    f.write(
        f"""
** --- {plate_label}刚体 + 点阵{load_end_label}载荷传递（Abaqus/Explicit）---
*Surface, type=ELEMENT, name={plate_surf}
PLATE, {plate_face}
"""
    )
    if needs_plate_surface:
        write_element_surface(f, load_face_surf, lattice_load_faces)
    if needs_hard_contact:
        write_model_contact_interactions(f, settings)
    f.write(
        f"""*Material, name=PLATE-STEEL
*Elastic
210000., 0.3
*Density
7.85e-9
*Shell Section, elset=PLATE, material=PLATE-STEEL
{plate_thk:.12g}
*Rigid Body, elset=PLATE, ref node={ref_node_id}
"""
    )
    if use_fixed_bottom:
        if not lattice_bottom_faces:
            raise ValueError("fixed_bottom_plate requires lattice_bottom_faces")
        write_element_surface(f, "LATTICE_BOTTOM", lattice_bottom_faces)
        write_nset(f, "PLATE_FIXED_REF", [int(fixed_ref_node_id)])
        _write_elset(f, "PLATE_FIXED", fixed_plate_elem_ids)
        f.write(
            f"""*Shell Section, elset=PLATE_FIXED, material=PLATE-STEEL
{plate_thk:.12g}
*Rigid Body, elset=PLATE_FIXED, ref node={int(fixed_ref_node_id)}
** --- 底面固定刚体板（Fig.2.6 RP2 ENCASTRE）---
*Surface, type=ELEMENT, name=PLATE_FIXED_TOP
PLATE_FIXED, SPOS
"""
        )
    if use_counter:
        counter_nodes = list(counter_lattice_node_ids or fixed_node_ids)
        if not counter_nodes:
            raise ValueError("counter plate requires counter_lattice_node_ids")
        write_nset(f, "PLATE_COUNTER_REF", [int(counter_ref_node_id)])
        _write_elset(f, "PLATE_COUNTER", counter_plate_elem_ids)
        write_nset(f, "LATTICE_TOP_NODES", counter_nodes)
        f.write(
            f"""*Shell Section, elset=PLATE_COUNTER, material=PLATE-STEEL
{plate_thk:.12g}
*Rigid Body, elset=PLATE_COUNTER, ref node={int(counter_ref_node_id)}
** --- 顶板刚体（固定端，点阵顶面运动学耦合）---
*Surface, type=ELEMENT, name=PLATE_COUNTER_BOT
PLATE_COUNTER, SNEG
*Surface, type=NODE, name=LATTICE_TOP_NODAL
LATTICE_TOP_NODES,
*Coupling, constraint name=PLATE-COUNTER-CPL, ref node={int(counter_ref_node_id)}, surface=LATTICE_TOP_NODAL
*Kinematic
1, 3
"""
        )
    if mode == "coupling":
        f.write(
            f"""
** RP 运动学耦合点阵{load_end_label}单元面（Explicit 下不如 coupling_nodes 稳）
*Coupling, constraint name=PLATE-LATTICE-CPL, ref node={ref_node_id}, surface={load_face_surf}
*Kinematic
1, 3
"""
        )
    elif mode in ("coupling_nodes", "direct_top"):
        load_nodes = list(lattice_load_node_ids or [])
        if not load_nodes:
            raise ValueError(f"{mode} requires lattice_load_node_ids")
        write_nset(f, load_node_nset, load_nodes)
        if mode == "coupling_nodes":
            f.write(
                f"""** {load_end_label}节点与 PLATE_REF 同步 U1-U3（命令行提交）
*Surface, type=NODE, name={load_node_surf}
{load_node_nset},
*Coupling, constraint name=PLATE-LATTICE-CPL, ref node={ref_node_id}, surface={load_node_surf}
*Kinematic
1, 3
"""
            )
        else:
            f.write(
                f"""
** direct_top：不用 Coupling/接触，Compression 步对 {load_node_nset} 直接施加 U3
"""
            )
    plate_pairs: list[tuple[str, str]] = []
    if mode == "pair":
        plate_pairs.append((load_face_surf, plate_surf))
    if use_fixed_bottom:
        plate_pairs.append(("LATTICE_BOTTOM", "PLATE_FIXED_TOP"))
    if settings.lattice_self_contact:
        default_contact = (
            "SETTLE-CONTACT"
            if settings.use_explicit_contact_settle()
            else "HARD-CONTACT"
        )
        write_lattice_general_contact_model(
            f,
            interaction=default_contact,
            plate_surface_pairs=plate_pairs if mode == "pair" else None,
            settings=settings,
        )
    elif settings.analysis.lower() == "explicit" and plate_pairs:
        write_plate_pair_general_contact(f, plate_pairs)
    if mode == "tie":
        tie_tol = settings.resolved_tie_position_tolerance()
        f.write(
            f"""
** Tie 数据行：slave, master；NODE TO SURFACE + 容差
*Tie, name=PLATE-LATTICE-TIE, adjust=YES, position tolerance={tie_tol:.12g}, type=NODE TO SURFACE
{load_face_surf}, {plate_surf}
"""
        )
    amp = settings.displacement_amplitude_name
    t_compress = t_total
    t_settle = 0.0
    if settings.use_explicit_contact_settle():
        frac = max(0.05, min(0.5, float(settings.contact_settle_time_fraction)))
        t_settle = frac * t_total
    fixed_bc = (
        "PLATE_COUNTER_REF, 1, 6, 0.\n"
        if use_counter
        else (
            f"PLATE_FIXED_REF, 1, 6, 0.\n"
            if use_fixed_bottom
            else f"{fixed_nset}, 1, 3, 0.\n"
        )
    )
    f.write(
        f"""*Boundary
{fixed_bc}PLATE_REF, 1, 6, 0.

"""
    )

    contact_block = ""
    if mode == "pair":
        if settings.analysis.lower() != "explicit":
            contact_block = f"""
** {plate_label}压点阵：slave={load_face_surf}, master={plate_surf}（刚体板）
*Contact Pair, interaction=HARD-CONTACT, type=SURFACE TO SURFACE
{load_face_surf}, {plate_surf}
"""
            if use_fixed_bottom:
                contact_block += f"""** 点阵底面–固定刚体板
*Contact Pair, interaction=HARD-CONTACT, type=SURFACE TO SURFACE
LATTICE_BOTTOM, PLATE_FIXED_TOP
"""
    elif mode == "hybrid":
        contact_block = f"""
*Contact Pair, interaction=HARD-CONTACT, type=SURFACE TO SURFACE
{load_face_surf}, {plate_surf}
"""
    elif mode == "general":
        if not settings.lattice_self_contact:
            write_lattice_general_contact_model(f)
        contact_block = ""
    elif mode in ("coupling", "coupling_nodes", "tie", "direct_top"):
        contact_block = ""

    if mode == "direct_top":
        compression_bc = f"""*Boundary, type=DISPLACEMENT, op=MOD, amplitude={amp}
{load_node_nset}, 3, 3, {disp:.12g}
PLATE_REF, 3, 3, {disp:.12g}
"""
    else:
        compression_bc = f"""*Boundary, type=DISPLACEMENT, op=MOD, amplitude={amp}
PLATE_REF, 3, 3, {disp:.12g}
"""

    def _write_step_outputs(step_time: float, *, full: bool) -> None:
        if not full:
            f.write(
                """*Output, field, number interval=1
*Node Output
U,
*Element Output, elset=LATTICE
S, LE
"""
            )
            return
        f.write(
            f"""*Output, field, number interval=50
*Node Output
U,
*Node Output, nset=PLATE_REF
RF,
*Node Output, nset={"PLATE_COUNTER_REF" if use_counter else ("PLATE_FIXED_REF" if use_fixed_bottom else fixed_nset)}
RF,
*Element Output, elset=LATTICE
S, LE

*Output, history, time interval={max(step_time / 100.0, 1.0e-4):.12g}
*Node Output, nset=PLATE_REF
RF, U
*Energy Output
ALLIE, ALLKE, ALLSE, ALLVD, ALLWK, ALLPD
"""
        )
        if use_fixed_bottom and fixed_ref_node_id is not None:
            f.write(
                f"""*Node Output, nset=PLATE_FIXED_REF
RF, U
"""
            )
        if settings.history_lattice_top_nodes and lattice_load_node_ids:
            f.write(
                f"""*Node Output, nset={load_node_nset}
RF, U
"""
            )

    if settings.use_explicit_contact_settle() and settings.analysis.lower() == "explicit":
        settle_name = settings.contact_settle_step_name
        f.write(
            f"""** Step 1: zero displacement + soft self-contact (s0={settings.contact_settle_soft_s0:g}, mu={settings.contact_settle_friction:g}) store_offsets={settings.contact_overclosure_store_offsets}
*Step, name={settle_name}, nlgeom=YES
"""
        )
        _write_explicit_dynamic_block(f, settings, t_settle)
        if settings.contact_overclosure_store_offsets:
            f.write(
                """** Reassert STORE OFFSETS at step 1 (general contact domain)
*Contact
*Contact Controls Assignment, AUTOMATIC OVERCLOSURE RESOLUTION
, , STORE OFFSETS
"""
            )
        if contact_block:
            f.write(contact_block)
        _write_step_outputs(t_settle, full=False)
        f.write(
            f"""** settle={t_settle:.9g}s compress={t_compress:.9g}s self_contact={settings.lattice_self_contact}
*End Step

** Step 2: full compression with HARD self-contact
"""
        )
        t_hold = max(0.0, min(0.5, settings.amplitude_hold_fraction)) * t_compress
        f.write(
            f"""** 位移幅值（STEP TIME；压缩步内 ramp）
*Amplitude, name={amp}, time=STEP TIME
0., 0.
{t_hold:.12g}, 0.
{t_compress:.12g}, 1.

*Step, name={settings.step_name}, nlgeom=YES
"""
        )
        _write_explicit_dynamic_block(f, settings, t_compress)
        f.write(
            """** Switch to HARD self-contact for compression
*Contact
*Contact Property Assignment
, , HARD-CONTACT
"""
        )
        if contact_block:
            f.write(contact_block)
        f.write(compression_bc)
        _write_step_outputs(t_compress, full=True)
        restart_block = ""
        if settings.explicit_restart_write:
            n_restart = settings.resolved_restart_number_interval()
            restart_block = f"*Restart, write, overlay, number interval={n_restart}\n"
        direction = settings.loading_direction
        f.write(
            f"""{restart_block}** loading={direction} counter_plate={use_counter} fixed_bottom_plate={use_fixed_bottom} contact={mode} self_contact={settings.lattice_self_contact} amp={amp} dt_mode={settings.explicit_dt_mode} dt={settings.resolved_explicit_dt():.6g}s settle={t_settle:.9g}s disp={disp:.9g}/{t_compress:.9g}s
*End Step
"""
        )
        return

    t_hold = max(0.0, min(0.5, settings.amplitude_hold_fraction)) * t_total
    f.write(
        f"""** 位移幅值（每行一对 time,value；不可写 3 对在一行）
*Amplitude, name={amp}, time=TOTAL TIME
0., 0.
{t_hold:.12g}, 0.
{t_total:.12g}, 1.

*Step, name={settings.step_name}, nlgeom=YES
"""
    )

    if settings.analysis.lower() == "explicit":
        _write_explicit_dynamic_block(f, settings, t_total)
    else:
        f.write(
            """*Static
0.01, 1., 1e-08, 0.1
"""
        )

    if contact_block:
        f.write(contact_block)
    f.write(compression_bc)
    _write_step_outputs(t_total, full=True)
    restart_block = ""
    if settings.analysis.lower() == "explicit" and settings.explicit_restart_write:
        n_restart = settings.resolved_restart_number_interval()
        restart_block = f"*Restart, write, overlay, number interval={n_restart}\n"
    direction = settings.loading_direction
    f.write(
        f"""{restart_block}** loading={direction} counter_plate={use_counter} fixed_bottom_plate={use_fixed_bottom} contact={mode} self_contact={settings.lattice_self_contact} amp={amp} dt_mode={settings.explicit_dt_mode} dt={settings.resolved_explicit_dt():.6g}s n_inc_est={settings.resolved_explicit_n_increments()} lattice_load_faces={len(lattice_load_faces)} lattice_load_nodes={len(lattice_load_node_ids or [])} disp={disp:.9g}/{t_total:.9g}s
*End Step
"""
    )


def _write_elset(f: TextIO, name: str, element_ids: Iterable[int], *, lines: int = 16) -> None:
    ids = [str(i) for i in element_ids]
    if not ids:
        return
    f.write(f"*Elset, elset={name}\n")
    for i in range(0, len(ids), lines):
        f.write(", ".join(ids[i : i + lines]) + "\n")
