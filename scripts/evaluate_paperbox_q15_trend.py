"""Score Q1.5 paperbox curve vs WPD Fig.3.3 experimental trend (wave + eps_d)."""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from src.paths import ABAQUS_POST
from src.postprocess.compression_curve import (
    HU_BAI_PAPER_DENSIFICATION_STRAIN,
    estimate_densification_strain,
)
from src.postprocess.fig33_plot_style import load_fig33_reference, stress_at_strain

Q15_KEY = "af2q15"
PAPER_ED = HU_BAI_PAPER_DENSIFICATION_STRAIN["q1.5"]

# WPD experiment checkpoints (MPa) — from digitized Fig.3.3
CHECKPOINTS = (
    (0.20, 0.0026, 1.5),
    (0.40, 0.0054, 1.5),
    (0.56, 0.0060, 1.5),
    (0.75, 0.0203, 1.5),
)

WAVE_PEAK_BAND = (0.38, 0.48)
WAVE_TROUGH_BAND = (0.50, 0.58)
SECOND_PEAK_BAND = (0.60, 0.68)


def slug_q15(variant_suffix: str = "") -> str:
    base = "hu_bai_sfbls_af2q1p5_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox"
    if variant_suffix:
        return f"{base}_{variant_suffix}"
    return base


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
    for i in range(1, len(pts)):
        e0, s0 = pts[i - 1]
        e1, s1 = pts[i]
        if e1 >= target:
            if e1 == e0:
                return s1
            return s0 + (s1 - s0) * (target - e0) / (e1 - e0)
    return None


def local_extrema(
    pts: list[tuple[float, float]],
    band: tuple[float, float],
    kind: str,
) -> dict | None:
    lo, hi = band
    in_band = [(e, s, i) for i, (e, s) in enumerate(pts) if lo <= e <= hi]
    if len(in_band) < 3:
        return None
    best = None
    for j in range(1, len(in_band) - 1):
        e, s, idx = in_band[j]
        _, sp, _ = in_band[j - 1]
        _, sn, _ = in_band[j + 1]
        if kind == "peak" and s >= sp and s >= sn:
            if best is None or s > best["stress_MPa"]:
                best = {"strain": e, "stress_MPa": s, "index": idx}
        if kind == "trough" and s <= sp and s <= sn:
            if best is None or s < best["stress_MPa"]:
                best = {"strain": e, "stress_MPa": s, "index": idx}
    return best


def evaluate_q15(slug: str) -> dict:
    ref = load_fig33_reference()
    ref_pts = ref["series"][Q15_KEY]["points"]
    pts = load_curve(slug)
    out: dict = {"slug": slug, "csv_found": bool(pts)}
    if not pts:
        out["q15_trend_pass"] = False
        out["reason"] = "missing_csv"
        return out

    eps = [p[0] for p in pts]
    sig = [p[1] for p in pts]
    peak_i = max(range(len(sig)), key=lambda i: sig[i])
    dens = estimate_densification_strain(eps, sig)

    wave_peak = local_extrema(pts, WAVE_PEAK_BAND, "peak")
    wave_trough = local_extrema(pts, WAVE_TROUGH_BAND, "trough")
    second_peak = local_extrema(pts, SECOND_PEAK_BAND, "peak")

    checkpoint_results = []
    fails: list[str] = []
    for strain, ref_stress, max_ratio in CHECKPOINTS:
        sim_s = interp(pts, strain)
        ref_s = stress_at_strain(ref_pts, strain)
        ratio = (sim_s / ref_s) if sim_s is not None and ref_s and ref_s > 1e-12 else None
        ok = ratio is not None and ratio <= max_ratio
        checkpoint_results.append(
            {
                "strain": strain,
                "sim_MPa": sim_s,
                "ref_MPa": ref_s,
                "ratio": ratio,
                "pass": ok,
            }
        )
        if not ok:
            fails.append(f"eps={strain:.2f} ratio={ratio:.2f} (max {max_ratio})")

    ed_lo, ed_hi = 0.50, 0.62
    ed_sim = dens["densification_strain"]
    ed_ok = ed_lo <= ed_sim <= ed_hi
    if not ed_ok:
        fails.append(f"eps_d={ed_sim:.3f} outside [{ed_lo},{ed_hi}] (paper {PAPER_ED})")

    wave_ok = wave_peak is not None and wave_trough is not None
    if not wave_ok:
        fails.append("missing wave peak/trough in eps 0.38-0.58")
    elif wave_peak["stress_MPa"] <= wave_trough["stress_MPa"]:
        fails.append("wave peak not above trough")

    out.update(
        {
            "n_points": len(pts),
            "peak_stress_MPa": sig[peak_i],
            "peak_strain": eps[peak_i],
            "densification_strain": ed_sim,
            "densification_stress_MPa": dens["densification_stress_MPa"],
            "paper_densification_strain": PAPER_ED,
            "wave_peak": wave_peak,
            "wave_trough": wave_trough,
            "second_peak": second_peak,
            "checkpoints": checkpoint_results,
            "q15_trend_pass": len(fails) == 0,
            "failures": fails,
            "reason": "; ".join(fails) if fails else "ok",
        }
    )
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate Q1.5 vs Fig.3.3 experimental trend")
    parser.add_argument("--slug", default="", help="Full slug (overrides --variant-suffix)")
    parser.add_argument(
        "--variant-suffix",
        default="",
        help="e.g. q15_v1_ns_el",
    )
    parser.add_argument(
        "--write-json",
        default="",
        help="Write report JSON (e.g. output/logs/q15_fig33_eval.json)",
    )
    args = parser.parse_args()

    slug = args.slug or slug_q15(args.variant_suffix)
    report = evaluate_q15(slug)
    print(json.dumps(report, indent=2, ensure_ascii=False))

    if args.write_json:
        os.makedirs(os.path.dirname(args.write_json) or ".", exist_ok=True)
        with open(args.write_json, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        print("Wrote:", args.write_json)

    return 0 if report.get("q15_trend_pass") else 1


if __name__ == "__main__":
    raise SystemExit(main())
