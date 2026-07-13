"""Q0.5 paper baseline vs fig33_v2_paper with Fig.3.3 experiment overlay.

  py -3 scripts/plot_q05_paper_baseline_vs_fig33_v2_paper.py
"""

from __future__ import annotations

import argparse
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
)

BASE = "hu_bai_sfbls_af2q0p5_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox"
CASES = (
    ("paper baseline (ContactSettle 15%)", BASE, "#1565C0", "-"),
    ("fig33_v2_paper (nosettle)", f"{BASE}_fig33_v2_paper", "#E65100", "-."),
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--png",
        default=str(REPORTS_ROOT / "fig33_v2_improve" / "q05_paper_baseline_vs_fig33_v2_paper.png"),
    )
    args = parser.parse_args()

    ref = load_fig33_reference()
    fig, ax, ax_r = create_fig33_figure()
    plot_fig33_experiment_series(ax, ref, series_key="af2q05")

    overlay_stresses: list[list[float]] = []
    for label, slug, color, ls in CASES:
        csv = ABAQUS_POST / slug / f"{slug}_stress_strain.csv"
        if not csv.is_file():
            print(f"[ERROR] Not found: {csv}")
            return 1
        eps, sig = load_csv(str(csv))
        peak_i = max(range(len(sig)), key=lambda i: sig[i])
        print(f"{label}: n={len(eps)} peak={sig[peak_i]:.4f} MPa @ eps={eps[peak_i]:.4f}")
        plot_fig33_simulation(
            ax,
            eps,
            sig,
            key="af2q05",
            label=f"AF2Q0.5 {label}",
            color=color,
            linestyle=ls,
            linewidth=2.0,
        )
        overlay_stresses.append(sig)

    autoscale_fig33_ylim_for_overlay(ax, ax_r, overlay_stresses)
    ax.legend(loc="upper left", fontsize=8, frameon=True, framealpha=0.92)
    ax.set_title("AF2Q0.5 — 实验 vs paper baseline / fig33_v2_paper")
    out = save_fig33_figure(fig, args.png)
    print("Saved:", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
