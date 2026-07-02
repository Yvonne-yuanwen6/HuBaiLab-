"""
Detect snap-through (post-peak stress drop) in paperbox stress-strain CSVs.

  py -3 scripts/analyze_paperbox_snapthrough.py
  py -3 scripts/analyze_paperbox_snapthrough.py --write-summary output/logs/paperbox_snapthrough_summary.json
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from src.paths import ABAQUS_POST, REPORTS_ROOT
from src.postprocess.compression_curve import estimate_densification_strain

BASE_SUFFIX = "cae_tet0p6mm80_5mmin_paperbox"
VARIANTS = (
    ("baseline", BASE_SUFFIX),
    ("B_nosettle", f"{BASE_SUFFIX}_paperbox_nosettle"),
    ("C_settle5p", f"{BASE_SUFFIX}_paperbox_settle5p"),
    ("D_dt1e4", f"{BASE_SUFFIX}_paperbox_nosettle_dt1e4"),
    ("E_nohold", f"{BASE_SUFFIX}_paperbox_nosettle_dt1e4_nohold"),
)
CASES = (
    ("BCC Q=0", "bcc_af2q0"),
    ("SFBLS Q=0.5", "sfbls_af2q0p5"),
)


def load_curve(slug: str) -> tuple[list[float], list[float]] | None:
    csv_path = ABAQUS_POST / slug / f"{slug}_stress_strain.csv"
    if not csv_path.is_file():
        return None
    rows = list(csv.DictReader(open(csv_path, encoding="utf-8")))
    if not rows:
        return None
    eps = [float(r["engineering_strain"]) for r in rows]
    sig = [float(r["engineering_stress_MPa"]) for r in rows]
    return eps, sig


def detect_snapthrough(
    strains: list[float],
    stresses: list[float],
    *,
    band_lo: float = 0.35,
    band_hi: float = 0.78,
    min_drop_frac: float = 0.05,
) -> dict:
    n = len(strains)
    if n < 5:
        return {"has_snapthrough": False, "reason": "too_few_points"}

    peak_i = -1
    peak_s = -1.0
    for i in range(n):
        if band_lo <= strains[i] <= band_hi and stresses[i] > peak_s:
            peak_s = stresses[i]
            peak_i = i

    if peak_i < 0:
        return {"has_snapthrough": False, "reason": "no_peak_in_band"}

    min_after = peak_s
    min_i = peak_i
    for j in range(peak_i + 1, n):
        if strains[j] > band_hi:
            break
        if stresses[j] < min_after:
            min_after = stresses[j]
            min_i = j

    drop = (peak_s - min_after) / peak_s if peak_s > 1e-12 else 0.0
    has = drop >= min_drop_frac and min_i > peak_i
    return {
        "has_snapthrough": has,
        "peak_strain": strains[peak_i],
        "peak_stress_MPa": peak_s,
        "trough_strain": strains[min_i] if min_i > peak_i else None,
        "trough_stress_MPa": min_after if min_i > peak_i else None,
        "drop_fraction": drop,
    }


def slug_for(tag: str, suffix: str) -> str:
    return f"hu_bai_{tag}_L20_4x4x4_solid_cad_f_{suffix}"


def analyze_all() -> list[dict]:
    out: list[dict] = []
    for label, tag in CASES:
        for vlabel, suffix in VARIANTS:
            slug = slug_for(tag, suffix)
            curve = load_curve(slug)
            row: dict = {
                "case": label,
                "variant": vlabel,
                "slug": slug,
                "csv_found": curve is not None,
            }
            if curve is None:
                row["status"] = "missing_csv"
                out.append(row)
                continue
            eps, sig = curve
            snap = detect_snapthrough(eps, sig)
            dens = estimate_densification_strain(eps, sig)
            row.update(
                {
                    "status": "ok",
                    "n_points": len(eps),
                    "peak_stress_MPa": max(sig),
                    "peak_strain": eps[sig.index(max(sig))],
                    "densification_strain": dens["densification_strain"],
                    "densification_stress_MPa": dens["densification_stress_MPa"],
                    **snap,
                }
            )
            out.append(row)
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write-summary", default="")
    parser.add_argument("--slug", default="", help="Analyze one slug only")
    parser.add_argument("--write-json", default="")
    args = parser.parse_args()

    if args.slug:
        curve = load_curve(args.slug)
        if curve is None:
            print(f"[ERROR] missing CSV for {args.slug}")
            return 1
        eps, sig = curve
        snap = detect_snapthrough(eps, sig, band_lo=0.65, band_hi=0.78)
        dens = estimate_densification_strain(eps, sig)
        row = {"slug": args.slug, **snap, "densification_strain": dens["densification_strain"]}
        print(json.dumps(row, indent=2))
        if args.write_json:
            os.makedirs(os.path.dirname(args.write_json) or ".", exist_ok=True)
            with open(args.write_json, "w", encoding="utf-8") as f:
                json.dump(row, f, indent=2)
        return 0

    rows = analyze_all()
    print(f"{'case':<14} {'variant':<12} {'snap':<5} {'drop%':<7} {'peak@band':<18} {'εd':<6} {'csv'}")
    print("-" * 90)
    for r in rows:
        if r.get("status") != "ok":
            print(f"{r['case']:<14} {r['variant']:<12} {'—':<5} {'—':<7} {'—':<18} {'—':<6} {r['status']}")
            continue
        snap = "YES" if r.get("has_snapthrough") else "no"
        drop = 100 * float(r.get("drop_fraction") or 0)
        peak_band = f"{r.get('peak_stress_MPa', 0):.4f}@{r.get('peak_strain', 0):.3f}"
        ed = r.get("densification_strain", float("nan"))
        print(
            f"{r['case']:<14} {r['variant']:<12} {snap:<5} {drop:6.1f} {peak_band:<18} {ed:5.3f} ok"
        )

    if args.write_summary:
        os.makedirs(os.path.dirname(args.write_summary) or ".", exist_ok=True)
        with open(args.write_summary, "w", encoding="utf-8") as f:
            json.dump(rows, f, indent=2)
        print(f"\nWrote {args.write_summary}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
