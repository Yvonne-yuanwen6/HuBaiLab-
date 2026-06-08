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
        ref_h = max(mesh_z_max - mesh_z_min, 1e-9)
        ref_a = max(nx * cell_size * ny * cell_size, 1e-9)
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
) -> tuple[list[float], list[float], list[float]]:
    t, u, r = list(times), list(u3_mm), list(rf3_n)
    if trim_hold:
        t, u, r = trim_amplitude_hold(t, u, r, meta)
    if drop_spike:
        t, u, r = filter_load_spikes(t, u, r)
    return t, u, r


def build_curve_records(
    times: Sequence[float],
    u3_mm: Sequence[float],
    rf3_n: Sequence[float],
    meta: CompressionMeta,
    *,
    force_source: str = "plate_ref",
) -> list[dict[str, float]]:
    """
    Build engineering stress-strain (compression positive).

    stress = |RF3| / reference_area_mm2  (N/mm2 = MPa)
    strain = |U3 - U3_0| / reference_height_mm
    """
    if not times:
        return []
    if len(u3_mm) != len(times) or len(rf3_n) != len(times):
        raise ValueError("times, u3_mm, rf3_n must have the same length")

    u0 = float(u3_mm[0])
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
