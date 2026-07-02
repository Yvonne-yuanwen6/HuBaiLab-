"""
Recreate Hu & Bai Fig.3.3 experimental reference (hand-traced) as project standard figure.

  py -3 scripts/plot_hu_bai_fig33_standard.py
  py -3 scripts/plot_hu_bai_fig33_standard.py --overlay-completed
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
    FIG33_PAPER_YMAX_MPA,
    autoscale_fig33_ylim_for_overlay,
    create_fig33_figure,
    load_fig33_reference,
    plot_fig33_experiment,
    plot_fig33_simulation,
    save_fig33_figure,
)

# Best completed slug per Fig.3.3 series (settle5p where available)
_OVERLAY_COMPLETED = (
    ("bcc", "hu_bai_bcc_af2q0_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox"),
    ("af2q05", "hu_bai_sfbls_af2q0p5_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox_paperbox_settle5p"),
    ("af2q1", "hu_bai_sfbls_af2q1_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox_paperbox_settle5p"),
    ("af2q15", "hu_bai_sfbls_af2q1p5_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox"),
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Plot Hu & Bai Fig.3.3 standard reference")
    parser.add_argument(
        "--png",
        default=str(REPORTS_ROOT / "hu_bai_fig33_experiment_standard.png"),
    )
    parser.add_argument(
        "--show-densification",
        action="store_true",
        help="Annotate paper §3.3.1 densification points (εd from thesis, σ from digitized curve)",
    )
    parser.add_argument(
        "--overlay-completed",
        action="store_true",
        help="Overlay latest completed paperbox sim curves (dashed); Y axis auto-expands",
    )
    parser.add_argument(
        "--paper-ylim",
        action="store_true",
        help="With --overlay-completed, keep paper Y max (0.04 MPa) even if sim curves clip",
    )
    parser.add_argument(
        "--ylim-max",
        type=float,
        default=None,
        metavar="MPA",
        help="Manual Y-axis max (MPa); default: paper 0.04, or auto-fit when overlaying",
    )
    args = parser.parse_args()

    ref = load_fig33_reference()
    fig, ax, ax_right = create_fig33_figure()
    plot_fig33_experiment(ax, ref, show_densification=args.show_densification)

    overlay_stresses: list[list[float]] = []
    if args.overlay_completed:
        for key, slug in _OVERLAY_COMPLETED:
            csv = ABAQUS_POST / slug / f"{slug}_stress_strain.csv"
            if not csv.is_file():
                print(f"[WARN] no sim csv: {csv}")
                continue
            eps, sig = load_csv(str(csv))
            plot_fig33_simulation(ax, eps, sig, key=key)
            overlay_stresses.append(sig)
            print(f"overlay {key}: {len(eps)} pts, peak={max(sig):.4f} MPa")

        if args.ylim_max is not None:
            from src.postprocess.fig33_plot_style import set_fig33_ylim

            ymax = float(args.ylim_max)
            set_fig33_ylim(ax, ax_right, ymax, ref=ref)
            print(f"ylim max: {ymax:.3f} MPa (manual)")
        elif not args.paper_ylim and overlay_stresses:
            ymax = autoscale_fig33_ylim_for_overlay(ax, ax_right, overlay_stresses, ref=ref)
            ax.axhline(
                FIG33_PAPER_YMAX_MPA,
                color="gray",
                linestyle="--",
                linewidth=0.9,
                alpha=0.65,
                zorder=1,
                label=f"论文纵轴 {FIG33_PAPER_YMAX_MPA:g} MPa",
            )
            print(f"ylim max: {ymax:.3f} MPa (auto-fit overlay)")

    ax.legend(loc="upper left", frameon=True, framealpha=0.92, fontsize=9, edgecolor="black")
    out = save_fig33_figure(fig, args.png)
    print("Saved:", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
