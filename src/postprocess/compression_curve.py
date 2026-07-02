"""Macroscopic engineering stress-strain from compression test history (RF3, U3)."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from typing import Iterable, Sequence


@dataclass
class CompressionMeta:
    """Geometry and step metadata written at INP export time."""

    nx: int
    ny: int
    nz: int
    cell_size: float
    height_ratio: float
    compression_displacement: float
    step_time: float
    step_name: str = "Compression"
    reference_area_mm2: float = 0.0
    reference_height_mm: float = 0.0
    mesh_z_min: float = 0.0
    mesh_z_max: float = 0.0
    plate_ref_node_id: int = 0
    plate_fixed_ref_node_id: int = 0
    amplitude_hold_fraction: float = 0.3
    loading_direction: str = "top_down"
    case_slug: str = ""
    geometry_tag: str = ""
    support_type: str = ""
    support_angle_deg: float | None = None
    r_frame: float = 0.0
    r_support: float = 0.0
    r_vertical: float = 0.0

    @classmethod
    def from_export_stats(
        cls,
        *,
        nx: int,
        ny: int,
        nz: int,
        cell_size: float,
        height_ratio: float,
        compression_displacement: float,
        step_time: float,
        step_name: str,
        stats: dict,
        amplitude_hold_fraction: float = 0.3,
        case_slug: str = "",
        geometry_tag: str = "",
        support_type: str = "",
        support_angle_deg: float | None = None,
        r_frame: float = 0.0,
        r_support: float = 0.0,
        r_vertical: float = 0.0,
        loading_direction: str = "top_down",
    ) -> CompressionMeta:
        mesh_z_max = float(stats.get("mesh_z_max", nz * cell_size))
        mesh_z_min = float(stats.get("mesh_z_min", 0.0))
        ref_h = nominal_block_height_mm(nz, cell_size)
        ref_a = nominal_block_area_mm2(nx, ny, cell_size)
        return cls(
            nx=nx,
            ny=ny,
            nz=nz,
            cell_size=cell_size,
            height_ratio=height_ratio,
            compression_displacement=compression_displacement,
            step_time=step_time,
            step_name=step_name,
            reference_area_mm2=ref_a,
            reference_height_mm=ref_h,
            mesh_z_min=mesh_z_min,
            mesh_z_max=mesh_z_max,
            plate_ref_node_id=int(stats.get("plate_ref_node_id", 0) or 0),
            plate_fixed_ref_node_id=int(
                stats.get("plate_fixed_ref_node_id", stats.get("fixed_plate_ref_node_id", 0))
                or 0
            ),
            amplitude_hold_fraction=float(amplitude_hold_fraction),
            case_slug=str(case_slug),
            geometry_tag=str(geometry_tag),
            support_type=str(support_type),
            support_angle_deg=support_angle_deg,
            r_frame=float(r_frame),
            r_support=float(r_support),
            r_vertical=float(r_vertical),
            loading_direction=str(
                stats.get("loading_direction", loading_direction) or loading_direction
            ),
        )

    def hold_end_time(self) -> float:
        frac = max(0.0, min(0.5, self.amplitude_hold_fraction))
        return frac * self.step_time


def save_compression_meta(meta: CompressionMeta, path: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(asdict(meta), f, indent=2, ensure_ascii=False)
        f.write("\n")


def load_compression_meta(path: str) -> CompressionMeta:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    known = {f.name for f in CompressionMeta.__dataclass_fields__.values()}  # type: ignore[attr-defined]
    filtered = {k: v for k, v in data.items() if k in known}
    return CompressionMeta(**filtered)


def nominal_block_area_mm2(nx: int, ny: int, cell_size: float) -> float:
    """Nominal footprint nx·L × ny·L (§2.2 block geometry; macro σ definition 原文未详述)."""
    return max(float(nx) * float(cell_size) * float(ny) * float(cell_size), 1e-9)


def nominal_block_height_mm(nz: int, cell_size: float) -> float:
    """Block height nz·L (§2.2 Eq. 2.12 strain definition for theory model)."""
    return max(float(nz) * float(cell_size), 1e-9)


def paper_reference_geometry(meta: CompressionMeta) -> tuple[float, float]:
    """
    Nominal block area/height for engineering σ–ε (repo convention).

    §2.4.2 experiment: record load F and stroke S from MTS; §2.2 Eq. 2.11–2.12
    use single-cell area/height in theory. Thesis does not specify ODB extraction
    (PLATE_REF RF3/U3 vs load cell). This repo uses:
      σ = |F| / (nx·L·ny·L),  ε = |S| / (nz·L)
    """
    area = meta.reference_area_mm2
    height = meta.reference_height_mm
    if area <= 0.0:
        area = nominal_block_area_mm2(meta.nx, meta.ny, meta.cell_size)
    if height <= 0.0:
        height = nominal_block_height_mm(meta.nz, meta.cell_size)
    return area, height


def trim_amplitude_hold(
    times: Sequence[float],
    u3_mm: Sequence[float],
    rf3_n: Sequence[float],
    meta: CompressionMeta,
) -> tuple[list[float], list[float], list[float]]:
    """Drop points before COMP-DISP amplitude ramp starts."""
    t_end = meta.hold_end_time()
    if t_end <= 0.0:
        return list(times), list(u3_mm), list(rf3_n)
    out_t, out_u, out_r = [], [], []
    for t, u, r in zip(times, u3_mm, rf3_n):
        if float(t) >= t_end - 1e-9:
            out_t.append(float(t))
            out_u.append(float(u))
            out_r.append(float(r))
    return out_t, out_u, out_r


def filter_load_spikes(
    times: Sequence[float],
    u3_mm: Sequence[float],
    rf3_n: Sequence[float],
    *,
    min_disp_mm: float = 0.01,
    disp_ratio: float = 0.02,
    rf_factor: float = 5.0,
) -> tuple[list[float], list[float], list[float]]:
    """
    Remove explicit transient spikes at load onset.

    1) Drop points before |U3-U3_0| reaches ``min_disp_mm``.
    2) Drop remaining points with huge |RF3| while displacement is still tiny.
    """
    n = len(times)
    if n < 4:
        return list(times), list(u3_mm), list(rf3_n)

    u0 = float(u3_mm[0])
    u_final = float(u3_mm[-1])
    disp_span = max(abs(u_final - u0), 1e-9)
    disp_thresh = max(min_disp_mm, disp_ratio * disp_span)

    load_start = n
    for i in range(n):
        if abs(float(u3_mm[i]) - u0) >= disp_thresh:
            load_start = i
            break

    loaded_rf = [abs(float(rf3_n[i])) for i in range(load_start, n)]
    rf_med = sorted(loaded_rf)[len(loaded_rf) // 2] if loaded_rf else 1e-6
    rf_limit = max(rf_med * rf_factor, 0.1)

    out_t, out_u, out_r = [], [], []
    for i, (t, u, r) in enumerate(zip(times, u3_mm, rf3_n)):
        if i < load_start:
            continue
        disp = abs(float(u) - u0)
        if disp < disp_thresh and abs(float(r)) > rf_limit:
            continue
        out_t.append(float(t))
        out_u.append(float(u))
        out_r.append(float(r))
    return out_t, out_u, out_r


def postprocess_history(
    times: Sequence[float],
    u3_mm: Sequence[float],
    rf3_n: Sequence[float],
    meta: CompressionMeta,
    *,
    trim_hold: bool = True,
    drop_spike: bool = True,
    method: str = "paper",
) -> tuple[list[float], list[float], list[float]]:
    t, u, r = list(times), list(u3_mm), list(rf3_n)
    if trim_hold:
        t, u, r = trim_amplitude_hold(t, u, r, meta)
    if drop_spike and method.lower() != "paper":
        t, u, r = filter_load_spikes(t, u, r)
    return t, u, r


def build_curve_records(
    times: Sequence[float],
    u3_mm: Sequence[float],
    rf3_n: Sequence[float],
    meta: CompressionMeta,
    *,
    force_source: str = "paper_top_plate",
    method: str = "paper",
) -> list[dict[str, float]]:
    """
    Build engineering stress-strain (compression positive).

    Repo ``paper`` method (aligned with §2.4.2 F/S idea; FE output mapping 原文未写):
      F ← top rigid-plate reaction (PLATE_REF RF3)
      S ← top plate stroke (PLATE_REF U3 − U3_0)
      σ = |F| / (nx·L·ny·L),  ε = |S| / (nz·L)
    """
    if not times:
        return []
    if len(u3_mm) != len(times) or len(rf3_n) != len(times):
        raise ValueError("times, u3_mm, rf3_n must have the same length")

    u0 = float(u3_mm[0])
    if method.lower() == "paper":
        area, height = paper_reference_geometry(meta)
    else:
        area = max(meta.reference_area_mm2, 1e-9)
        height = max(meta.reference_height_mm, 1e-9)

    rows: list[dict[str, float]] = []
    for t, u3, rf3 in zip(times, u3_mm, rf3_n):
        disp = abs(float(u3) - u0)
        strain = disp / height
        stress = abs(float(rf3)) / area
        rows.append(
            {
                "time_s": float(t),
                "U3_mm": float(u3),
                "RF3_N": float(rf3),
                "displacement_mm": disp,
                "engineering_strain": strain,
                "engineering_stress_MPa": stress,
                "force_source": force_source,
            }
        )
    return rows


def _smooth_series(values: Sequence[float], window: int = 5) -> list[float]:
    n = len(values)
    if n < 3:
        return [float(v) for v in values]
    w = max(3, int(window) | 1)
    half = w // 2
    out: list[float] = []
    for i in range(n):
        lo = max(0, i - half)
        hi = min(n, i + half + 1)
        out.append(sum(float(values[j]) for j in range(lo, hi)) / (hi - lo))
    return out


def estimate_densification_strain(
    strains: Sequence[float],
    stresses: Sequence[float],
    *,
    smooth_window: int = 5,
    min_strain: float = 0.2,
    late_strain: float = 0.55,
) -> dict[str, float]:
    """
    Densification onset from macro stress–strain (Hu & Bai 2024 §3.3, ISO 13314 style).

    η(ε) = W(ε) / σ*(ε),  W = ∫σ dε,  σ* = max stress up to ε.
    Densification starts near a local peak of η (efficiency rolls over before deep densification).

    Returns engineering_strain, engineering_stress_MPa at the detected onset.
  """
    if len(strains) < 8:
        return {
            "densification_strain": float("nan"),
            "densification_stress_MPa": float("nan"),
        }

    eps = [float(s) for s in strains]
    sig = _smooth_series([float(s) for s in stresses], smooth_window)

    w_abs = [0.0]
    for i in range(1, len(eps)):
        de = eps[i] - eps[i - 1]
        w_abs.append(w_abs[-1] + 0.5 * (sig[i] + sig[i - 1]) * de)

    sigma_star: list[float] = []
    running = 0.0
    for s in sig:
        running = max(running, s)
        sigma_star.append(running)

    eta = [
        w_abs[i] / sigma_star[i] if sigma_star[i] > 1e-12 else 0.0 for i in range(len(w_abs))
    ]

    peaks: list[tuple[float, float, float]] = []
    for i in range(1, len(eta) - 1):
        if eps[i] < min_strain:
            continue
        if eta[i] >= eta[i - 1] and eta[i] >= eta[i + 1]:
            peaks.append((eta[i], eps[i], sig[i]))

    if not peaks:
        bi = max(range(len(eta)), key=lambda i: eta[i] if eps[i] >= min_strain else -1.0)
        return {
            "densification_strain": eps[bi],
            "densification_stress_MPa": sig[bi],
        }

    eta_max = max(p[0] for p in peaks)
    late = [p for p in peaks if p[1] >= late_strain and p[0] >= 0.85 * eta_max]
    _, ed, sd = max(late or peaks, key=lambda p: (p[1], p[0]))
    return {
        "densification_strain": float(ed),
        "densification_stress_MPa": float(sd),
    }


# §3.3.1 energy-absorption analysis (Hu & Bai thesis); used for sim compare & Fig.3.3 εd markers
HU_BAI_PAPER_DENSIFICATION_STRAIN = {
    "bcc": 0.70,
    "q0.5": 0.79,
    "q1": 0.75,
    "q1.5": 0.56,
}


def write_curve_csv(rows: Iterable[dict[str, float]], path: str) -> None:
    import csv

    rows = list(rows)
    if not rows:
        raise ValueError("No curve data to write")

    fieldnames = list(rows[0].keys())
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)
