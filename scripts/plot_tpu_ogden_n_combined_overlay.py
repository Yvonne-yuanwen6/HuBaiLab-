"""
Combined overlay: full-range + lattice-range Ogden N=1/2/3, all on one figure.

  py -3 scripts/plot_tpu_ogden_n_combined_overlay.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.evaluate_tpu_material_fit import load_csv_curve
from src.material.tpu_fig25 import DEFAULT_TPU_FIG25_JSON, load_tpu_fig25_uniaxial
from src.paths import REPORTS_ROOT

FULL_DIR = REPORTS_ROOT / "tpu_material_fit" / "ogden_n_sweep"
LATTICE_DIR = REPORTS_ROOT / "tpu_material_fit" / "ogden_n_sweep_lattice"
OUT_PNG = REPORTS_ROOT / "tpu_material_fit" / "ogden_n_all_combined_overlay.png"

OGDEN_NAMES = ("ogden_n1", "ogden_n2", "ogden_n3")


def _load_report(report_dir: Path) -> dict:
    path = report_dir / "ogden_n_sweep_report.json"
    if not path.is_file():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    models: dict[str, dict] = {}
    for name in ("marlow", *OGDEN_NAMES):
        csv = report_dir / f"{name}_stress_strain.csv"
        curve = load_csv_curve(csv)
        if not curve:
            continue
        meta = (raw.get("models") or {}).get(name, {})
        models[name] = {
            "curve": curve,
            "score_full": meta.get("score_full", {}),
            "score_lattice_le_0p8": meta.get("score_lattice_le_0p8", {}),
        }
    return {
        "fit_eps_max": raw.get("fit_eps_max"),
        "models": models,
    }


def plot_combined(ref: list[tuple[float, float]], full: dict, lattice: dict, out_png: Path) -> None:
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
    styles = {"ogden_n1": "--", "ogden_n2": "-.", "ogden_n3": ":"}

    fig, axes = plt.subplots(2, 2, figsize=(13.5, 9.0), dpi=150)
    ref_x = [p[0] for p in ref]
    ref_y = [p[1] for p in ref]
    eps_full = max(ref_x) if ref_x else 1.0

    panels = (
        (axes[0, 0], full, 0.8, "全段拟合 · ε≤0.8"),
        (axes[0, 1], full, eps_full, "全段拟合 · 全段"),
        (axes[1, 0], lattice, 0.8, "ε≤0.8 拟合 · ε≤0.8"),
        (axes[1, 1], lattice, eps_full, "ε≤0.8 拟合 · 全段"),
    )

    for ax, report, eps_cap, title in panels:
        if not report.get("models"):
            ax.text(0.5, 0.5, "无数据\n请先运行 fit_tpu_ogden_n_sweep.py", ha="center", va="center", transform=ax.transAxes)
            ax.set_title(title)
            continue

        ref_band = [(e, s) for e, s in zip(ref_x, ref_y) if e <= eps_cap + 1e-9]
        ax.plot(
            [p[0] for p in ref_band],
            [p[1] for p in ref_band],
            "o",
            color="0.12",
            ms=3.5,
            label="Fig.2.5 实验",
            zorder=9,
        )
        marlow = report["models"].get("marlow", {}).get("curve") or []
        m_band = [(e, s) for e, s in marlow if e <= eps_cap + 1e-9]
        if m_band:
            ax.plot(
                [p[0] for p in m_band],
                [p[1] for p in m_band],
                color=colors["marlow"],
                lw=2.6,
                ls="-",
                label="marlow",
                zorder=10,
            )
        for i, name in enumerate(OGDEN_NAMES):
            curve = report["models"].get(name, {}).get("curve") or []
            band = [(e, s) for e, s in curve if e <= eps_cap + 1e-9]
            if not band:
                continue
            sc = report["models"][name].get("score_full", {})
            rmse = sc.get("rmse_MPa")
            rmse_s = f"{rmse:.3f}" if rmse is not None else "n/a"
            ax.plot(
                [p[0] for p in band],
                [p[1] for p in band],
                color=colors[name],
                lw=2.0,
                ls=styles[name],
                label=f"{name} ({rmse_s})",
                zorder=5 + i,
            )
        ax.set_xlim(0, eps_cap * 1.02)
        ymax = max([p[1] for p in ref if p[0] <= eps_cap] or [1.0])
        ax.set_ylim(0, ymax * 1.08)
        ax.set_xlabel("工程应变")
        ax.set_ylabel("工程应力 (MPa)")
        ax.set_title(title)
        ax.grid(True, alpha=0.3)
        ax.legend(fontsize=6.5, loc="lower right")

    fig.suptitle("Ogden N=1/2/3 全部叠图（全段拟合 vs ε≤0.8 拟合）", fontsize=12)
    fig.tight_layout()
    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def main() -> int:
    ref = load_tpu_fig25_uniaxial(DEFAULT_TPU_FIG25_JSON)
    full = _load_report(FULL_DIR)
    lattice = _load_report(LATTICE_DIR)
    if not full.get("models"):
        print(f"Missing {FULL_DIR} — run: py -3 scripts/fit_tpu_ogden_n_sweep.py")
        return 1
    if not lattice.get("models"):
        print(f"Missing {LATTICE_DIR} — run: py -3 scripts/fit_tpu_ogden_n_sweep.py --fit-eps-max 0.8 --out-dir ...")
    plot_combined(ref, full, lattice, OUT_PNG)
    print(f"Saved: {OUT_PNG}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
