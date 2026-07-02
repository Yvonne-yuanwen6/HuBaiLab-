"""Plot Q0.5 mesh convergence: RMSE / peak stress vs element count."""
from __future__ import annotations

import argparse
import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from src.paths import REPORTS_ROOT
from src.postprocess.fig33_plot_style import configure_matplotlib_chinese


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--json",
        default=str(REPORTS_ROOT / "mesh_convergence" / "q05_mesh_convergence.json"),
    )
    parser.add_argument(
        "--png",
        default=str(REPORTS_ROOT / "mesh_convergence" / "q05_mesh_convergence.png"),
    )
    args = parser.parse_args()

    if not os.path.isfile(args.json):
        print(f"[ERROR] missing {args.json} — run evaluate_mesh_convergence.py first")
        return 1

    with open(args.json, encoding="utf-8") as f:
        data = json.load(f)
    rows = [r for r in data.get("levels", []) if r.get("status") == "ok" and r.get("element_count")]
    if not rows:
        print("[ERROR] no completed levels with element_count in JSON")
        return 1

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    configure_matplotlib_chinese()
    rows = sorted(rows, key=lambda r: int(r["element_count"]))

    xs = [int(r["element_count"]) for r in rows]
    labels = [r["level_id"] for r in rows]
    rmse = [float(r["rmse_vs_fig33"]) for r in rows if r.get("rmse_vs_fig33") is not None]
    rmse_xs = [int(r["element_count"]) for r in rows if r.get("rmse_vs_fig33") is not None]
    peaks = [float(r["peak_stress_MPa"]) for r in rows]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10.5, 4.2), dpi=150)

    if rmse_xs:
        ax1.plot(rmse_xs, rmse, "o-", color="#1565C0", linewidth=2, markersize=7)
        for x, y, lab in zip(rmse_xs, rmse, labels):
            ax1.annotate(lab, (x, y), textcoords="offset points", xytext=(4, 4), fontsize=7)
    ax1.set_xlabel("单元数")
    ax1.set_ylabel("RMSE vs Fig.3.3 Q0.5 (MPa)")
    ax1.set_title("网格收敛 — RMSE")
    ax1.grid(True, alpha=0.3)

    ax2.plot(xs, peaks, "s-", color="#C62828", linewidth=2, markersize=7)
    ax2.axhline(0.032, color="#888", linestyle=":", linewidth=1, label="Q0.5 peak 阈值 0.032")
    for x, y, lab in zip(xs, peaks, labels):
        ax2.annotate(lab, (x, y), textcoords="offset points", xytext=(4, 4), fontsize=7)
    ax2.set_xlabel("单元数")
    ax2.set_ylabel("峰值应力 (MPa)")
    ax2.set_title("网格收敛 — 峰值应力")
    ax2.legend(fontsize=8)
    ax2.grid(True, alpha=0.3)

    fig.suptitle("AF2Q0.5 网格收敛研究 (CAE C3D4)", fontsize=12)
    fig.tight_layout()
    os.makedirs(os.path.dirname(args.png) or ".", exist_ok=True)
    fig.savefig(args.png, bbox_inches="tight", facecolor="white")
    print("Saved:", args.png)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
