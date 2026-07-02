"""Q0.5 Fig.3.3 experiment vs fig33 improve sweep variants (+ elastic baseline)."""
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
    IMPROVE_VARIANT_STYLES,
    autoscale_fig33_ylim_for_overlay,
    create_fig33_figure,
    load_fig33_reference,
    plot_fig33_experiment_series,
    plot_fig33_simulation,
    save_fig33_figure,
)

BASE = "cae_tet0p6mm80_5mmin_paperbox"
PREFIX = f"hu_bai_sfbls_af2q0p5_L20_4x4x4_solid_cad_f_{BASE}"

VARIANTS = (
    ("fig33_v2_el (baseline)", f"{PREFIX}_fig33_v2_el"),
    ("fig33_v2_paper", f"{PREFIX}_fig33_v2_paper"),
    ("fig33_v2_ep", f"{PREFIX}_fig33_v2_ep"),
    ("paperbox_settle5p", f"{PREFIX}_paperbox_settle5p"),
    ("fig33_v2_paper_dt1e4", f"{PREFIX}_fig33_v2_paper_dt1e4"),
)


def find_csv(slug: str) -> str | None:
    for name in (f"{slug}_stress_strain.csv", f"{slug}_stress_strain_partial.csv"):
        path = ABAQUS_POST / slug / name
        if path.is_file():
            return str(path)
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--png",
        default=str(REPORTS_ROOT / "fig33_v2_improve" / "af2q05_exp_vs_sim_all.png"),
    )
    parser.add_argument("--per-variant", action="store_true")
    parser.add_argument("--write-summary-json", default="")
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
        style = IMPROVE_VARIANT_STYLES.get(label, {"color": "#555555", "linestyle": "--", "linewidth": 1.8})
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
        loaded.append(
            {
                "label": label,
                "slug": slug,
                "n_points": len(eps),
                "peak_MPa": max(sig),
                "peak_strain": eps[sig.index(max(sig))],
                "csv": csv_path,
            }
        )
        print(f"{label}: {len(eps)} pts peak={max(sig):.4f} MPa @ eps={eps[sig.index(max(sig))]:.3f}")

    if not loaded:
        print("[ERROR] no curves loaded")
        return 1

    autoscale_fig33_ylim_for_overlay(ax, ax_r, overlay_stresses)
    ax.legend(loc="upper left", fontsize=7, frameon=True, framealpha=0.92, ncol=1)
    ax.set_title("AF2Q0.5 — 实验 vs 材料/接触扫参 (fig33 improve sweep)")
    out = save_fig33_figure(fig, args.png)
    print("Saved:", out)

    if args.per_variant:
        out_dir = REPORTS_ROOT / "fig33_v2_improve"
        out_dir.mkdir(parents=True, exist_ok=True)
        for row in loaded:
            fig_i, ax_i, ax_r_i = create_fig33_figure()
            plot_fig33_experiment_series(ax_i, ref, series_key="af2q05")
            eps, sig = load_csv(row["csv"])
            style = IMPROVE_VARIANT_STYLES.get(row["label"], {"color": "#555555", "linestyle": "--", "linewidth": 1.8})
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
            safe = row["label"].replace(" ", "_").replace("(", "").replace(")", "")
            save_fig33_figure(fig_i, str(out_dir / f"af2q05_{safe}.png"))

    if args.write_summary_json:
        os.makedirs(os.path.dirname(args.write_summary_json) or ".", exist_ok=True)
        with open(args.write_summary_json, "w", encoding="utf-8") as f:
            json.dump({"variants": loaded}, f, indent=2, ensure_ascii=False)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
