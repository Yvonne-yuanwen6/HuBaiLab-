"""
Overlay Q1 experimental (WPD) vs simulation on Fig.3.3 axes.

  py -3 scripts/plot_q1_fig33_vs_sim.py
  py -3 scripts/plot_q1_fig33_vs_sim.py --variant fig33_v2_el
"""
from __future__ import annotations

import argparse
import math
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from scripts.plot_stress_strain import load_csv
from src.paths import ABAQUS_POST, REPORTS_ROOT
from src.postprocess.fig33_plot_style import (
    autoscale_fig33_ylim_for_overlay,
    create_fig33_figure,
    load_fig33_reference,
    plot_fig33_experiment_series,
    plot_fig33_simulation,
    save_fig33_figure,
    stress_at_strain,
)

_BASE = "hu_bai_sfbls_af2q1_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox"


def slug_q1(variant_suffix: str = "") -> str:
    if not variant_suffix:
        return _BASE
    return f"{_BASE}_{variant_suffix}"


def _rmse_vs_exp(ref_pts: list[tuple[float, float]], eps: list[float], sig: list[float]) -> float:
    if not eps:
        return float("nan")
    err2 = 0.0
    n = 0
    for e, s in zip(eps, sig):
        exp_s = stress_at_strain(ref_pts, e)
        if exp_s is None:
            continue
        d = s - exp_s
        err2 += d * d
        n += 1
    return math.sqrt(err2 / n) if n else float("nan")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--variant",
        action="append",
        default=[],
        help="Variant suffix under paperbox base (default: fig33_v2_el).",
    )
    parser.add_argument(
        "--show-densification",
        action="store_true",
        help="Show paper §3.3.1 densification markers on experiment curves",
    )
    parser.add_argument(
        "--png",
        default=str(REPORTS_ROOT / "q1_fig33_exp_vs_sim.png"),
    )
    args = parser.parse_args()

    variants = args.variant or ["fig33_v2_el"]
    ref = load_fig33_reference()
    exp_pts = ref["series"]["af2q1"]["points"]

    fig, ax, ax_r = create_fig33_figure()
    plot_fig33_experiment_series(ax, ref, series_key="af2q1")

    overlay_stresses: list[list[float]] = []
    n = 0
    for v in variants:
        slug = slug_q1(v)
        csv = ABAQUS_POST / slug / f"{slug}_stress_strain.csv"
        partial = ABAQUS_POST / slug / f"{slug}_stress_strain_partial.csv"
        if not csv.is_file() and partial.is_file():
            csv = partial
            partial_tag = " (partial)"
        else:
            partial_tag = ""
        if not csv.is_file():
            print(f"[WARN] missing {csv}")
            continue
        eps, sig = load_csv(str(csv))
        label = v or "baseline"
        plot_fig33_simulation(ax, eps, sig, key="af2q1", label=f"Q1 {label}{partial_tag}-仿真")
        overlay_stresses.append(sig)
        rmse = _rmse_vs_exp(exp_pts, eps, sig)
        n += 1
        print(f"overlay {slug}: {len(eps)} pts, peak={max(sig):.4f} MPa, rmse={rmse:.4f}")

    if n == 0:
        print("[ERROR] no simulation curves loaded")
        return 1

    autoscale_fig33_ylim_for_overlay(ax, ax_r, overlay_stresses, ref=ref)
    ax.legend(loc="upper left", fontsize=8, frameon=True, framealpha=0.92)
    ax.set_title("AF2Q1 — 实验 vs 仿真（Fig.3.3 坐标）")
    out = save_fig33_figure(fig, args.png)
    print("Saved:", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
