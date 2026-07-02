"""Abaqus/Explicit restart continuation: extend compression strain from a completed job."""

from __future__ import annotations

import json
import math
import os
import re
from dataclasses import dataclass
from typing import Any

from src.export.abaqus_compression import (
    EXPLICIT_RESTART_DEFAULT_NUMBER_INTERVAL,
    EXPLICIT_RESTART_MAX_NUMBER_INTERVAL,
    HU_BAI_AMPLITUDE_HOLD_FRACTION,
    HU_BAI_LOAD_RATE_MM_MIN,
    hu_bai_compression_displacement,
    hu_bai_quasi_static_step_time,
    validate_explicit_restart_inp,
)

# Abaqus/Explicit restart read (oldjob=) requires these extensions in the job dir.
EXPLICIT_RESTART_FILE_EXTENSIONS = (
    "abq",
    "mdl",
    "stt",
    "pac",
    "prt",
    "res",
    "sel",
    "odb",
)


@dataclass(frozen=True)
class ContinueSegment:
    source_slug: str
    target_slug: str
    source_strain: float
    target_strain: float
    delta_strain: float
    reference_height_mm: float
    reference_area_mm2: float
    additional_displacement_mm: float
    step_time_s: float
    load_rate_mm_min: float
    hold_fraction: float
    source_step_name: str
    source_step_number: int
    restart_read_interval: int
    explicit_dt: float
    explicit_mass_scaling: float
    bulk_viscosity_linear: float
    bulk_viscosity_quadratic: float


def _load_json(path: str) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def source_strain_from_meta(meta: dict[str, Any]) -> float:
    loading = meta.get("loading") or {}
    if loading.get("target_engineering_strain") is not None:
        return float(loading["target_engineering_strain"])
    height = float(meta.get("reference_height_mm") or 0.0)
    disp = float(meta.get("compression_displacement") or loading.get("compression_displacement_mm") or 0.0)
    if height > 0.0 and disp > 0.0:
        return disp / height
    raise ValueError("Cannot infer source strain from meta.json")


def compute_continue_segment(
    *,
    source_slug: str,
    target_slug: str,
    source_meta: dict[str, Any],
    target_strain: float,
    load_rate_mm_min: float | None = None,
    hold_fraction: float | None = None,
    restart_number_interval: int | None = None,
) -> ContinueSegment:
    src_strain = source_strain_from_meta(source_meta)
    tgt = float(target_strain)
    if tgt <= src_strain + 1e-9:
        raise ValueError(
            f"target strain {tgt:.4f} must exceed source strain {src_strain:.4f}"
        )
    loading = source_meta.get("loading") or {}
    nz = int(source_meta.get("nz") or loading.get("block_cells", [4, 4, 4])[2])
    cell = float(source_meta.get("cell_size") or loading.get("cell_size_mm") or 20.0)
    height = float(source_meta.get("reference_height_mm") or nz * cell)
    area = float(source_meta.get("reference_area_mm2") or 0.0)
    rate = float(load_rate_mm_min if load_rate_mm_min is not None else loading.get("load_rate_mm_min") or HU_BAI_LOAD_RATE_MM_MIN)
    hold = float(hold_fraction if hold_fraction is not None else loading.get("amplitude_hold_fraction") or HU_BAI_AMPLITUDE_HOLD_FRACTION)
    delta = tgt - src_strain
    add_disp = hu_bai_compression_displacement(nz, cell, target_strain=delta)
    step_time = hu_bai_quasi_static_step_time(add_disp, load_rate_mm_min=rate)
    n_restart = restart_number_interval
    if n_restart is None:
        n_restart = int(loading.get("explicit_restart_number_interval") or EXPLICIT_RESTART_DEFAULT_NUMBER_INTERVAL)
    n_restart = max(1, min(EXPLICIT_RESTART_MAX_NUMBER_INTERVAL, int(n_restart)))
    step_num = int(loading.get("compression_step_number") or 0)
    if step_num <= 0:
        step_num = 2 if loading.get("explicit_contact_settle") else 1
    dt = float(loading.get("explicit_dt") or 5.0e-4)
    mass = float(loading.get("explicit_mass_scaling") or 50.0)
    return ContinueSegment(
        source_slug=source_slug,
        target_slug=target_slug,
        source_strain=src_strain,
        target_strain=tgt,
        delta_strain=delta,
        reference_height_mm=height,
        reference_area_mm2=area,
        additional_displacement_mm=add_disp,
        step_time_s=step_time,
        load_rate_mm_min=rate,
        hold_fraction=hold,
        source_step_name=str(source_meta.get("step_name") or "Compression"),
        source_step_number=step_num,
        restart_read_interval=n_restart,
        explicit_dt=dt,
        explicit_mass_scaling=mass,
        bulk_viscosity_linear=0.12,
        bulk_viscosity_quadratic=1.6,
    )


def required_restart_files(job_dir: str, source_slug: str) -> list[str]:
    missing = []
    for ext in EXPLICIT_RESTART_FILE_EXTENSIONS:
        name = f"{source_slug}.{ext}"
        if not os.path.isfile(os.path.join(job_dir, name)):
            missing.append(name)
    return missing


def link_restart_files(source_job_dir: str, target_job_dir: str, source_slug: str) -> list[str]:
    """Symlink (or copy fallback) all Explicit restart files into target job dir."""
    os.makedirs(target_job_dir, exist_ok=True)
    linked: list[str] = []
    for ext in EXPLICIT_RESTART_FILE_EXTENSIONS:
        name = f"{source_slug}.{ext}"
        src = os.path.join(source_job_dir, name)
        dst = os.path.join(target_job_dir, name)
        if not os.path.isfile(src):
            continue
        if os.path.lexists(dst):
            linked.append(name)
            continue
        try:
            os.symlink(src, dst)
        except OSError:
            if ext == "odb":
                raise OSError(f"Cannot link large restart file {name}; free disk or enable symlinks")
            import shutil
            shutil.copy2(src, dst)
        linked.append(name)
    return linked


def _signed_additional_displacement(meta: dict[str, Any], magnitude_mm: float) -> float:
    direction = str(meta.get("loading_direction") or "top_down").lower()
    mag = abs(float(magnitude_mm))
    return -mag if direction in ("top_down", "down", "compress") else mag


def write_explicit_continue_inp(
    out_path: str,
    *,
    segment: ContinueSegment,
    source_meta: dict[str, Any],
) -> None:
    hold = max(0.0, min(0.5, segment.hold_fraction)) * segment.step_time_s
    hold_line = f"{hold:.12g}, 0.\n" if hold > 1e-9 else ""
    disp = _signed_additional_displacement(source_meta, segment.additional_displacement_mm)
    hist_interval = max(segment.step_time_s / 100.0, 1.0e-4)
    amp_name = "COMP-DISP-CONT"
    step_name = "CompressionContinue"
    text = f"""** HuBaiLab Explicit restart continue
** source={segment.source_slug} strain={segment.source_strain:.4f} -> target={segment.target_strain:.4f}
** oldjob={segment.source_slug} on abq command line
*Restart, read, end step, step={segment.source_step_number}, interval={segment.restart_read_interval}

*Amplitude, name={amp_name}, time=STEP TIME
0., 0.
{hold_line}{segment.step_time_s:.12g}, 1.

*Step, name={step_name}, nlgeom=YES
** continue dt limit {segment.explicit_dt:g}s; step {segment.step_time_s:g}s
*Dynamic, Explicit
, {segment.step_time_s:.12g}
*Fixed Mass Scaling, elset=ALLSOLID, factor={segment.explicit_mass_scaling:g}, type=BELOW MIN, dt={segment.explicit_dt:g}
*Bulk Viscosity
{segment.bulk_viscosity_linear:g}, {segment.bulk_viscosity_quadratic:g}
*Boundary, type=DISPLACEMENT, op=MOD, amplitude={amp_name}
PLATE_REF, 3, 3, {disp:.12g}
*Output, field, number interval=50
*Node Output
U,
*Node Output, nset=PLATE_REF
RF,
*Node Output, nset=PLATE_FIXED_REF
RF,
*Element Output, elset=LATTICE
S, LE

*Output, history, time interval={hist_interval:.12g}
*Node Output, nset=PLATE_REF
RF, U
*Energy Output
ALLIE, ALLKE, ALLSE, ALLVD, ALLWK, ALLPD
*Node Output, nset=PLATE_FIXED_REF
RF, U
*Restart, write, overlay, number interval={segment.restart_read_interval}
** continue delta_strain={segment.delta_strain:.4f} disp={disp:.9g}/{segment.step_time_s:.9g}s
*End Step
"""
    validate_explicit_restart_inp(text)
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def write_continue_meta(
    out_path: str,
    *,
    segment: ContinueSegment,
    source_meta: dict[str, Any],
    continue_inp: str,
) -> dict[str, Any]:
    meta = dict(source_meta)
    meta.update(
        {
            "case_slug": segment.target_slug,
            "compression_displacement": float(source_meta.get("compression_displacement", 0.0))
            + segment.additional_displacement_mm,
            "step_time": segment.step_time_s,
            "step_name": "CompressionContinue",
            "restart_continue": {
                "mode": "explicit_restart_read_end_step",
                "source_slug": segment.source_slug,
                "source_strain": segment.source_strain,
                "target_strain": segment.target_strain,
                "delta_strain": segment.delta_strain,
                "additional_displacement_mm": segment.additional_displacement_mm,
                "continue_inp": continue_inp,
            },
        }
    )
    loading = dict(meta.get("loading") or {})
    loading.update(
        {
            "target_engineering_strain": segment.target_strain,
            "compression_displacement_mm": meta["compression_displacement"],
            "step_time_s": segment.step_time_s,
            "continue_from_slug": segment.source_slug,
            "continue_source_strain": segment.source_strain,
            "continue_delta_strain": segment.delta_strain,
        }
    )
    meta["loading"] = loading
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)
    return meta


def merge_stress_strain_csv_paths(
    source_csv: str,
    continue_csv: str,
    out_csv: str,
    *,
    source_meta: dict[str, Any],
    continue_meta: dict[str, Any],
) -> int:
    """Concatenate source + continue curves; shift continue strain by source end strain."""

    def _read(path: str) -> list[tuple[float, float]]:
        rows: list[tuple[float, float]] = []
        with open(path, encoding="utf-8") as f:
            header = f.readline()
            if "engineering_strain" not in header:
                raise ValueError(f"Bad CSV header: {path}")
            for line in f:
                line = line.strip()
                if not line:
                    continue
                e, s = line.split(",", 1)
                rows.append((float(e), float(s)))
        return rows

    src = _read(source_csv)
    cont = _read(continue_csv)
    if not src or not cont:
        raise ValueError("empty source or continue CSV")
    offset = source_strain_from_meta(source_meta)
    merged: list[tuple[float, float]] = list(src)
    last_e = src[-1][0]
    for e, s in cont:
        ne = offset + e
        if ne <= last_e + 1e-9:
            continue
        merged.append((ne, s))
        last_e = ne
    os.makedirs(os.path.dirname(out_csv) or ".", exist_ok=True)
    with open(out_csv, "w", encoding="utf-8", newline="\n") as f:
        f.write("engineering_strain,engineering_stress_MPa\n")
        for e, s in merged:
            f.write(f"{e},{s}\n")
    return len(merged)


def default_continue_slug(source_slug: str, target_strain: float) -> str:
    pct = int(round(float(target_strain) * 100.0))
    if re.search(r"_s\d+$", source_slug):
        return re.sub(r"_s\d+$", f"_s{pct}_cont", source_slug)
    return f"{source_slug}_s{pct}_cont"
