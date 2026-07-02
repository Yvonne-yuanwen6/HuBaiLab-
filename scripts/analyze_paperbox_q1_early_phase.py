"""Compare early-phase stress ranking for Q1 paperbox diagnostic variants."""
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

_BASE = "hu_bai_sfbls_af2q1_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox"
_VARIANTS = (
    ("baseline (settle15%)", _BASE, _BASE),
    ("settle5p", f"{_BASE}_paperbox_settle5p", f"{_BASE}_paperbox_settle5p"),
    ("nosettle_dt1e4", f"{_BASE}_paperbox_nosettle_dt1e4", f"{_BASE}_paperbox_nosettle_dt1e4"),
    ("settle5p_dt1e4", f"{_BASE}_paperbox_settle5p_dt1e4", f"{_BASE}_paperbox_settle5p_dt1e4"),
    ("q1_rods4", f"{_BASE}_paperbox_q1_rods4", f"{_BASE}_paperbox_q1_rods4"),
)
_STRAINS = (0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.45)


def load_curve(slug: str) -> list[tuple[float, float]]:
    path = ABAQUS_POST / slug / f"{slug}_stress_strain.csv"
    if not path.is_file():
        return []
    pts: list[tuple[float, float]] = []
    with open(path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            pts.append((float(row["engineering_strain"]), float(row["engineering_stress_MPa"])))
    return pts


def interp(pts: list[tuple[float, float]], target: float) -> float | None:
    if not pts:
        return None
    for i in range(1, len(pts)):
        e0, s0 = pts[i - 1]
        e1, s1 = pts[i]
        if e1 >= target:
            if e1 == e0:
                return s1
            return s0 + (s1 - s0) * (target - e0) / (e1 - e0)
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write-summary", default="")
    args = parser.parse_args()

    rows: list[dict] = []
    for label, slug, _ in _VARIANTS:
        pts = load_curve(slug)
        if not pts:
            print(f"[WARN] missing curve: {slug}")
            continue
        peak_early = max((s for e, s in pts if e <= 0.40), default=float("nan"))
        entry = {
            "label": label,
            "slug": slug,
            "n_points": len(pts),
            "peak_stress_eps_le_0.40_MPa": peak_early,
            "stress_at_strain": {},
        }
        for eps in _STRAINS:
            entry["stress_at_strain"][f"{eps:.2f}"] = interp(pts, eps)
        rows.append(entry)
        print(
            f"{label}: {len(pts)} pts, peak<=0.40={peak_early:.4f} MPa, "
            f"σ@0.20={entry['stress_at_strain'].get('0.20')}"
        )

    if args.write_summary:
        os.makedirs(os.path.dirname(args.write_summary) or ".", exist_ok=True)
        with open(args.write_summary, "w", encoding="utf-8") as f:
            json.dump({"variants": rows, "strain_checkpoints": list(_STRAINS)}, f, indent=2)
        print("Wrote:", args.write_summary)

    # quick ranking at eps=0.20
    ranked = sorted(
        ((r["label"], r["stress_at_strain"].get("0.20")) for r in rows),
        key=lambda x: (x[1] is None, -(x[1] or 0)),
    )
    if ranked:
        print("\nRanking at ε=0.20 (higher = stiffer early phase):")
        for i, (lab, s) in enumerate(ranked, 1):
            print(f"  {i}. {lab}: {s:.4f} MPa" if s is not None else f"  {i}. {lab}: NA")

    return 0 if rows else 1


if __name__ == "__main__":
    raise SystemExit(main())
