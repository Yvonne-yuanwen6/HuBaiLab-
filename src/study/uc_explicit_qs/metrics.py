"""Metrics: KE/IE, AE/IE, initial stiffness, peak force, snap location."""

from __future__ import annotations

import csv
import math
from pathlib import Path


def _f(row: dict, *keys: str) -> float | None:
    for k in keys:
        if k in row and row[k] not in ("", None):
            try:
                return float(row[k])
            except (TypeError, ValueError):
                pass
    return None


def load_fu(path: Path) -> list[tuple[float, float]]:
    if not path.is_file():
        return []
    pts: list[tuple[float, float]] = []
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            u = _f(row, "displacement_mm", "U3_mm")
            fr = _f(row, "force_N", "RF3_N")
            if u is None or fr is None:
                continue
            pts.append((abs(u), abs(fr)))
    return pts


def load_energy(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    rows: list[dict] = []
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            t = _f(row, "time_s", "time") or 0.0
            ke = abs(_f(row, "ALLKE_J", "ALLKE") or 0.0)
            ie = _f(row, "ALLIE_J", "ALLIE") or 0.0
            ae = _f(row, "ALLAE_J", "ALLAE")
            rows.append({"t": t, "ke": ke, "ie": ie, "ae": ae})
    return rows


def fu_metrics(pts: list[tuple[float, float]]) -> dict:
    if len(pts) < 3:
        return {"ok": False, "reason": "too_few_points"}
    early = [(u, f) for u, f in pts if 0.2 < u <= 1.0]
    if len(early) < 2:
        early = pts[1 : min(8, len(pts))]
    k0 = float("nan")
    if len(early) >= 2:
        u0, f0 = early[0]
        u1, f1 = early[-1]
        if abs(u1 - u0) > 1e-9:
            k0 = (f1 - f0) / (u1 - u0)
    peak_f = max(f for _, f in pts)
    peak_u = next(u for u, f in pts if f == peak_f)

    # Snap / buckling: first local max then drop > 8% of that force.
    snap_u = float("nan")
    snap_f = float("nan")
    for i in range(2, len(pts) - 2):
        u, f = pts[i]
        if f < pts[i - 1][1] or f < pts[i + 1][1]:
            continue
        if f < 0.35 * peak_f:
            continue
        later = pts[i + 1 : min(len(pts), i + 25)]
        if later and min(x[1] for x in later) < 0.92 * f:
            snap_u, snap_f = u, f
            break
    return {
        "ok": True,
        "n": len(pts),
        "u_max_mm": pts[-1][0],
        "initial_stiffness_N_per_mm": k0,
        "peak_force_N": peak_f,
        "peak_u_mm": peak_u,
        "snap_u_mm": snap_u,
        "snap_force_N": snap_f,
    }


def energy_metrics(rows: list[dict], *, ke_ie_limit: float = 0.05) -> dict:
    if not rows:
        return {"ok": False, "reason": "empty_energy"}
    ratios_ke: list[float] = []
    ratios_ae: list[float] = []
    for r in rows:
        if r["ie"] > 1.0e-9:
            ratios_ke.append(r["ke"] / r["ie"])
            if r["ae"] is not None:
                ratios_ae.append(abs(r["ae"]) / r["ie"])
    n = len(ratios_ke)
    tail = ratios_ke[max(0, int(0.05 * n)) :] if n else []
    max_tail = max(tail) if tail else (max(ratios_ke) if ratios_ke else float("nan"))
    # Stable window: IE > 1% of peak (reduces early contact noise).
    ie_peak = max(r["ie"] for r in rows)
    stable = [
        r["ke"] / r["ie"]
        for r in rows
        if ie_peak > 0 and r["ie"] > 0.01 * ie_peak
    ]
    max_stable = max(stable) if stable else max_tail
    max_ae = max(ratios_ae) if ratios_ae else float("nan")
    qs_pass = bool(math.isfinite(max_stable) and max_stable < ke_ie_limit)
    warn = None
    if not qs_pass:
        warn = (
            f"KE/IE={100.0 * max_stable:.2f}% > {100.0 * ke_ie_limit:.1f}% — "
            "降低加载速度或调整质量缩放"
        )
    return {
        "ok": True,
        "n": len(rows),
        "allie_peak_J": ie_peak,
        "allke_peak_J": max(r["ke"] for r in rows),
        "allae_peak_J": (
            max(abs(r["ae"]) for r in rows if r["ae"] is not None)
            if any(r["ae"] is not None for r in rows)
            else None
        ),
        "max_ke_ie_after_5pct_hist": max_tail,
        "max_ke_ie_ie_gt_1pct_peak": max_stable,
        "max_ae_ie": max_ae if ratios_ae else None,
        "qs_pass": qs_pass,
        "qs_warning": warn,
        "ke_ie_limit": ke_ie_limit,
    }


def evaluate_case(
    *,
    stress_strain_csv: Path,
    energy_csv: Path,
    ke_ie_limit: float = 0.05,
) -> dict:
    pts = load_fu(Path(stress_strain_csv))
    en = load_energy(Path(energy_csv))
    return {
        "fu": fu_metrics(pts),
        "energy": energy_metrics(en, ke_ie_limit=ke_ie_limit),
        "fu_points": pts,
        "energy_rows": en,
    }
