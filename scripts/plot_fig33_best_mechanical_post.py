"""
Fig.3.11–3.13 & Fig.4.10 from best Fig.3.3 simulation curves (BCC / Q0.5 / Q1 / Q1.5).

  py -3 scripts/plot_fig33_best_mechanical_post.py

Outputs under output/reports/fig33_best_mechanical_post/:
  - fig311_energy_absorption.png   (Wv, SEA, η vs strain — thesis Fig.3.11 style)
  - fig313_normalized_energy.png (Wv/E vs log σ/E — thesis Fig.3.13 style)
  - fig410_specific_modulus.png  (solid TPU ref + lattice bars — thesis Fig.4.10 cube panel)
  - mechanical_post_report.json
  - {slug}_energy_absorption.csv per case
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import matplotlib.pyplot as plt

from src.paths import REPORTS_ROOT
from src.postprocess.best_fig33_cases import STRUCTURE_ORDER, load_best_curves
from src.postprocess.energy_absorption import (
    HU_BAI_PAPER_RELATIVE_DENSITY,
    HU_BAI_TPU_MATRIX_E_MPA,
    analyze_energy_absorption,
)
from src.postprocess.fig33_plot_style import FIG33_OVERLAY_COLORS, configure_matplotlib_chinese

OUT_DIR = REPORTS_ROOT / "fig33_best_mechanical_post"


def _write_energy_csv(path: str, analysis: dict) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    rows = []
    for i in range(len(analysis["strains"])):
        rows.append(
            {
                "engineering_strain": analysis["strains"][i],
                "engineering_stress_MPa": analysis["stresses_MPa"][i],
                "Wv_J_cm3": analysis["Wv_J_cm3"][i],
                "SEA": analysis["SEA"][i],
                "eta": analysis["eta"][i],
                "sigma_star_MPa": analysis["sigma_star_MPa"][i],
            }
        )
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def plot_fig311(cases: list[dict], out_png: str) -> None:
    configure_matplotlib_chinese()
    fig, axes = plt.subplots(1, 3, figsize=(14, 4.2), constrained_layout=True)

    titles = (
        "(a) 单位体积能量吸收 Wv",
        "(b) 比能量吸收 SEA = Wv/ρa",
        "(c) 能量吸收效率 η = Wv/σ*",
    )
    ylabels = ("Wv (J/cm³)", "SEA (J/cm³)", "η (–)")

    for ax, title, ylabel, field in zip(
        axes,
        titles,
        ylabels,
        ("Wv_J_cm3", "SEA", "eta"),
    ):
        for case in cases:
            key = case["key"]
            ana = case["analysis"]
            eps = ana["strains"]
            y = ana[field]
            ax.plot(
                eps,
                y,
                color=FIG33_OVERLAY_COLORS[key],
                linewidth=2.0,
                label=case["series_label"],
            )
            ed = ana["densification"]["densification_strain"]
            if ed == ed:
                idx = max(range(len(eps)), key=lambda i: eps[i] if eps[i] <= ed else -1.0)
                ax.scatter(
                    [ed],
                    [y[idx]],
                    color=FIG33_OVERLAY_COLORS[key],
                    s=28,
                    zorder=5,
                )
        ax.set_xlabel("工程应变 ε")
        ax.set_ylabel(ylabel)
        ax.set_title(title, fontsize=11)
        ax.grid(True, alpha=0.25)
        ax.set_xlim(left=0.0)

    axes[0].legend(loc="upper left", fontsize=8, frameon=True, framealpha=0.9)
    fig.suptitle("Fig.3.11 — 能量吸收性能（最优仿真曲线）", fontsize=12, y=1.02)
    os.makedirs(os.path.dirname(out_png) or ".", exist_ok=True)
    fig.savefig(out_png, dpi=160, bbox_inches="tight")
    plt.close(fig)


def plot_fig313(cases: list[dict], out_png: str) -> None:
    configure_matplotlib_chinese()
    fig, ax = plt.subplots(figsize=(7.5, 5.5), constrained_layout=True)
    for case in cases:
        key = case["key"]
        ana = case["analysis"]
        ax.plot(
            ana["normalized_x_log_sigma_over_E"],
            ana["normalized_y_Wv_over_E"],
            color=FIG33_OVERLAY_COLORS[key],
            linewidth=2.0,
            label=case["series_label"],
        )
    ax.set_xlabel("log10(sigma / E_m)")
    ax.set_ylabel("Wv / E_m")
    ax.set_title("Fig.3.13 — 归一化能量吸收曲线（最优仿真）")
    ax.grid(True, alpha=0.25)
    ax.legend(loc="upper left", fontsize=9)
    os.makedirs(os.path.dirname(out_png) or ".", exist_ok=True)
    fig.savefig(out_png, dpi=160, bbox_inches="tight")
    plt.close(fig)


def plot_fig410(cases: list[dict], out_png: str) -> None:
    """
    Thesis Fig.4.10 cube-block panel: specific modulus E* = E_struct / ρa.

    Solid TPU cube reference: E_m / 1 = 25 MPa.
    """
    configure_matplotlib_chinese()
    fig, ax = plt.subplots(figsize=(8.5, 5.0), constrained_layout=True)

    labels = ["实体 TPU\n(ρa=1)"]
    values = [HU_BAI_TPU_MATRIX_E_MPA]
    colors = ["#424242"]

    for case in cases:
        labels.append(case["series_label"])
        values.append(case["analysis"]["specific_modulus_MPa"])
        colors.append(FIG33_OVERLAY_COLORS[case["key"]])

    xpos = range(len(labels))
    bars = ax.bar(xpos, values, color=colors, edgecolor="white", linewidth=0.8)
    ax.set_xticks(list(xpos))
    ax.set_xticklabels(labels, fontsize=9)
    ax.set_ylabel("比弹性模量 E* = E / ρa (MPa)")
    ax.set_title("Fig.4.10 — 比弹性模量（4×4×4 立方块，最优仿真）")
    ax.grid(True, axis="y", alpha=0.25)

    for bar, val in zip(bars, values):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height(),
            f"{val:.2f}",
            ha="center",
            va="bottom",
            fontsize=8,
        )

    os.makedirs(os.path.dirname(out_png) or ".", exist_ok=True)
    fig.savefig(out_png, dpi=160, bbox_inches="tight")
    plt.close(fig)


def main() -> int:
    parser = argparse.ArgumentParser(description="Fig.3.11–3.13 & Fig.4.10 from best Fig.3.3 sims")
    parser.add_argument("--out-dir", default=str(OUT_DIR))
    args = parser.parse_args()
    out_dir = args.out_dir
    os.makedirs(out_dir, exist_ok=True)

    raw = load_best_curves()
    if not raw:
        print("[ERROR] no best curves found under output/post/ (need paperbox/fig33 stress_strain.csv)")
        return 1

    cases: list[dict] = []
    report_cases: list[dict] = []
    for row in raw:
        key = row["key"]
        rho_a = HU_BAI_PAPER_RELATIVE_DENSITY.get(key, 0.045)
        ana = analyze_energy_absorption(
            row["strains"],
            row["stresses_MPa"],
            relative_density=rho_a,
        )
        case = {**row, "analysis": ana, "relative_density_paper": rho_a}
        cases.append(case)

        csv_out = os.path.join(out_dir, f"{row['slug']}_energy_absorption.csv")
        _write_energy_csv(csv_out, ana)

        report_cases.append(
            {
                "key": key,
                "slug": row["slug"],
                "label": row["label"],
                "rmse": row["rmse"],
                "relative_density_paper": rho_a,
                "elastic_modulus_MPa": ana["mechanics"]["elastic_modulus_MPa"],
                "yield_stress_MPa": ana["mechanics"]["yield_stress_MPa"],
                "specific_modulus_MPa": ana["specific_modulus_MPa"],
                "densification_strain": ana["densification"]["densification_strain"],
                "Wv_at_densification_J_cm3": ana["Wv_at_densification_J_cm3"],
                "SEA_at_densification": ana["SEA_at_densification"],
                "eta_at_densification": ana["eta_at_densification"],
                "csv": row["csv"],
                "energy_csv": csv_out,
            }
        )
        print(
            f"{key}: E={ana['mechanics']['elastic_modulus_MPa']:.4f} MPa  "
            f"E*={ana['specific_modulus_MPa']:.2f} MPa  "
            f"Wv@ed={ana['Wv_at_densification_J_cm3']:.5f} J/cm3  "
            f"eta@ed={ana['eta_at_densification']:.3f}"
        )

    # Preserve thesis structure order in plots
    order = {k: i for i, k in enumerate(STRUCTURE_ORDER)}
    cases.sort(key=lambda c: order.get(c["key"], 99))

    fig311 = os.path.join(out_dir, "fig311_energy_absorption.png")
    fig313 = os.path.join(out_dir, "fig313_normalized_energy.png")
    fig410 = os.path.join(out_dir, "fig410_specific_modulus.png")

    plot_fig311(cases, fig311)
    plot_fig313(cases, fig313)
    plot_fig410(cases, fig410)

    report = {
        "reference": "Hu & Bai 2024 §3.3.1 (Fig.3.11–3.13), §4.4 (Fig.4.10 cube block)",
        "matrix_E_MPa": HU_BAI_TPU_MATRIX_E_MPA,
        "note_fig312": (
            "Fig.3.12 mixed HX/ZX structures not included — requires separate HXAF2Q1Q15 / "
            "ZXAF2Q1Q15 compression curves."
        ),
        "cases": report_cases,
        "figures": {
            "fig311": fig311,
            "fig313": fig313,
            "fig410": fig410,
        },
    }
    report_path = os.path.join(out_dir, "mechanical_post_report.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    print("Saved:", fig311)
    print("Saved:", fig313)
    print("Saved:", fig410)
    print("Wrote:", report_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
