"""Overlay Q0.5 Fig.3.3 experiment vs fig33_v2_marlow partial (live ODB history)."""
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
    plot_fig33_experiment,
    plot_fig33_simulation,
    save_fig33_figure,
)

BASE = "cae_tet0p6mm80_5mmin_paperbox"
SLUG_MARLOW = f"hu_bai_sfbls_af2q0p5_L20_4x4x4_solid_cad_f_{BASE}_fig33_v2_marlow"
SLUG_EL = f"hu_bai_sfbls_af2q0p5_L20_4x4x4_solid_cad_f_{BASE}_fig33_v2_el"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--png",
        default=str(REPORTS_ROOT / "fig33_v2_marlow" / "af2q05_exp_vs_sim_partial.png"),
    )
    parser.add_argument(
        "--compare-el",
        action="store_true",
        help="Also overlay completed fig33_v2_el (linear elastic) baseline.",
    )
    args = parser.parse_args()

    ref = load_fig33_reference()
    fig, ax, ax_r = create_fig33_figure()
    plot_fig33_experiment(ax, ref, show_densification=False)

    overlay_stresses: list[list[float]] = []
    n = 0

    partial = ABAQUS_POST / SLUG_MARLOW / f"{SLUG_MARLOW}_stress_strain_partial.csv"
    full = ABAQUS_POST / SLUG_MARLOW / f"{SLUG_MARLOW}_stress_strain.csv"
    csv_path = full if full.is_file() else partial
    label_suffix = " (full)" if full.is_file() else " (partial)"
    if csv_path.is_file():
        eps, sig = load_csv(str(csv_path))
        plot_fig33_simulation(
            ax, eps, sig, key="af2q05", label=f"AF2Q0.5 Marlow{label_suffix}-仿真",
        )
        overlay_stresses.append(sig)
        n += 1
        print(f"marlow{label_suffix}: {len(eps)} pts, peak={max(sig):.4f} MPa, last strain={eps[-1]:.3f}")

    if args.compare_el:
        el_csv = ABAQUS_POST / SLUG_EL / f"{SLUG_EL}_stress_strain.csv"
        if el_csv.is_file():
            eps, sig = load_csv(str(el_csv))
            plot_fig33_simulation(
                ax, eps, sig, key="af2q05", label="AF2Q0.5 fig33_v2_el (elastic)-仿真",
            )
            overlay_stresses.append(sig)
            n += 1
            print(f"elastic baseline: {len(eps)} pts, peak={max(sig):.4f} MPa")

    if n == 0:
        print("[ERROR] no simulation curves loaded")
        return 1

    autoscale_fig33_ylim_for_overlay(ax, ax_r, overlay_stresses)
    ax.legend(loc="upper left", fontsize=8, frameon=True, framealpha=0.92)
    ax.set_title("AF2Q0.5 — 实验 vs Marlow 仿真 (partial, readOnly ODB)")
    out = save_fig33_figure(fig, args.png)
    print("Saved:", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
