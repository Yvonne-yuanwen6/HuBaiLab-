"""
Fit Ogden N=1/2/3 to Fig.2.5 TPU tensile data; compare with Marlow + experiment.

  py -3 scripts/fit_tpu_ogden_n_sweep.py --plot
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
    nominal_stress_ogden,
    stretch_from_engineering_strain,
)
from src.material.tpu_fig25 import DEFAULT_TPU_FIG25_JSON, load_tpu_fig25_uniaxial
from src.paths import REPORTS_ROOT

OUT_DIR = REPORTS_ROOT / "tpu_material_fit" / "ogden_n_sweep"


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


def _ogden_model_factory(n: int):
    def model(lam_arr: np.ndarray, *params: float) -> np.ndarray:
        out = np.zeros_like(lam_arr, dtype=float)
        for i in range(n):
            mu = params[2 * i]
            alpha = params[2 * i + 1]
            if abs(alpha) < 1e-12:
                continue
            out += (2.0 * mu / alpha) * (lam_arr ** alpha - lam_arr ** (-0.5 * alpha))
        return out

    return model


def _initial_guesses(n: int, c10: float) -> list[tuple[float, ...]]:
    g: list[tuple[float, ...]] = []
    if n == 1:
        g.extend([(c10, 2.0), (c10, 1.3), (c10 * 1.5, -1.9), (c10, 0.8)])
    elif n == 2:
        g.extend(
            [
                (c10, 2.0, c10 * 0.3, 2.0),
                (c10, 1.3, c10 * 0.5, -2.0),
                (c10 * 0.8, -1.9, c10 * 0.4, 2.5),
                (1.6, -1.2, 0.8, -1.2),
            ]
        )
    else:
        g.extend(
            [
                (c10, 2.0, c10 * 0.3, 2.0, c10 * 0.1, 1.0),
                (c10, 1.3, c10 * 0.5, -2.0, c10 * 0.2, 3.0),
                (1.0, -1.5, 0.5, 2.0, 0.3, 4.0),
            ]
        )
    return g


def _bounds(n: int, *, positive_alpha: bool) -> tuple[list[float], list[float]]:
    lo: list[float] = []
    hi: list[float] = []
    for _ in range(n):
        lo.extend([1e-6, 0.2 if positive_alpha else -5.0])
        hi.extend([50.0, 6.0])
    return lo, hi


def fit_ogden_n(
    test_data: list[tuple[float, float]],
    n: int,
    *,
    positive_alpha: bool = False,
) -> tuple[tuple[float, ...], tuple[float, ...], float]:
    eps = np.array([p[0] for p in test_data], dtype=float)
    sig = np.array([p[1] for p in test_data], dtype=float)
    lam = stretch_from_engineering_strain(eps)
    model = _ogden_model_factory(n)
    lo, hi = _bounds(n, positive_alpha=positive_alpha)
    c10 = hu_bai_neo_hooke_c10(HU_BAI_E_MODULUS_MPA)

    best_rmse = float("inf")
    best_mu: tuple[float, ...] = tuple()
    best_alpha: tuple[float, ...] = tuple()

    for p0 in _initial_guesses(n, c10):
        try:
            popt, _ = curve_fit(
                model,
                lam,
                sig,
                p0=p0,
                bounds=(lo, hi),
                maxfev=60000,
            )
        except Exception:
            continue
        mu = tuple(float(popt[2 * i]) for i in range(n))
        alpha = tuple(float(popt[2 * i + 1]) for i in range(n))
        curve = curve_from_fn(
            lambda x, m=mu, a=alpha: nominal_stress_ogden(x, mu=m, alpha=a),
            eps_max=float(np.max(eps)),
        )
        rmse = _score(test_data, curve)["rmse_MPa"] or float("inf")
        if rmse < best_rmse:
            best_rmse = rmse
            best_mu, best_alpha = mu, alpha

    if not best_mu:
        raise RuntimeError(f"Ogden N={n} fit failed for all initial guesses")

    return best_mu, best_alpha, best_rmse


def run_sweep(test_data: list[tuple[float, float]], *, eps_max: float, fit_eps_max: float | None = None) -> dict:
    fit_data = (
        [(e, s) for e, s in test_data if e <= float(fit_eps_max) + 1e-9]
        if fit_eps_max is not None
        else test_data
    )
    models: dict[str, dict] = {}

    marlow_curve = marlow_curve_from_test_data(test_data, eps_max=eps_max)
    models["marlow"] = {
        "params": {"note": "Fig.2.5 interpolation"},
        "curve": marlow_curve,
        "score_full": _score(test_data, marlow_curve),
        "score_lattice_le_0p8": _score([(e, s) for e, s in test_data if e <= 0.8], marlow_curve),
    }

    ogden_ranking: list[str] = []
    for n in (1, 2, 3):
        name = f"ogden_n{n}"
        mu, alpha, _ = fit_ogden_n(fit_data, n, positive_alpha=False)
        mu_pos, alpha_pos, rmse_pos = fit_ogden_n(fit_data, n, positive_alpha=True)
        curve_neg = curve_from_fn(
            lambda x, m=mu, a=alpha: nominal_stress_ogden(x, mu=m, alpha=a),
            eps_max=eps_max,
        )
        curve_pos = curve_from_fn(
            lambda x, m=mu_pos, a=alpha_pos: nominal_stress_ogden(x, mu=m, alpha=a),
            eps_max=eps_max,
        )
        rmse_neg = _score(test_data, curve_neg)["rmse_MPa"] or float("inf")
        use_pos = rmse_pos < rmse_neg
        mu_f, alpha_f, curve = (mu_pos, alpha_pos, curve_pos) if use_pos else (mu, alpha, curve_neg)
        models[name] = {
            "params": {f"mu{i+1}": mu_f[i] for i in range(n)} | {f"alpha{i+1}": alpha_f[i] for i in range(n)},
            "params_note": "positive_alpha" if use_pos else "signed_alpha",
            "curve": curve,
            "score_full": _score(test_data, curve),
            "score_lattice_le_0p8": _score([(e, s) for e, s in test_data if e <= 0.8], curve),
        }
        ogden_ranking.append(name)

    ogden_ranking.sort(key=lambda k: models[k]["score_full"]["rmse_MPa"] or 1e9)
    return {
        "method": "ogden_n_sweep_direct_fit",
        "eps_max": eps_max,
        "fit_eps_max": fit_eps_max,
        "best_ogden": ogden_ranking[0] if ogden_ranking else None,
        "ogden_ranking_rmse": ogden_ranking,
        "models": models,
    }


def write_outputs(report: dict, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    serial = {
        "method": report["method"],
        "eps_max": report["eps_max"],
        "best_ogden": report["best_ogden"],
        "ogden_ranking_rmse": report["ogden_ranking_rmse"],
        "models": {
            k: {
                "params": v["params"],
                "score_full": v["score_full"],
                "score_lattice_le_0p8": v["score_lattice_le_0p8"],
            }
            for k, v in report["models"].items()
        },
    }
    (out_dir / "ogden_n_sweep_report.json").write_text(
        json.dumps(serial, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    for name, info in report["models"].items():
        path = out_dir / f"{name}_stress_strain.csv"
        with path.open("w", encoding="utf-8") as f:
            f.write("engineering_strain,engineering_stress_MPa\n")
            for e, s in info["curve"]:
                f.write(f"{e:.8g},{s:.8g}\n")


def plot_compare(ref: list[tuple[float, float]], report: dict, out_png: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    from src.postprocess.fig33_plot_style import configure_matplotlib_chinese

    configure_matplotlib_chinese()
    colors = {
        "marlow": "#1565C0",
        "ogden_n1": "#E65100",
        "ogden_n2": "#C62828",
        "ogden_n3": "#6A1B9A",
    }

    styles = {
        "ogden_n1": ("--", 2.0),
        "ogden_n2": ("-.", 2.0),
        "ogden_n3": (":", 2.6),
        "marlow": ("-", 2.8),
    }

    fig, axes = plt.subplots(1, 2, figsize=(13.0, 5.4), dpi=150)
    ref_x = [p[0] for p in ref]
    ref_y = [p[1] for p in ref]
    eps_full = max(ref_x) if ref_x else 1.0
    draw_order = ["ogden_n1", "ogden_n2", "ogden_n3", "marlow"]

    for ax, eps_cap, title in (
        (axes[0], 0.8, "ε ≤ 0.8"),
        (axes[1], eps_full, f"全段 ε ≤ {eps_full:.2f}"),
    ):
        ref_band = [(e, s) for e, s in zip(ref_x, ref_y) if e <= eps_cap + 1e-9]
        ax.plot(
            [p[0] for p in ref_band],
            [p[1] for p in ref_band],
            "o",
            color="0.12",
            ms=4,
            mfc="0.12",
            mec="white",
            mew=0.4,
            label="Fig.2.5 实验 (WPD)",
            zorder=8,
        )
        for name in draw_order:
            if name not in report["models"]:
                continue
            curve = report["models"][name]["curve"]
            band = [(e, s) for e, s in curve if e <= eps_cap + 1e-9]
            if not band:
                continue
            sc = report["models"][name]["score_full"]
            rmse = sc.get("rmse_MPa")
            rmse_s = f"{rmse:.3f}" if rmse is not None else "n/a"
            is_marlow = name == "marlow"
            ls, lw = styles.get(name, ("-", 1.8))
            ax.plot(
                [p[0] for p in band],
                [p[1] for p in band],
                color=colors.get(name, "#333"),
                lw=lw,
                ls=ls,
                alpha=1.0 if is_marlow else 0.95,
                label=f"{name} (RMSE={rmse_s})",
                zorder=10 if is_marlow else {"ogden_n1": 5, "ogden_n2": 6, "ogden_n3": 7}.get(name, 4),
            )
        ax.set_xlim(0, eps_cap * 1.02)
        ymax = max([p[1] for p in ref if p[0] <= eps_cap] or [1.0])
        ax.set_ylim(0, ymax * 1.08)
        ax.set_xlabel("工程应变")
        ax.set_ylabel("工程应力 (MPa)")
        ax.set_title(title)
        ax.grid(True, alpha=0.3)
        ax.legend(fontsize=7, loc="lower right")

    fit_note = report.get("fit_eps_max")
    if fit_note:
        fig.suptitle(f"Ogden N=1/2/3 + Marlow vs 实验（拟合段 ε≤{fit_note}）", fontsize=11)
    else:
        fig.suptitle("Ogden N=1/2/3 + Marlow vs 实验（全段拟合）", fontsize=11)
    fig.tight_layout()
    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fig25-json", type=Path, default=DEFAULT_TPU_FIG25_JSON)
    ap.add_argument("--out-dir", type=Path, default=OUT_DIR)
    ap.add_argument("--fit-eps-max", type=float, default=0.0, help="Fit only on eps<=this (0=full range)")
    ap.add_argument("--no-plot", action="store_true", help="Skip overlay PNG")
    args = ap.parse_args()

    test_data = load_tpu_fig25_uniaxial(args.fig25_json)
    eps_max = max(e for e, _ in test_data)
    fit_cap = float(args.fit_eps_max) if args.fit_eps_max > 0 else None
    report = run_sweep(test_data, eps_max=eps_max, fit_eps_max=fit_cap)
    write_outputs(report, args.out_dir)

    print(f"Report: {args.out_dir / 'ogden_n_sweep_report.json'}")
    if fit_cap:
        print(f"  (fitted on eps <= {fit_cap}, evaluated vs full Fig.2.5)")
    print(f"Best Ogden (full RMSE): {report['best_ogden']}")
    print("Ogden ranking:", " > ".join(report["ogden_ranking_rmse"]))
    for name in ["marlow", *report["ogden_ranking_rmse"]]:
        sc = report["models"][name]["score_full"]
        sc08 = report["models"][name]["score_lattice_le_0p8"]
        print(
            f"  {name:10s}  full RMSE={sc['rmse_MPa']:.4f}  "
            f"<=0.8 RMSE={sc08['rmse_MPa']:.4f}  params={report['models'][name]['params']}"
        )

    if not args.no_plot:
        out_resolved = args.out_dir.resolve()
        if out_resolved == OUT_DIR.resolve():
            png = REPORTS_ROOT / "tpu_material_fit" / "ogden_n_sweep_overlay.png"
        else:
            png = out_resolved / "ogden_n_sweep_overlay.png"
        plot_compare(test_data, report, png)
        print(f"Plot: {png}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
