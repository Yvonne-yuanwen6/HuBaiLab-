"""
Direct hyperelastic fit to Fig.2.5 TPU tensile data (no Abaqus FEA probe).

Mirrors Abaqus/CAE Material Evaluate: fit several strain-energy forms to the same
uniaxial test data, score RMSE, export curves for overlay plots.

  py -3 scripts/fit_tpu_hyperelastic_direct.py
  py -3 scripts/fit_tpu_hyperelastic_direct.py --plot
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import numpy as np
from scipy.optimize import curve_fit

from src.export.abaqus_compression import HU_BAI_E_MODULUS_MPA, hu_bai_neo_hooke_c10
from src.material.hyperelastic_uniaxial import (
    curve_from_fn,
    marlow_curve_from_test_data,
    nominal_stress_elastic,
    nominal_stress_mooney_rivlin,
    nominal_stress_neo_hooke,
    nominal_stress_ogden,
    nominal_stress_reduced_poly_n2,
    stretch_from_engineering_strain,
)
from src.material.tpu_fig25 import DEFAULT_TPU_FIG25_JSON, load_tpu_fig25_uniaxial
from src.paths import REPORTS_ROOT

OUT_DIR = REPORTS_ROOT / "tpu_material_fit" / "direct_fit"


def _score(ref: list[tuple[float, float]], sim: list[tuple[float, float]]) -> dict:
    if not ref or not sim:
        return {"rmse_MPa": None, "nrmse": None}
    sx = np.array([p[0] for p in sim])
    sy = np.array([p[1] for p in sim])
    rx = np.array([p[0] for p in ref])
    ry = np.array([p[1] for p in ref])
    pred = np.interp(rx, sx, sy, left=sy[0], right=sy[-1])
    err = pred - ry
    rmse = float(math.sqrt(np.mean(err * err)))
    peak = float(np.max(ry)) if len(ry) else 1.0
    return {"rmse_MPa": rmse, "nrmse": rmse / peak if peak > 1e-12 else None}


def _fit_mooney_rivlin(test_data: list[tuple[float, float]]) -> tuple[float, float]:
    eps = np.array([p[0] for p in test_data], dtype=float)
    sig = np.array([p[1] for p in test_data], dtype=float)
    lam = stretch_from_engineering_strain(eps)

    def model(lam_arr, c10, c01):
        return 2.0 * (lam_arr - lam_arr ** (-2)) * c10 + 2.0 * (1.0 - lam_arr ** (-3)) * c01

    c10_0 = hu_bai_neo_hooke_c10(HU_BAI_E_MODULUS_MPA)
    popt, _ = curve_fit(model, lam, sig, p0=(c10_0, c10_0 * 0.2), bounds=([1e-6, 0.0], [50.0, 50.0]), maxfev=20000)
    return float(popt[0]), float(popt[1])


def _fit_reduced_poly_n2(test_data: list[tuple[float, float]]) -> tuple[float, float]:
    eps = np.array([p[0] for p in test_data], dtype=float)
    sig = np.array([p[1] for p in test_data], dtype=float)
    lam = stretch_from_engineering_strain(eps)
    i1 = lam**2 + 2.0 * lam ** (-1)

    def model(lam_arr, c10, c20):
        i1_arr = lam_arr**2 + 2.0 * lam_arr ** (-1)
        return 2.0 * (lam_arr - lam_arr ** (-2)) * (c10 + 2.0 * c20 * (i1_arr - 3.0))

    c10_0 = hu_bai_neo_hooke_c10(HU_BAI_E_MODULUS_MPA)
    popt, _ = curve_fit(model, lam, sig, p0=(c10_0, 0.01), bounds=([1e-6, -10.0], [50.0, 10.0]), maxfev=20000)
    return float(popt[0]), float(popt[1])


def _fit_ogden_n2(test_data: list[tuple[float, float]]) -> tuple[tuple[float, float], tuple[float, float]]:
    eps = np.array([p[0] for p in test_data], dtype=float)
    sig = np.array([p[1] for p in test_data], dtype=float)
    lam = stretch_from_engineering_strain(eps)

    def model(lam_arr, mu1, a1, mu2, a2):
        t1 = (2.0 * mu1 / a1) * (lam_arr ** a1 - lam_arr ** (-0.5 * a1))
        t2 = (2.0 * mu2 / a2) * (lam_arr ** a2 - lam_arr ** (-0.5 * a2))
        return t1 + t2

    c10 = hu_bai_neo_hooke_c10(HU_BAI_E_MODULUS_MPA)
    popt, _ = curve_fit(
        model,
        lam,
        sig,
        p0=(c10, 1.3, c10 * 0.5, -2.0),
        bounds=([1e-6, -5.0, 1e-6, -5.0], [50.0, 5.0, 50.0, 5.0]),
        maxfev=40000,
    )
    mu = (float(popt[0]), float(popt[2]))
    alpha = (float(popt[1]), float(popt[3]))
    return mu, alpha


def fit_all(test_data: list[tuple[float, float]], *, eps_max: float) -> dict:
    c10 = hu_bai_neo_hooke_c10(HU_BAI_E_MODULUS_MPA)
    c10_mr, c01_mr = _fit_mooney_rivlin(test_data)
    c10_y, c20_y = _fit_reduced_poly_n2(test_data)
    mu_o, alpha_o = _fit_ogden_n2(test_data)

    models: dict[str, dict] = {}

    def add(name: str, curve: list[tuple[float, float]], params: dict) -> None:
        models[name] = {
            "params": params,
            "curve": curve,
            "score_full": _score(test_data, curve),
            "score_lattice_le_0p8": _score([(e, s) for e, s in test_data if e <= 0.8 + 1e-9], curve),
        }

    add(
        "elastic",
        curve_from_fn(lambda x: nominal_stress_elastic(x, e_mpa=HU_BAI_E_MODULUS_MPA), eps_max=eps_max),
        {"E_MPa": HU_BAI_E_MODULUS_MPA},
    )
    add(
        "neo_hooke",
        curve_from_fn(lambda x: nominal_stress_neo_hooke(x, c10=c10), eps_max=eps_max),
        {"C10_MPa": c10},
    )
    add("marlow", marlow_curve_from_test_data(test_data, eps_max=eps_max), {"source": "Fig.2.5 test data interpolation"})
    add(
        "polynomial",
        curve_from_fn(lambda x: nominal_stress_mooney_rivlin(x, c10=c10_mr, c01=c01_mr), eps_max=eps_max),
        {"C10_MPa": c10_mr, "C01_MPa": c01_mr, "note": "Mooney-Rivlin / polynomial N=1"},
    )
    add(
        "reduced_poly_n2",
        curve_from_fn(lambda x: nominal_stress_reduced_poly_n2(x, c10=c10_y, c20=c20_y), eps_max=eps_max),
        {"C10_MPa": c10_y, "C20_MPa": c20_y},
    )
    add(
        "ogden_n2",
        curve_from_fn(lambda x: nominal_stress_ogden(x, mu=mu_o, alpha=alpha_o), eps_max=eps_max),
        {"mu1": mu_o[0], "alpha1": alpha_o[0], "mu2": mu_o[1], "alpha2": alpha_o[1]},
    )

    ranked = sorted(models.keys(), key=lambda k: models[k]["score_full"]["rmse_MPa"] or 1e9)
    return {
        "method": "direct_uniaxial_fit",
        "eps_max": eps_max,
        "best_model": ranked[0] if ranked else None,
        "ranking_rmse": ranked,
        "models": models,
    }


def write_outputs(report: dict, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    serial = {
        "method": report["method"],
        "eps_max": report["eps_max"],
        "best_model": report["best_model"],
        "ranking_rmse": report["ranking_rmse"],
        "models": {
            k: {
                "params": v["params"],
                "score_full": v["score_full"],
                "score_lattice_le_0p8": v["score_lattice_le_0p8"],
            }
            for k, v in report["models"].items()
        },
    }
    (out_dir / "direct_fit_report.json").write_text(
        json.dumps(serial, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    for name, info in report["models"].items():
        path = out_dir / f"{name}_stress_strain.csv"
        with path.open("w", encoding="utf-8") as f:
            f.write("engineering_strain,engineering_stress_MPa\n")
            for e, s in info["curve"]:
                f.write(f"{e:.8g},{s:.8g}\n")


def plot_overlay(
    ref: list[tuple[float, float]],
    report: dict,
    probe_curves: dict[str, list[tuple[float, float]]],
    out_png: Path,
) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    from src.postprocess.fig33_plot_style import configure_matplotlib_chinese

    configure_matplotlib_chinese()
    colors = {
        "elastic": "#9E9E9E",
        "neo_hooke": "#795548",
        "marlow": "#1565C0",
        "polynomial": "#2E7D32",
        "ogden_n2": "#C62828",
        "reduced_poly_n2": "#6A1B9A",
    }

    fig, axes = plt.subplots(1, 2, figsize=(12.5, 5.2), dpi=150)
    ref_x = [p[0] for p in ref]
    ref_y = [p[1] for p in ref]
    eps_full = max(ref_x) if ref_x else 1.0

    for ax, eps_cap, title in (
        (axes[0], 0.8, "ε ≤ 0.8（晶格相关段）"),
        (axes[1], eps_full, f"全段 ε ≤ {eps_full:.2f}"),
    ):
        ref_band = [(e, s) for e, s in zip(ref_x, ref_y) if e <= eps_cap + 1e-9]
        # Reference as markers so Marlow (nearly identical) remains visible underneath/over.
        ax.plot(
            [p[0] for p in ref_band],
            [p[1] for p in ref_band],
            "o",
            color="0.15",
            ms=3.5,
            mfc="0.15",
            mec="white",
            mew=0.4,
            label="Fig.2.5 WPD 参考",
            zorder=6,
        )
        ax.plot(
            [p[0] for p in ref_band],
            [p[1] for p in ref_band],
            color="0.55",
            lw=0.8,
            alpha=0.55,
            zorder=1,
        )
        for name, curve in probe_curves.items():
            if not curve:
                continue
            band = [(e, s) for e, s in curve if e <= eps_cap + 1e-9]
            if not band:
                continue
            ax.plot(
                [p[0] for p in band],
                [p[1] for p in band],
                color=colors.get(name, "#444444"),
                ls="--",
                lw=1.6,
                alpha=0.95,
                label=f"{name} (FE probe)",
                zorder=3,
            )
        for name in report.get("ranking_rmse", []):
            curve = report["models"][name]["curve"]
            band = [(e, s) for e, s in curve if e <= eps_cap + 1e-9]
            if not band:
                continue
            is_marlow = name == "marlow"
            ax.plot(
                [p[0] for p in band],
                [p[1] for p in band],
                color=colors.get(name, None),
                ls="-" if is_marlow else "-",
                lw=2.6 if is_marlow else 1.4,
                alpha=1.0 if is_marlow else 0.85,
                label=f"{name} (direct fit)",
                zorder=10 if is_marlow else 4,
            )
        ax.set_xlim(0, eps_cap * 1.02)
        ymax = max([p[1] for p in ref if p[0] <= eps_cap] or [1.0])
        ax.set_ylim(0, ymax * 1.08)
        ax.set_xlabel("工程应变")
        ax.set_ylabel("工程应力 (MPa)")
        ax.set_title(title)
        ax.grid(True, alpha=0.3)
        ax.legend(fontsize=6.5, loc="lower right")

    best = report.get("best_model")
    fig.suptitle(f"TPU 材料筛选 — 直接拟合最优: {best or 'n/a'}", fontsize=11)
    fig.tight_layout()
    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def load_probe_curves() -> dict[str, list[tuple[float, float]]]:
    from scripts.evaluate_tpu_material_fit import load_csv_curve
    from src.paths import ABAQUS_POST

    out: dict[str, list[tuple[float, float]]] = {}
    for name in ("elastic", "neo_hooke"):
        slug = f"tpu_mat_{name}"
        out[name] = load_csv_curve(ABAQUS_POST / slug / f"{slug}_stress_strain.csv")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fig25-json", type=Path, default=DEFAULT_TPU_FIG25_JSON)
    ap.add_argument("--out-dir", type=Path, default=OUT_DIR)
    ap.add_argument("--plot", action="store_true")
    args = ap.parse_args()

    test_data = load_tpu_fig25_uniaxial(args.fig25_json)
    eps_max = max(e for e, _ in test_data)
    report = fit_all(test_data, eps_max=eps_max)
    write_outputs(report, args.out_dir)

    print(f"Direct fit report: {args.out_dir / 'direct_fit_report.json'}")
    print(f"Best model (full-range RMSE): {report['best_model']}")
    print("Ranking:", " > ".join(report["ranking_rmse"]))
    for name in report["ranking_rmse"]:
        sc = report["models"][name]["score_full"]
        sc08 = report["models"][name]["score_lattice_le_0p8"]
        print(
            f"  {name:16s}  RMSE={sc['rmse_MPa']:.4f}  NRMSE={sc['nrmse']:.4f}  "
            f"RMSE@<=0.8={sc08['rmse_MPa']:.4f}"
        )

    if args.plot:
        probe = load_probe_curves()
        png = REPORTS_ROOT / "tpu_material_fit" / "tpu_material_fit_overlay.png"
        plot_overlay(test_data, report, probe, png)
        print(f"Plot: {png}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
