"""
Fig.3.3 — overlay best-matching simulation per structure (auto-picked from post/).

  py -3 scripts/plot_fig33_best_exp_vs_sim.py
"""
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
from src.postprocess.best_fig33_cases import pick_best_per_structure
from src.postprocess.fig33_plot_style import (
    FIG33_EXP_LINEWIDTH,
    FIG33_EXP_LINESTYLE,
    FIG33_OVERLAY_COLORS,
    FIG33_SIM_LINEWIDTH,
    FIG33_SIM_LINESTYLE,
    autoscale_fig33_ylim_for_overlay,
    create_fig33_figure,
    load_fig33_reference,
    plot_fig33_experiment,
    plot_fig33_simulation,
    save_fig33_figure,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--png",
        default=str(REPORTS_ROOT / "fig33_best_exp_vs_sim_all.png"),
    )
    parser.add_argument(
        "--write-json",
        default=str(REPORTS_ROOT / "fig33_best_exp_vs_sim_all.json"),
    )
    parser.add_argument("--show-densification", action="store_true")
    args = parser.parse_args()

    picked = pick_best_per_structure()
    ref = load_fig33_reference()
    fig, ax, ax_r = create_fig33_figure()
    plot_fig33_experiment(
        ax,
        ref,
        show_densification=args.show_densification,
        color_map=FIG33_OVERLAY_COLORS,
        linestyle=FIG33_EXP_LINESTYLE,
        linewidth=FIG33_EXP_LINEWIDTH,
    )

    overlay_stresses: list[list[float]] = []
    loaded: list[dict] = []
    for key in ("bcc", "af2q05", "af2q1", "af2q15"):
        rows = picked.get(key) or []
        if not rows:
            print(f"[WARN] no candidate for {key}")
            continue
        row = rows[0]
        slug = row["slug"]
        csv = ABAQUS_POST / slug / f"{slug}_stress_strain.csv"
        if not csv.is_file():
            print(f"[WARN] missing {csv}")
            continue
        eps, sig = load_csv(str(csv))
        exp_lab = ref["series"][key]["label"].replace("-实验", "")
        sim_lab = f"{exp_lab} {row['label']}-仿真"
        plot_fig33_simulation(
            ax,
            eps,
            sig,
            key=key,
            label=sim_lab,
            color=FIG33_OVERLAY_COLORS[key],
            linestyle=FIG33_SIM_LINESTYLE,
            linewidth=FIG33_SIM_LINEWIDTH,
        )
        overlay_stresses.append(sig)
        loaded.append({**row, "key": key, "n_points": len(eps), "csv": str(csv)})
        print(f"{key}: rmse={row['rmse']:.6f}  {row['label']}  peak={max(sig):.4f} MPa")

    if not loaded:
        print("[ERROR] no simulation curves loaded")
        return 1

    autoscale_fig33_ylim_for_overlay(ax, ax_r, overlay_stresses)
    ax.legend(loc="upper left", fontsize=6.5, frameon=True, framealpha=0.92, ncol=1)
    ax.set_title("Fig.3.3 — 实验 vs 当前最接近仿真（按 RMSE 自动选取）")
    out = save_fig33_figure(fig, args.png)
    print("Saved:", out)

    if args.write_json:
        os.makedirs(os.path.dirname(args.write_json) or ".", exist_ok=True)
        with open(args.write_json, "w", encoding="utf-8") as f:
            json.dump({"picked": loaded}, f, indent=2, ensure_ascii=False)
        print("Wrote:", args.write_json)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
