"""
Plot partial BCC voxel0p5mm80_5mmin (self-contact) stress-strain from paused run.

Tries ODB extract first; if the ODB is corrupt, falls back to .sta subsampling
with ALLIE->RF3 calibration from the completed noself BCC reference case.

  py -3 scripts/plot_voxel0p5mm80_bcc_paused_stress_strain.py
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.plot_stress_strain import load_csv, plot_curve
from src.paths import ABAQUS_JOBS, ABAQUS_POST, REPORTS_ROOT
from src.postprocess.compression_curve import (
    CompressionMeta,
    build_curve_records,
    load_compression_meta,
    write_curve_csv,
)

SLUG = "hu_bai_bcc_af2q0_L20_4x4x4_solid_cad_f_voxel0p5mm80_5mmin"
NOSELF_SLUG = "hu_bai_bcc_af2q0_L20_4x4x4_solid_cad_f_voxel1mm80_25mmin_noself"
HOLD_TIME_S = 15.36  # COMP-DISP amplitude hold end (0.02 * 768 s)
HISTORY_INTERVAL_S = 7.68  # max(step_time/100, 1e-4)


def _amp_value(step_time_s: float, step_time: float = 768.0) -> float:
    if step_time_s <= HOLD_TIME_S + 1e-9:
        return 0.0
    return min(1.0, max(0.0, (step_time_s - HOLD_TIME_S) / (step_time - HOLD_TIME_S)))


def _latest_sta_path() -> Path:
    job_sta = ABAQUS_JOBS / SLUG / f"{SLUG}.sta"
    if job_sta.is_file():
        return job_sta
    failed_root = _ROOT / "output" / "failed" / SLUG
    if failed_root.is_dir():
        archives = sorted(failed_root.iterdir(), key=lambda p: p.name, reverse=True)
        for arch in archives:
            sta = arch / "jobs" / f"{SLUG}.sta"
            if sta.is_file():
                return sta
    raise FileNotFoundError(f"No .sta found for {SLUG}")


def _parse_sta_history(sta_path: Path) -> list[tuple[float, float, float]]:
    """Return (time_s, kinetic_J, total_internal_J) subsampled at history interval."""
    inc_re = re.compile(
        r"^\s+\d+\s+([\d.E+-]+)\s+([\d.E+-]+)\s+\d\d:\d\d:\d\d\s+[\d.E+-]+\s+\d+\s+"
        r"([\d.E+-]+)\s+([\d.E+-]+)\s+"
    )
    rows: list[tuple[float, float, float]] = []
    last_bucket = -1.0
    with sta_path.open(encoding="utf-8", errors="ignore") as f:
        for line in f:
            m = inc_re.match(line)
            if not m:
                continue
            t = float(m.group(2))
            ke = float(m.group(3))
            ie = float(m.group(4))
            bucket = int(t / HISTORY_INTERVAL_S)
            if bucket <= last_bucket:
                continue
            last_bucket = bucket
            rows.append((t, ke, ie))
    return rows


def _load_noself_calibration() -> tuple[list[float], list[float]]:
    """Map ALLIE (J) -> |RF3| (N) from completed noself BCC."""
    noself_sta = ABAQUS_JOBS / NOSELF_SLUG / f"{NOSELF_SLUG}.sta"
    noself_csv = ABAQUS_POST / NOSELF_SLUG / f"{NOSELF_SLUG}_stress_strain.csv"
    if not noself_sta.is_file() or not noself_csv.is_file():
        return [], []
    sta_rows = _parse_sta_history(noself_sta)
    times_sta = [r[0] for r in sta_rows]
    allie_sta = [r[2] for r in sta_rows]
    times_csv, strains, rf_abs = [], [], []
    with noself_csv.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            t = float(row["time_s"])
            times_csv.append(t)
            strains.append(float(row["engineering_strain"]))
            rf_abs.append(abs(float(row["RF3_N"])))
    if not times_csv:
        return [], []
    allie_at_csv: list[float] = []
    j = 0
    for t in times_csv:
        while j + 1 < len(times_sta) and times_sta[j + 1] <= t:
            j += 1
        allie_at_csv.append(allie_sta[min(j, len(allie_sta) - 1)])
    return allie_at_csv, rf_abs


def _calibrate_rf3(allie: float, cal_allie: list[float], cal_rf: list[float]) -> float:
    if not cal_allie or allie <= cal_allie[0]:
        return 0.0
    for i in range(1, len(cal_allie)):
        if allie <= cal_allie[i]:
            a0, a1 = cal_allie[i - 1], cal_allie[i]
            r0, r1 = cal_rf[i - 1], cal_rf[i]
            if a1 <= a0:
                return r1
            w = (allie - a0) / (a1 - a0)
            return r0 + w * (r1 - r0)
    # High-strain extrapolation: last segment slope, capped
    if len(cal_allie) >= 2:
        a0, a1 = cal_allie[-2], cal_allie[-1]
        r0, r1 = cal_rf[-2], cal_rf[-1]
        slope = (r1 - r0) / max(a1 - a0, 1e-9)
        return max(0.0, r1 + slope * (allie - a1))
    return cal_rf[-1]


def extract_from_sta(sta_path: Path, meta: CompressionMeta, csv_path: Path) -> str:
    cal_allie, cal_rf = _load_noself_calibration()
    if len(cal_allie) < 4:
        raise RuntimeError("Need noself BCC .sta + CSV for ALLIE->RF3 calibration")

    sta_rows = _parse_sta_history(sta_path)
    if len(sta_rows) < 4:
        raise RuntimeError(f"Too few .sta history points: {sta_path}")

    times: list[float] = []
    u3_mm: list[float] = []
    rf3_n: list[float] = []
    disp_mm = abs(meta.compression_displacement)
    for t, _ke, allie in sta_rows:
        if t < HOLD_TIME_S - 1e-9:
            continue
        amp = _amp_value(t, meta.step_time)
        u3 = -amp * disp_mm
        rf = _calibrate_rf3(allie, cal_allie, cal_rf)
        times.append(t)
        u3_mm.append(u3)
        rf3_n.append(-rf)

    rows = build_curve_records(
        times, u3_mm, rf3_n, meta, force_source="sta_allie_calibrated", method="paper"
    )
    write_curve_csv(rows, str(csv_path))
    return "sta_allie_calibrated"


def try_extract_odb(odb: Path, meta: Path, csv_path: Path) -> bool:
    if not odb.is_file():
        return False
    abaqus = os.environ.get("ABAQUS_CMD", "abaqus")
    extract = _ROOT / "scripts" / "extract_stress_strain_from_odb.py"
    cmd = [
        abaqus,
        "python",
        str(extract),
        "--odb",
        str(odb),
        "--meta",
        str(meta),
        "--csv",
        str(csv_path),
        "--force-mode",
        "paper",
        "--curve-method",
        "paper",
        "--no-raw",
    ]
    try:
        proc = subprocess.run(cmd, cwd=str(_ROOT), capture_output=True, text=True)
    except FileNotFoundError:
        print("[WARN] abaqus not found on PATH; skipping ODB extract")
        return False
    if proc.returncode != 0:
        tail = (proc.stdout + proc.stderr).strip().splitlines()
        print("[WARN] ODB extract failed:", tail[-1] if tail else proc.returncode)
        return False
    return csv_path.is_file() and csv_path.stat().st_size > 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Plot paused BCC voxel0p5mm80 stress-strain")
    parser.add_argument(
        "--csv",
        default=str(ABAQUS_POST / SLUG / f"{SLUG}_stress_strain_paused.csv"),
    )
    parser.add_argument(
        "--png",
        default=str(REPORTS_ROOT / "voxel0p5mm80_5mmin_bcc_paused_stress_strain.png"),
    )
    parser.add_argument("--sta", default="", help="Override .sta path")
    parser.add_argument("--show", action="store_true")
    args = parser.parse_args()

    meta_path = _ROOT / "output" / "export" / SLUG / f"{SLUG}_meta.json"
    odb_path = ABAQUS_JOBS / SLUG / f"{SLUG}.odb"
    csv_path = Path(args.csv)
    png_path = Path(args.png)
    csv_path.parent.mkdir(parents=True, exist_ok=True)

    meta = load_compression_meta(str(meta_path))
    source = ""
    if try_extract_odb(odb_path, meta_path, csv_path):
        source = "odb"
    else:
        sta_path = Path(args.sta) if args.sta else _latest_sta_path()
        print(f"[INFO] ODB unreadable; using .sta fallback: {sta_path}")
        source = extract_from_sta(sta_path, meta, csv_path)

    strains, stresses = load_csv(str(csv_path))
    if not strains:
        print("[ERROR] Empty curve")
        return 1

    peak_i = max(range(len(stresses)), key=lambda i: stresses[i])
    print(
        f"Source={source}  points={len(strains)}  "
        f"peak {stresses[peak_i]:.4f} MPa @ strain {strains[peak_i]:.4f}  "
        f"last strain {strains[-1]:.4f}"
    )

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(8, 5))
    ax.plot(strains, stresses, color="#89CFF0", linewidth=1.8, label="BCC Q=0 (paused ~70%)")
    ax.set_xlabel("Engineering strain")
    ax.set_ylabel("Engineering stress (MPa)")
    title = "BCC C3D8R voxel 0.5 mm / 5 mm/min / self-contact — paused partial curve"
    if source == "sta_allie_calibrated":
        title += "\n(stress estimated from .sta ALLIE via noself calibration; ODB corrupt)"
    ax.set_title(title, fontsize=10)
    ax.grid(True, alpha=0.35)
    ax.legend(loc="best")
    fig.tight_layout()
    png_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(png_path, dpi=150)
    plt.close(fig)
    print("Saved:", png_path)
    print("CSV:", csv_path)

    sidecar = png_path.with_suffix(".json")
    sidecar.write_text(
        json.dumps(
            {
                "slug": SLUG,
                "source": source,
                "csv": str(csv_path),
                "png": str(png_path),
                "note": "Paused run; ODB may be corrupt after hard stop.",
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
