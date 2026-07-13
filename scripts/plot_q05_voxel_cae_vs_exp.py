"""
AF2Q0.5 — Fig.3.3 experiment vs voxel 0.6 / CAE baseline / Marlow.

  py -3 scripts/plot_q05_voxel_cae_vs_exp.py
  py -3 scripts/plot_q05_voxel_cae_vs_exp.py --ymax 0.10   # zoom low-stress band
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.plot_stress_strain import load_csv
from src.paths import ABAQUS_POST, REPORTS_ROOT
from src.postprocess.fig33_plot_style import (
    autoscale_fig33_ylim_for_overlay,
    create_fig33_figure,
    load_fig33_reference,
    plot_fig33_experiment_series,
    save_fig33_figure,
    set_fig33_ylim,
)

# (slug, label, color, linestyle, linewidth)
_CASES = (
    (
        "hu_bai_sfbls_af2q0p5_L20_4x4x4_solid_cad_f_voxel0p6mm80_5mmin_autodt",
        "voxel 0.6 mm autodt (solid_merged, C3D8R)",
        "#E65100",
        "-.",
        2.2,
    ),
    (
        "hu_bai_sfbls_af2q0p5_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox",
        "CAE baseline (paper_box, C3D4, settle15%)",
        "#C62828",
        "--",
        2.6,
    ),
    (
        "hu_bai_sfbls_af2q0p5_L20_4x4x4_solid_cad_f_test_marlow",
        "Marlow (Fig.2.5, CAE mesh, settle5%)",
        "#2E7D32",
        ":",
        2.4,
    ),
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Q0.5 voxel vs CAE vs Marlow vs experiment")
    parser.add_argument(
        "--png",
        default=str(REPORTS_ROOT / "q05_all" / "q05_voxel06_cae_vs_exp.png"),
    )
    parser.add_argument(
        "--ymax",
        type=float,
        default=None,
        help="Override Y max [MPa]; e.g. 0.10 to emphasize exp/CAE/Marlow",
    )
    args = parser.parse_args()

    ref = load_fig33_reference()
    fig, ax, ax_r = create_fig33_figure(figsize=(10, 6))
    plot_fig33_experiment_series(ax, ref, series_key="af2q05", linewidth=2.4)

    overlay_stresses: list[list[float]] = []
    for slug, label, color, ls, lw in _CASES:
        csv_path = ABAQUS_POST / slug / f"{slug}_stress_strain.csv"
        if not csv_path.is_file():
            print(f"[ERROR] Missing: {csv_path}")
            return 1
        eps, sig = load_csv(str(csv_path))
        if not eps:
            print(f"[ERROR] Empty: {csv_path}")
            return 1
        ax.plot(eps, sig, color=color, linestyle=ls, linewidth=lw, label=label, zorder=3)
        overlay_stresses.append(sig)
        peak_i = sig.index(max(sig))
        print(f"{label}: {len(eps)} pts, peak={max(sig):.4f} MPa @ eps={eps[peak_i]:.3f}")

    if args.ymax is not None:
        set_fig33_ylim(ax, ax_r, float(args.ymax), ref=ref)
    else:
        autoscale_fig33_ylim_for_overlay(ax, ax_r, overlay_stresses, ref=ref)

    ax.set_title("AF2Q0.5 — Fig.3.3 实验 vs voxel 0.6 / CAE baseline / Marlow")
    ax.legend(loc="upper left", fontsize=8.5, frameon=True)
    out = save_fig33_figure(fig, args.png)
    print(f"Saved: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
