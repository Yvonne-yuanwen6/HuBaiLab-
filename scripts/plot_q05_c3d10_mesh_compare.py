"""Q0.5 Fig.3.3 experiment vs C3D10 / C3D10M mesh-convergence cases."""
from __future__ import annotations

import argparse
import json
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

VARIANTS = (
    ("C3D10 s05r4 s80", "q05_c10_s05r4_el_s80"),
    ("C3D10M s06r3 s45", "q05_c10m_s06r3_el_s45"),
    ("C3D10M s06r3 s75 cont", "q05_c10m_s06r3_el_s75_cont"),
    ("C3D10M s05r4 s78 (fail)", "q05_c10m_s05r4_el_s78"),
)

STYLES = {
    "C3D10 s05r4 s80": {"color": "#E65100", "linestyle": "-.", "linewidth": 2.0},
    "C3D10M s06r3 s45": {"color": "#2E7D32", "linestyle": "--", "linewidth": 2.0},
    "C3D10M s06r3 s75 cont": {"color": "#1565C0", "linestyle": "-", "linewidth": 2.2},
    "C3D10M s05r4 s78 (fail)": {"color": "#9E9E9E", "linestyle": ":", "linewidth": 1.6},
}


def find_csv(slug: str) -> str | None:
    post = ABAQUS_POST / slug
    for name in (
        f"{slug}_merged_stress_strain.csv",
        f"{slug}_stress_strain.csv",
        f"{slug}_stress_strain_partial.csv",
    ):
        path = post / name
        if path.is_file():
            return str(path)
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--png",
        default=str(REPORTS_ROOT / "c3d10_mesh" / "af2q05_exp_vs_sim_c3d10.png"),
    )
    parser.add_argument("--per-variant", action="store_true")
    parser.add_argument("--write-summary-json", default="")
    parser.add_argument("--min-points", type=int, default=5)
    args = parser.parse_args()

    ref = load_fig33_reference()
    fig, ax, ax_r = create_fig33_figure()
    plot_fig33_experiment_series(ax, ref, series_key="af2q05")

    overlay_stresses: list[list[float]] = []
    loaded: list[dict] = []
    for label, slug in VARIANTS:
        csv_path = find_csv(slug)
        if not csv_path:
            print(f"[WARN] missing {slug}")
            continue
        eps, sig = load_csv(csv_path)
        if len(eps) < args.min_points:
            print(f"[WARN] skip {slug}: only {len(eps)} points")
            continue
        style = STYLES.get(label, {"color": "#555555", "linestyle": "--", "linewidth": 1.8})
        plot_fig33_simulation(
            ax,
            eps,
            sig,
            key="af2q05",
            label=f"AF2Q0.5 {label}-仿真",
            color=style["color"],
            linestyle=style["linestyle"],
            linewidth=style["linewidth"],
        )
        overlay_stresses.append(sig)
        peak_i = sig.index(max(sig))
        loaded.append(
            {
                "label": label,
                "slug": slug,
                "n_points": len(eps),
                "peak_MPa": max(sig),
                "peak_strain": eps[peak_i],
                "csv": csv_path,
            }
        )
        print(f"{label}: {len(eps)} pts peak={max(sig):.4f} MPa @ eps={eps[peak_i]:.3f}")

    if not loaded:
        print("[ERROR] no curves loaded")
        return 1

    autoscale_fig33_ylim_for_overlay(ax, ax_r, overlay_stresses)
    ax.legend(loc="upper left", fontsize=7, frameon=True, framealpha=0.92, ncol=1)
    ax.set_title("AF2Q0.5 — 实验 vs C3D10/C3D10M 网格收敛")
    out = save_fig33_figure(fig, args.png)
    print("Saved:", out)

    if args.per_variant:
        out_dir = REPORTS_ROOT / "c3d10_mesh"
        out_dir.mkdir(parents=True, exist_ok=True)
        for row in loaded:
            fig_i, ax_i, ax_r_i = create_fig33_figure()
            plot_fig33_experiment_series(ax_i, ref, series_key="af2q05")
            eps, sig = load_csv(row["csv"])
            style = STYLES.get(row["label"], {"color": "#555555", "linestyle": "--", "linewidth": 1.8})
            plot_fig33_simulation(
                ax_i,
                eps,
                sig,
                key="af2q05",
                label=f"AF2Q0.5 {row['label']}-仿真",
                color=style["color"],
                linestyle=style["linestyle"],
                linewidth=style["linewidth"],
            )
            autoscale_fig33_ylim_for_overlay(ax_i, ax_r_i, [sig])
            ax_i.legend(loc="upper left", fontsize=8)
            ax_i.set_title(f"AF2Q0.5 — 实验 vs {row['label']}")
            safe = row["slug"]
            save_fig33_figure(fig_i, str(out_dir / f"af2q05_{safe}.png"))

    if args.write_summary_json:
        os.makedirs(os.path.dirname(args.write_summary_json) or ".", exist_ok=True)
        with open(args.write_summary_json, "w", encoding="utf-8") as f:
            json.dump({"variants": loaded}, f, indent=2, ensure_ascii=False)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
