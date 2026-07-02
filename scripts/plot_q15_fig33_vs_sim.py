"""
Overlay Q1.5 experimental (WPD) vs simulation on Fig.3.3 axes.

  py -3 scripts/plot_q15_fig33_vs_sim.py
  py -3 scripts/plot_q15_fig33_vs_sim.py --variant q15_fig33_v1_nosettle_noself_elastic
"""
from __future__ import annotations

import argparse
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from scripts.evaluate_paperbox_q15_trend import slug_q15
from scripts.plot_stress_strain import load_csv
from src.paths import ABAQUS_POST, REPORTS_ROOT
from src.postprocess.fig33_plot_style import (
    create_fig33_figure,
    load_fig33_reference,
    plot_fig33_experiment,
    plot_fig33_simulation,
    save_fig33_figure,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--variant",
        action="append",
        default=[],
        help="Variant suffix under paperbox base (repeatable). Default: baseline only.",
    )
    parser.add_argument(
        "--show-densification",
        action="store_true",
        help="Show paper §3.3.1 densification markers on experiment curves",
    )
    parser.add_argument(
        "--partial",
        action="store_true",
        help="Use *_stress_strain_partial.csv (live ODB snapshot while job runs).",
    )
    parser.add_argument(
        "--png",
        default=str(REPORTS_ROOT / "q15_fig33_exp_vs_sim.png"),
    )
    args = parser.parse_args()

    ref = load_fig33_reference()
    fig, ax, _ax_r = create_fig33_figure()
    plot_fig33_experiment(ax, ref, show_densification=args.show_densification)

    variants = args.variant or ["", "q15_v1_ns_el"]
    n = 0
    for v in variants:
        slug = slug_q15(v)
        stem = f"{slug}_stress_strain_partial" if args.partial else f"{slug}_stress_strain"
        csv = ABAQUS_POST / slug / f"{stem}.csv"
        if not csv.is_file():
            print(f"[WARN] missing {csv}")
            continue
        eps, sig = load_csv(str(csv))
        label = "Q15 baseline (self-contact ON)" if not v else f"Q15 {v}"
        if args.partial:
            label += " (partial)"
        plot_fig33_simulation(ax, eps, sig, key="af2q15", label=label + "-仿真")
        n += 1
        print(f"overlay {slug}: {len(eps)} pts, peak={max(sig):.4f} MPa")

    if n == 0:
        print("[ERROR] no simulation curves loaded")
        return 1

    ax.legend(loc="upper left", fontsize=8, frameon=True, framealpha=0.92)
    ax.set_title("AF2Q15 — 实验 vs 仿真（Fig.3.3 坐标）")
    out = save_fig33_figure(fig, args.png)
    print("Saved:", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
