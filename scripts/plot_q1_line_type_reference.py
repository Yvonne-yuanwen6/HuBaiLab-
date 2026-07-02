"""
Q1 (AF2Q1) unit-cell line-type check: current bulge vs paper-correct (flip bending sign).

Paper Eq. 2.1 uses A_f*sin(2πQs); our implementation picks bulge plane via global Z
and outward octant sign. For Q1 the user reports single-rod bending is mirrored vs the paper.

  py -3 scripts/plot_q1_line_type_reference.py
"""
from __future__ import annotations

import math
import os
import sys

import matplotlib.pyplot as plt
import numpy as np

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from src.generator.hu_bai_bcc import HuBaiLatticeGenerator, sinusoidal_path_points
from src.paths import REPORTS_ROOT
from src.postprocess.fig33_plot_style import configure_matplotlib_chinese
from src.visualization.plot_lattice import plot_lattice

L = 20.0
AF = 2.0
Q = 1.0
N_SEG = 48


def _path(amplitude: float) -> list[np.ndarray]:
    h = 0.5 * L
    p0 = np.array([0.0, 0.0, 0.0])
    p1 = np.array([h, h, h])  # (+,+,+) corner — representative strut
    return sinusoidal_path_points(
        p0,
        p1,
        amplitude=amplitude,
        period_factor=Q,
        n_segments=N_SEG,
    )


def _lateral_profile(points: list[np.ndarray]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return arc length s, lateral offset u (mm), sin reference along chord."""
    p0, p1 = points[0], points[-1]
    chord = p1 - p0
    length = float(np.linalg.norm(chord))
    e_t = chord / length
    # Bulge plane: component perpendicular to chord
    lat = []
    s_vals = []
    for p in points:
        rel = p - p0
        s = float(np.dot(rel, e_t))
        u_vec = rel - s * e_t
        lat.append(float(np.linalg.norm(u_vec)) * (1.0 if np.dot(u_vec, u_vec) >= 0 else -1.0))
        s_vals.append(s)
    s_arr = np.array(s_vals)
    u_signed = []
    ref_dir = None
    for p in points:
        rel = p - p0
        s = float(np.dot(rel, e_t))
        u_vec = rel - s * e_t
        if ref_dir is None and float(np.linalg.norm(u_vec)) > 1e-9:
            ref_dir = u_vec / float(np.linalg.norm(u_vec))
        if ref_dir is None:
            u_signed.append(0.0)
        else:
            u_signed.append(float(np.dot(u_vec, ref_dir)))
    s_norm = s_arr / max(length, 1e-9)
    sin_ref = AF * np.sin(2.0 * math.pi * Q * s_norm)
    return s_arr, np.array(u_signed), sin_ref


def _build_unitcell(amplitude: float):
    gen = HuBaiLatticeGenerator(
        cell_size=L,
        rod_diameter=2.0,
        amplitude=float(amplitude),
        period_factor=Q,
        n_segments=N_SEG,
    )
    gen.build_unitcell()
    return gen.get_data(copy=True)


def main() -> int:
    configure_matplotlib_chinese()
    out_dir = REPORTS_ROOT / "q1_line_type_check"
    out_dir.mkdir(parents=True, exist_ok=True)

    pts_wrong = _path(+AF)
    pts_right = _path(-AF)
    s_w, u_w, sin_w = _lateral_profile(pts_wrong)
    s_r, u_r, sin_r = _lateral_profile(pts_right)

    # --- Figure 1: side-by-side unit cell front view (X–Z) ---
    for label, amp, tag in (
        ("当前建模（弯曲方向反）", +AF, "current_wrong"),
        ("论文线型（A_f 取反）", -AF, "paper_correct"),
    ):
        nodes, beams, polylines = _build_unitcell(amp)
        png = out_dir / f"q1_unitcell_front_{tag}.png"
        plot_lattice(
            nodes,
            beams,
            str(png),
            polylines=polylines,
            title=f"AF2Q1 单胞正视图 (X–Z) — {label}",
            projection="front",
        )
        print("Saved:", png)

    # --- Figure 2: single strut line-type + 2D profile ---
    fig, axes = plt.subplots(2, 2, figsize=(12, 10), dpi=150)

    ax = axes[0, 0]
    pw = np.array(pts_wrong)
    ax.plot(pw[:, 0], pw[:, 2], color="#C2185B", lw=2, label="当前")
    pr = np.array(pts_right)
    ax.plot(pr[:, 0], pr[:, 2], color="#1565C0", lw=2, ls="--", label="论文正确")
    ax.scatter([0, L / 2], [0, L / 2], c=["k", "gray"], s=30, zorder=5)
    ax.set_aspect("equal")
    ax.grid(True, alpha=0.3)
    ax.set_xlabel("X (mm)")
    ax.set_ylabel("Z (mm)")
    ax.set_title("单杆 (+,+,+) 正视投影")
    ax.legend(fontsize=8)

    ax = axes[0, 1]
    ax.plot(pw[:, 0], pw[:, 1], color="#C2185B", lw=2, label="当前")
    ax.plot(pr[:, 0], pr[:, 1], color="#1565C0", lw=2, ls="--", label="论文正确")
    ax.set_aspect("equal")
    ax.grid(True, alpha=0.3)
    ax.set_xlabel("X (mm)")
    ax.set_ylabel("Y (mm)")
    ax.set_title("单杆 俯投影 (X–Y)")

    ax = axes[1, 0]
    ax.plot(s_w, u_w, color="#C2185B", lw=2, label="当前 lateral")
    ax.plot(s_r, u_r, color="#1565C0", lw=2, ls="--", label="论文 lateral")
    ax.axhline(0, color="k", lw=0.5, alpha=0.4)
    for frac, txt in ((0.25, "s=0.25"), (0.5, "s=0.5"), (0.75, "s=0.75")):
        x = frac * s_w[-1]
        ax.axvline(x, color="gray", ls=":", alpha=0.5)
        ax.text(x, ax.get_ylim()[1] * 0.85, txt, fontsize=7, ha="center")
    ax.set_xlabel("沿杆弧长 s (mm)")
    ax.set_ylabel("横向偏移 u (mm，带符号)")
    ax.set_title("Q1 线型：横向位移 vs 弧长")
    ax.legend(fontsize=8)
    ax.grid(True, alpha=0.3)

    ax = axes[1, 1]
    s_norm = s_w / s_w[-1]
    ax.plot(s_norm, u_w, color="#C2185B", lw=2, label="当前 u(s)")
    ax.plot(s_norm, u_r, color="#1565C0", lw=2, ls="--", label="论文 u(s)")
    ax.plot(s_norm, sin_w, color="#C2185B", lw=1, alpha=0.4, ls=":", label="+A_f sin(2πs)")
    ax.plot(s_norm, -sin_w, color="#1565C0", lw=1, alpha=0.4, ls=":", label="−A_f sin(2πs)")
    ax.axhline(0, color="k", lw=0.5, alpha=0.4)
    ax.set_xlabel("归一化 s / L_chord")
    ax.set_ylabel("mm")
    ax.set_title("归一化线型对比（论文 = 当前取反）")
    ax.legend(fontsize=7)
    ax.grid(True, alpha=0.3)

    fig.suptitle("AF2Q1 单杆弯曲方向核对 — 线型图", fontsize=13, y=0.98)
    fig.tight_layout()
    compare_png = out_dir / "q1_line_type_compare.png"
    fig.savefig(compare_png, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print("Saved:", compare_png)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
