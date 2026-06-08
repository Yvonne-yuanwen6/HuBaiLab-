"""
Summarize Hu & Bai acceleration case manifests and post-processed curves.

  py -3 scripts/compare_hu_bai_acceleration.py
"""

from __future__ import annotations

import csv
import json
import os
import re
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HU_BAI_EXPORT = os.path.join(_ROOT, "output", "export", "hu_bai")
HU_BAI_JOBS = os.path.join(_ROOT, "output", "abaqus", "jobs", "hu_bai")
HU_BAI_POST = os.path.join(_ROOT, "output", "abaqus", "post", "hu_bai")

FULL_SLUG = "hu_bai_bcc_af2q0_L20_3x3x3_solid_cad_f"
PILOT_SLUG = "hu_bai_bcc_af2q0_L20_3x3x3_solid_cad_p"
PROFILES = [
    ("fast_45pct", "hu_bai_bcc_af2q0_L20_3x3x3_solid_cad_f_fast"),
    ("full_70pct_pair", FULL_SLUG),
    ("pilot_15pct", PILOT_SLUG),
    ("pilot_dt2e4", f"{PILOT_SLUG}_dt2e4"),
    ("pilot_qa25", f"{PILOT_SLUG}_qa25"),
]


def _read_manifest(slug: str) -> dict | None:
    path = os.path.join(HU_BAI_EXPORT, slug, "case_manifest.json")
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _sta_completed(slug: str) -> bool:
    sta = os.path.join(HU_BAI_JOBS, slug, f"{slug}.sta")
    if not os.path.isfile(sta):
        return False
    with open(sta, encoding="utf-8", errors="replace") as f:
        return "THE ANALYSIS HAS COMPLETED SUCCESSFULLY" in f.read()


def _wall_minutes_from_sta(slug: str) -> float | None:
    sta = os.path.join(HU_BAI_JOBS, slug, f"{slug}.sta")
    if not os.path.isfile(sta):
        return None
    last_wall = None
    with open(sta, encoding="utf-8", errors="replace") as f:
        for line in f:
            if "INCREMENT" in line or "Output Field" in line:
                continue
            parts = line.split()
            if len(parts) >= 4 and re.match(r"\d{2}:\d{2}:\d{2}$", parts[3]):
                last_wall = parts[3]
    if not last_wall:
        return None
    h, m, s = (int(x) for x in last_wall.split(":"))
    return h * 60 + m + s / 60.0


def _curve_peak(slug: str) -> tuple[float, float] | None:
    csv_path = os.path.join(HU_BAI_POST, slug, f"{slug}_stress_strain.csv")
    if not os.path.isfile(csv_path):
        return None
    peak_s, peak_e = 0.0, 0.0
    with open(csv_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            s = float(row["engineering_stress_MPa"])
            e = float(row["engineering_strain"])
            if s >= peak_s:
                peak_s, peak_e = s, e
    return peak_e, peak_s


def main() -> int:
    print("Hu & Bai acceleration profile comparison\n")
    header = (
        f"{'profile':<14} {'slug':<42} {'done':<5} "
        f"{'wall_min':<9} {'step_s':<7} {'dt':<8} {'n_inc':<8} "
        f"{'peak_MPa':<10} {'peak_eps':<8}"
    )
    print(header)
    print("-" * len(header))

    for label, slug in PROFILES:
        mf = _read_manifest(slug)
        load = (mf or {}).get("loading") or {}
        step_s = load.get("step_time_s", "")
        dt = load.get("explicit_dt", "")
        n_inc = load.get("explicit_n_increments_est", "")
        done = _sta_completed(slug)
        wall = _wall_minutes_from_sta(slug) if done else None
        peak = _curve_peak(slug) if done else None
        peak_s = f"{peak[1]:.4f}" if peak else "-"
        peak_e = f"{peak[0]:.4f}" if peak else "-"
        wall_s = f"{wall:.1f}" if wall is not None else ("running" if not done else "-")
        print(
            f"{label:<14} {slug:<42} {str(done):<5} "
            f"{wall_s:<9} {str(step_s):<7} {str(dt):<8} {str(n_inc):<8} "
            f"{peak_s:<10} {peak_e:<8}"
        )

    print("\nCAE: compare ALLKE vs ALLSE per profile when ODB is complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
