"""
Plot traced Fig.2.5 TPU tensile curve (WPD) with paper scalar checkpoints.

  py -3 scripts/plot_tpu_fig25_wpd.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.paths import REPORTS_ROOT
from src.postprocess.fig33_plot_style import configure_matplotlib_chinese

TRACED = _ROOT / "data" / "hu_bai_tpu_fig25_tensile_traced.json"


def main() -> int:
    if not TRACED.is_file():
        print(f"Missing {TRACED} — run: py -3 scripts/import_webplotdigitizer_tpu_fig25.py")
        return 1

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    configure_matplotlib_chinese()
    data = json.loads(TRACED.read_text(encoding="utf-8"))
    pts = data["points"]
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    scalars = data.get("paper_scalars") or {}

    fig, ax = plt.subplots(figsize=(8, 5), dpi=150)
    ax.plot(xs, ys, color="#1565C0", linewidth=2, label="Fig.2.5 WPD 试样曲线")
    ax.axhline(float(scalars.get("yield_MPa_tensile", 4.69)), color="#E53935", ls=":", lw=1, alpha=0.7,
               label=f"论文屈服 ≈{scalars.get('yield_MPa_tensile', 4.69)} MPa")
    for eps, lab in ((0.05, "ε=0.05"), (0.50, "ε=0.50")):
        ax.axvline(eps, color="gray", ls=":", alpha=0.35)
        ax.text(eps, ax.get_ylim()[1] * 0.02 if ax.get_ylim()[1] else 0.2, lab, fontsize=8, ha="center")

    pk = data.get("peak") or {}
    if pk:
        ax.plot(pk["engineering_strain"], pk["engineering_stress_MPa"], "o", color="#C62828", ms=6,
                label=f"峰值 {pk['engineering_stress_MPa']:.2f} MPa")

    ax.set_xlim(0, data.get("xlim", [0, 6.5])[1])
    ax.set_ylim(0, data.get("ylim", [0, 14])[1])
    ax.set_xlabel(data.get("x_label", "工程应变"))
    ax.set_ylabel(data.get("y_label", "工程应力 (MPa)"))
    ax.set_title("Fig.2.5 TPU 拉伸 — WebPlotDigitizer 校验")
    ax.grid(True, alpha=0.3)
    ax.legend(loc="lower right", fontsize=8)
    fig.tight_layout()

    out_dir = REPORTS_ROOT / "tpu_fig25"
    out_dir.mkdir(parents=True, exist_ok=True)
    png = out_dir / "tpu_fig25_wpd_validation.png"
    fig.savefig(png, bbox_inches="tight", facecolor="white")
    print("Saved:", png)
    plt.close(fig)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
