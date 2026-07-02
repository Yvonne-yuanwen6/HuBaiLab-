"""Score Q0.5 paperbox curve vs WPD Fig.3.3 experimental trend."""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from scripts.analyze_paperbox_snapthrough import detect_snapthrough
from src.paths import ABAQUS_POST
from src.postprocess.compression_curve import HU_BAI_PAPER_DENSIFICATION_STRAIN, estimate_densification_strain
from src.postprocess.fig33_plot_style import load_fig33_reference, stress_at_strain

Q05_KEY = "af2q05"
PAPER_ED = HU_BAI_PAPER_DENSIFICATION_STRAIN["q0.5"]

# WPD checkpoints (MPa) — max sim/exp ratio allowed
CHECKPOINTS = (
    (0.20, 0.00314, 1.35),
    (0.40, 0.00572, 1.35),
    (0.55, 0.00947, 1.40),
    (0.70, 0.03465, 1.25),
)

PEAK_BAND = (0.65, 0.78)
PEAK_STRESS_MIN_MPA = 0.032
ED_LO, ED_HI = 0.74, 0.84


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


def evaluate_q05(slug: str) -> dict:
    ref = load_fig33_reference()
    ref_pts = ref["series"][Q05_KEY]["points"]
    pts = load_curve(slug)
    out: dict = {"slug": slug, "csv_found": bool(pts)}
    if not pts:
        out["q05_trend_pass"] = False
        out["reason"] = "missing_csv"
        return out

    eps = [p[0] for p in pts]
    sig = [p[1] for p in pts]
    snap = detect_snapthrough(eps, sig, band_lo=PEAK_BAND[0], band_hi=PEAK_BAND[1])
    dens = estimate_densification_strain(eps, sig)
    peak_i = max(range(len(sig)), key=lambda i: sig[i])

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

    ed_sim = dens["densification_strain"]
    ed_ok = ED_LO <= ed_sim <= ED_HI
    if not ed_ok:
        fails.append(f"eps_d={ed_sim:.3f} outside [{ED_LO},{ED_HI}] (paper {PAPER_ED})")

    peak_ok = sig[peak_i] >= PEAK_STRESS_MIN_MPA
    if not peak_ok:
        fails.append(f"peak {sig[peak_i]:.4f} MPa < {PEAK_STRESS_MIN_MPA}")

    snap_ok = snap.get("has_snapthrough", False)
    if not snap_ok:
        fails.append("no snap-through in eps 0.65-0.78 (soft)")

    out.update(
        {
            "n_points": len(pts),
            "peak_stress_MPa": sig[peak_i],
            "peak_strain": eps[peak_i],
            "stress_at_0.20_MPa": interp(pts, 0.20),
            "has_snapthrough": snap_ok,
            "snapthrough_drop_fraction": snap.get("drop_fraction"),
            "densification_strain": ed_sim,
            "paper_densification_strain": PAPER_ED,
            "checkpoints": checkpoint_results,
            "q05_trend_pass": len([f for f in fails if not f.startswith("no snap")]) == 0,
            "hard_pass": len(fails) == 0,
            "reason": "; ".join(fails) if fails else "ok",
        }
    )
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--slug", required=True)
    parser.add_argument("--write-json", default="")
    args = parser.parse_args()

    report = evaluate_q05(args.slug)
    print(json.dumps(report, indent=2))
    if args.write_json:
        os.makedirs(os.path.dirname(args.write_json) or ".", exist_ok=True)
        with open(args.write_json, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)

    return 0 if report.get("q05_trend_pass") else 1


if __name__ == "__main__":
    raise SystemExit(main())
