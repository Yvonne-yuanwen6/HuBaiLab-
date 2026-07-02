"""Q0.5 snap-through diagnostic overlay vs Fig.3.3 experiment."""
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

BASE = "cae_tet0p6mm80_5mmin_paperbox"
PREFIX = f"hu_bai_sfbls_af2q0p5_L20_4x4x4_solid_cad_f_{BASE}"

# (legend label, slug suffix)
SNAP_VARIANTS = (
    ("snap s78 el (baseline)", f"{PREFIX}_fig33_snap_s78_el"),
    ("snap s78 s0=0.08 ★", f"{PREFIX}_fig33_snap_s78_s0_08"),
    ("snap s78 s0=0.12", f"{PREFIX}_fig33_snap_s78_s0_12"),
    ("snap s78 settle2p", f"{PREFIX}_fig33_snap_s78_settle2p"),
    ("fig33_v2_el (full 80%)", f"{PREFIX}_fig33_v2_el"),
)

STYLES = {
    "snap s78 el (baseline)": {"color": "#212121", "linestyle": "--", "linewidth": 2.0},
    "snap s78 s0=0.08 ★": {"color": "#E65100", "linestyle": "-", "linewidth": 2.2},
    "snap s78 s0=0.12": {"color": "#6A1B9A", "linestyle": "-.", "linewidth": 2.0},
    "snap s78 settle2p": {"color": "#00838F", "linestyle": ":", "linewidth": 2.2},
    "fig33_v2_el (full 80%)": {"color": "#1565C0", "linestyle": (0, (4, 2)), "linewidth": 1.8},
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--png",
        default=str(REPORTS_ROOT / "fig33_snap_diag" / "af2q05_exp_vs_sim_all.png"),
    )
    parser.add_argument("--per-variant", action="store_true")
    args = parser.parse_args()

    ref = load_fig33_reference()
    fig, ax, ax_r = create_fig33_figure()
    plot_fig33_experiment_series(ax, ref, series_key="af2q05")

    overlay_stresses: list[list[float]] = []
    loaded = 0
    for label, slug in SNAP_VARIANTS:
        csv = ABAQUS_POST / slug / f"{slug}_stress_strain.csv"
        if not csv.is_file():
            print(f"[WARN] missing {csv}")
            continue
        eps, sig = load_csv(str(csv))
        style = STYLES.get(label, {"color": "#555555", "linestyle": "--", "linewidth": 1.8})
        plot_fig33_simulation(
            ax, eps, sig, key="af2q05", label=f"AF2Q0.5 {label}-仿真",
            color=style["color"], linestyle=style["linestyle"], linewidth=style["linewidth"],
        )
        overlay_stresses.append(sig)
        loaded += 1
        peak_i = sig.index(max(sig))
        print(f"{label}: {len(eps)} pts peak={max(sig):.4f} MPa @ eps={eps[peak_i]:.3f}")

    if loaded == 0:
        print("[ERROR] no curves loaded")
        return 1

    autoscale_fig33_ylim_for_overlay(ax, ax_r, overlay_stresses)
    ax.legend(loc="upper left", fontsize=7, frameon=True, framealpha=0.92)
    ax.set_title("AF2Q0.5 — 实验 vs snap 接触扫参 (ε≤0.78)")
    out = save_fig33_figure(fig, args.png)
    print("Saved:", out)

    if args.per_variant:
        out_dir = REPORTS_ROOT / "fig33_snap_diag"
        out_dir.mkdir(parents=True, exist_ok=True)
        for label, slug in SNAP_VARIANTS:
            csv = ABAQUS_POST / slug / f"{slug}_stress_strain.csv"
            if not csv.is_file():
                continue
            fig_i, ax_i, ax_r_i = create_fig33_figure()
            plot_fig33_experiment_series(ax_i, ref, series_key="af2q05")
            eps, sig = load_csv(str(csv))
            style = STYLES.get(label, {"color": "#555555", "linestyle": "--", "linewidth": 1.8})
            plot_fig33_simulation(
                ax_i, eps, sig, key="af2q05", label=f"AF2Q0.5 {label}-仿真",
                color=style["color"], linestyle=style["linestyle"], linewidth=style["linewidth"],
            )
            autoscale_fig33_ylim_for_overlay(ax_i, ax_r_i, [sig])
            ax_i.legend(loc="upper left", fontsize=8)
            ax_i.set_title(f"AF2Q0.5 — 实验 vs {label}")
            safe = label.replace(" ", "_").replace("=", "").replace("★", "snap")
            save_fig33_figure(fig_i, str(out_dir / f"af2q05_{safe}.png"))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
