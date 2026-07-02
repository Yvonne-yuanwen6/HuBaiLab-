"""
Fig.3.3 experimental vs fig33_v2_el simulation — all four paper_box structures.

  py -3 scripts/plot_fig33_v2_el_overlay.py
  py -3 scripts/plot_fig33_v2_el_overlay.py --show-densification
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
    plot_fig33_experiment,
    plot_fig33_simulation,
    save_fig33_figure,
)

BASE = "cae_tet0p6mm80_5mmin_paperbox"

# (fig33 series key, slug without path)
FIG33_V2_OVERLAY = (
    ("bcc", f"hu_bai_bcc_af2q0_L20_4x4x4_solid_cad_f_{BASE}_fig33_v2_el"),
    ("af2q05", f"hu_bai_sfbls_af2q0p5_L20_4x4x4_solid_cad_f_{BASE}_fig33_v2_el"),
    ("af2q1", f"hu_bai_sfbls_af2q1_L20_4x4x4_solid_cad_f_{BASE}_fig33_v2_el"),
    ("af2q15", f"hu_bai_sfbls_af2q1p5_L20_4x4x4_solid_cad_f_{BASE}_q15_v2_el"),
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--png",
        default=str(REPORTS_ROOT / "fig33_v2_el_exp_vs_sim_all.png"),
    )
    parser.add_argument(
        "--show-densification",
        action="store_true",
        help="Show paper §3.3.1 densification markers on experiment curves",
    )
    parser.add_argument(
        "--per-structure",
        action="store_true",
        help="Also write one PNG per structure under output/reports/fig33_v2_el/",
    )
    args = parser.parse_args()

    ref = load_fig33_reference()
    fig, ax, _ax_r = create_fig33_figure()
    plot_fig33_experiment(ax, ref, show_densification=args.show_densification)

    overlay_stresses: list[list[float]] = []
    n = 0
    for key, slug in FIG33_V2_OVERLAY:
        csv = ABAQUS_POST / slug / f"{slug}_stress_strain.csv"
        if not csv.is_file():
            print(f"[WARN] missing {csv}")
            continue
        eps, sig = load_csv(str(csv))
        plot_fig33_simulation(ax, eps, sig, key=key)
        overlay_stresses.append(sig)
        n += 1
        print(f"overlay {key}: {len(eps)} pts, peak={max(sig):.4f} MPa")

    if n == 0:
        print("[ERROR] no simulation curves loaded")
        return 1

    if overlay_stresses:
        autoscale_fig33_ylim_for_overlay(ax, _ax_r, overlay_stresses)

    ax.legend(loc="upper left", fontsize=7, frameon=True, framealpha=0.92, ncol=1)
    ax.set_title("Fig.3.3 — 实验 vs 仿真 (fig33_v2_el, 线弹性+自接触)")

    out = save_fig33_figure(fig, args.png)
    print("Saved:", out)

    if args.per_structure:
        out_dir = REPORTS_ROOT / "fig33_v2_el"
        out_dir.mkdir(parents=True, exist_ok=True)
        for key, slug in FIG33_V2_OVERLAY:
            csv = ABAQUS_POST / slug / f"{slug}_stress_strain.csv"
            if not csv.is_file():
                continue
            fig_i, ax_i, ax_r_i = create_fig33_figure()
            plot_fig33_experiment(ax_i, ref, show_densification=args.show_densification)
            eps, sig = load_csv(str(csv))
            plot_fig33_simulation(ax_i, eps, sig, key=key)
            autoscale_fig33_ylim_for_overlay(ax_i, ax_r_i, [sig])
            ax_i.legend(loc="upper left", fontsize=8, frameon=True, framealpha=0.92)
            lab = ref["series"][key]["label"]
            ax_i.set_title(f"{lab} — 实验 vs fig33_v2_el")
            p = out_dir / f"{key}_exp_vs_sim.png"
            save_fig33_figure(fig_i, str(p))
            print("Saved:", p)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
