"""
Score TPU material probe curves vs Fig.2.5 WPD reference (material-level screening).

  py -3 scripts/evaluate_tpu_material_fit.py
  py -3 scripts/evaluate_tpu_material_fit.py --plot
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.material.tpu_fig25 import DEFAULT_TPU_FIG25_JSON, load_tpu_fig25_uniaxial
from src.paths import ABAQUS_POST, REPORTS_ROOT

PROBE_PREFIX = "tpu_mat"
DEFAULT_MODELS = (
    "elastic",
    "neo_hooke",
    "marlow",
    "polynomial",
    "ogden_n2",
    "reduced_poly_n2",
)


def load_csv_curve(path: Path) -> list[tuple[float, float]]:
    if not path.is_file():
        return []
    pts: list[tuple[float, float]] = []
    with path.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            pts.append((float(row["engineering_strain"]), float(row["engineering_stress_MPa"])))
    return pts


def interp(pts: list[tuple[float, float]], target: float) -> float | None:
    if not pts:
        return None
    if target <= pts[0][0]:
        return pts[0][1]
    for i in range(1, len(pts)):
        e0, s0 = pts[i - 1]
        e1, s1 = pts[i]
        if e1 >= target:
            if abs(e1 - e0) < 1e-15:
                return s1
            t = (target - e0) / (e1 - e0)
            return s0 + t * (s1 - s0)
    return None


def _sample_ref(ref: list[tuple[float, float]], eps_max: float) -> list[tuple[float, float]]:
    return [(e, s) for e, s in ref if e <= eps_max + 1e-12]


def score_curve(
    sim: list[tuple[float, float]],
    ref: list[tuple[float, float]],
    *,
    eps_max: float,
) -> dict:
    ref_band = _sample_ref(ref, eps_max)
    if not sim or not ref_band:
        return {
            "n_ref": len(ref_band),
            "rmse_MPa": None,
            "nrmse": None,
            "max_abs_err_MPa": None,
            "pass": False,
            "reason": "missing_data",
        }

    sq = 0.0
    n = 0
    max_abs = 0.0
    ref_peak = max(s for _, s in ref_band)
    for e_ref, s_ref in ref_band:
        s_sim = interp(sim, e_ref)
        if s_sim is None:
            continue
        err = s_sim - s_ref
        sq += err * err
        n += 1
        max_abs = max(max_abs, abs(err))

    if n == 0:
        return {
            "n_ref": len(ref_band),
            "rmse_MPa": None,
            "nrmse": None,
            "max_abs_err_MPa": None,
            "pass": False,
            "reason": "no_overlap",
        }

    rmse = math.sqrt(sq / n)
    nrmse = rmse / ref_peak if ref_peak > 1e-12 else None
    checkpoints = []
    for eps in (0.05, 0.10, 0.50, 0.80, 1.00):
        if eps > eps_max + 1e-9:
            continue
        s_ref = interp(ref, eps)
        s_sim = interp(sim, eps)
        if s_ref is None or s_sim is None or abs(s_ref) < 1e-12:
            continue
        checkpoints.append(
            {
                "strain": eps,
                "ref_MPa": s_ref,
                "sim_MPa": s_sim,
                "ratio": s_sim / s_ref,
                "abs_err_MPa": s_sim - s_ref,
            }
        )

    return {
        "n_ref": n,
        "rmse_MPa": rmse,
        "nrmse": nrmse,
        "max_abs_err_MPa": max_abs,
        "checkpoints": checkpoints,
        "pass": True,
    }


def evaluate_all(
    *,
    models: tuple[str, ...],
    ref: list[tuple[float, float]],
    eps_full: float,
    eps_lattice: float,
) -> dict:
    rows = []
    for model in models:
        slug = f"{PROBE_PREFIX}_{model}"
        csv_path = ABAQUS_POST / slug / f"{slug}_stress_strain.csv"
        sim = load_csv_curve(csv_path)
        full = score_curve(sim, ref, eps_max=eps_full)
        lattice = score_curve(sim, ref, eps_max=eps_lattice)
        rows.append(
            {
                "model": model,
                "slug": slug,
                "csv_found": csv_path.is_file(),
                "csv_path": str(csv_path),
                "full_range": full,
                "lattice_range_le_0p8": lattice,
            }
        )

    ranked = sorted(
        [r for r in rows if r["full_range"].get("rmse_MPa") is not None],
        key=lambda r: float(r["full_range"]["rmse_MPa"]),
    )
    best = ranked[0]["model"] if ranked else None
    return {
        "best_model_full_range": best,
        "ranking_full_range_rmse": [r["model"] for r in ranked],
        "fig25_peak_strain": max(e for e, _ in ref),
        "eval_eps_full": eps_full,
        "eval_eps_lattice": eps_lattice,
        "models": rows,
    }


def plot_overlay(report: dict, ref: list[tuple[float, float]], out_png: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    from src.postprocess.fig33_plot_style import configure_matplotlib_chinese

    configure_matplotlib_chinese()
    fig, axes = plt.subplots(1, 2, figsize=(12, 5), dpi=150)

    colors = {
        "elastic": "#9E9E9E",
        "neo_hooke": "#795548",
        "marlow": "#1565C0",
        "polynomial": "#2E7D32",
        "ogden_n2": "#C62828",
        "reduced_poly_n2": "#6A1B9A",
    }

    ref_x = [p[0] for p in ref]
    ref_y = [p[1] for p in ref]

    for ax, eps_max, title_suffix in (
        (axes[0], report["eval_eps_lattice"], f"ε ≤ {report['eval_eps_lattice']}"),
        (axes[1], report["eval_eps_full"], f"ε ≤ {report['eval_eps_full']:.2f}"),
    ):
        ax.plot(ref_x, ref_y, "k-", lw=2.2, label="Fig.2.5 WPD 参考")
        for row in report["models"]:
            model = row["model"]
            slug = row["slug"]
            csv_path = Path(row["csv_path"])
            sim = load_csv_curve(csv_path)
            if not sim:
                continue
            sim_band = [(e, s) for e, s in sim if e <= eps_max + 1e-9]
            if not sim_band:
                continue
            ax.plot(
                [p[0] for p in sim_band],
                [p[1] for p in sim_band],
                color=colors.get(model, None),
                lw=1.5,
                alpha=0.9,
                label=model,
            )
        ax.set_xlim(0, eps_max * 1.02)
        ax.set_ylim(0, max(ref_y) * 1.05)
        ax.set_xlabel("工程应变")
        ax.set_ylabel("工程应力 (MPa)")
        ax.set_title(f"TPU 材料模型对比 — {title_suffix}")
        ax.grid(True, alpha=0.3)
        ax.legend(fontsize=7, loc="lower right")

    best = report.get("best_model_full_range")
    fig.suptitle(f"材料级筛选 (Abaqus 单元素拉伸) — 全段最优: {best or 'n/a'}", fontsize=11)
    fig.tight_layout()
    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fig25-json", type=Path, default=DEFAULT_TPU_FIG25_JSON)
    ap.add_argument("--models", nargs="*", default=list(DEFAULT_MODELS))
    ap.add_argument("--lattice-eps-max", type=float, default=0.8)
    ap.add_argument("--plot", action="store_true")
    ap.add_argument(
        "--write-json",
        type=Path,
        default=REPORTS_ROOT / "tpu_material_fit" / "tpu_material_fit_report.json",
    )
    args = ap.parse_args()

    ref = load_tpu_fig25_uniaxial(args.fig25_json)
    eps_full = max(e for e, _ in ref)
    report = evaluate_all(
        models=tuple(args.models),
        ref=ref,
        eps_full=eps_full,
        eps_lattice=float(args.lattice_eps_max),
    )

    args.write_json.parent.mkdir(parents=True, exist_ok=True)
    args.write_json.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Report: {args.write_json}")
    print(f"Best (full-range RMSE): {report.get('best_model_full_range')}")
    print("Ranking:", " > ".join(report.get("ranking_full_range_rmse") or ["(none)"]))

    for row in report["models"]:
        full = row["full_range"]
        lat = row["lattice_range_le_0p8"]
        rmse = full.get("rmse_MPa")
        lat_rmse = lat.get("rmse_MPa")
        rmse_s = f"{rmse:.4f}" if rmse is not None else "n/a"
        lat_s = f"{lat_rmse:.4f}" if lat_rmse is not None else "n/a"
        print(f"  {row['model']:16s}  csv={'Y' if row['csv_found'] else 'N'}  RMSE={rmse_s}  RMSE@<=0.8={lat_s}")

    if args.plot:
        png = args.write_json.parent / "tpu_material_fit_overlay.png"
        plot_overlay(report, ref, png)
        print(f"Plot: {png}")

    missing = [r["model"] for r in report["models"] if not r["csv_found"]]
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
