"""
Four-structure line-type check (BCC, Q0.5, Q1, Q1.5): lateral u(s) vs normalized s.

Uses HuBaiLatticeGenerator / sinusoidal_path_points (Q=1: −A_f sin; others: +A_f sin).

  py -3 scripts/plot_four_line_types.py
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

from src.generator.hu_bai_bcc import _bulge_direction_outward, sinusoidal_path_points
from src.paths import REPORTS_ROOT
from src.postprocess.fig33_plot_style import configure_matplotlib_chinese

L = 20.0
AF = 2.0
N_SEG = 48
H = 0.5 * L

STRUCTURES = (
    (0.0, "BCC AF2Q0", "#546E7A"),
    (0.5, "SFBLS AF2Q0.5", "#1565C0"),
    (1.0, "SFBLS AF2Q1", "#C2185B"),
    (1.5, "SFBLS AF2Q1.5", "#E53935"),
)


def _representative_path(q: float) -> list[np.ndarray]:
    p0 = np.array([0.0, 0.0, 0.0])
    p1 = np.array([H, H, H])
    return sinusoidal_path_points(
        p0,
        p1,
        amplitude=AF,
        period_factor=q,
        n_segments=N_SEG,
    )


def _lateral_profile(points: list[np.ndarray]) -> tuple[np.ndarray, np.ndarray]:
    p0, p1 = points[0], points[-1]
    chord = p1 - p0
    length = float(np.linalg.norm(chord))
    e_t = chord / length
    n_hat = _bulge_direction_outward(p0, p1)
    n_hat = n_hat - float(np.dot(n_hat, e_t)) * e_t
    n_norm = float(np.linalg.norm(n_hat))
    if n_norm >= 1e-12:
        n_hat /= n_norm
    s_vals: list[float] = []
    u_signed: list[float] = []
    for p in points:
        rel = p - p0
        s = float(np.dot(rel, e_t))
        u_vec = rel - s * e_t
        u_signed.append(float(np.dot(u_vec, n_hat)))
        s_vals.append(s)
    s_arr = np.array(s_vals)
    s_norm = s_arr / max(length, 1e-9)
    return s_norm, np.array(u_signed)


def _sin_ref(q: float, s_norm: np.ndarray) -> np.ndarray:
    if abs(q) < 1e-12:
        return np.zeros_like(s_norm)
    sign = -1.0 if abs(q - 1.0) < 1e-9 else 1.0
    return sign * AF * np.sin(2.0 * math.pi * q * s_norm)


def main() -> int:
    configure_matplotlib_chinese()
    out_dir = REPORTS_ROOT / "four_line_types"
    out_dir.mkdir(parents=True, exist_ok=True)

    fig, axes = plt.subplots(2, 2, figsize=(12, 10), dpi=150)
    for ax, (q, title, color) in zip(axes.ravel(), STRUCTURES):
        pts = _representative_path(q)
        s_norm, u = _lateral_profile(pts)
        sin_u = _sin_ref(q, s_norm)
        sin_sign = "−" if abs(q - 1.0) < 1e-9 else "+"
        if abs(q) < 1e-12:
            formula = "f(s)=0 (straight)"
        else:
            formula = f"f(s)={sin_sign}A_f sin(2π·{q:g}·s)"

        ax.plot(s_norm, u, color=color, lw=2, label="u(s) 建模")
        if abs(q) >= 1e-12:
            ax.plot(
                s_norm,
                sin_u,
                color=color,
                lw=1.2,
                ls="--",
                alpha=0.55,
                label=formula,
            )
        ax.axhline(0, color="k", lw=0.5, alpha=0.4)
        ax.set_xlabel("归一化 s / L_chord")
        ax.set_ylabel("横向偏移 u (mm)")
        ax.set_title(f"{title}\n{formula}")
        ax.legend(fontsize=8)
        ax.grid(True, alpha=0.3)

        single_png = out_dir / f"line_type_q{str(q).replace('.', 'p')}.png"
        fig1, ax1 = plt.subplots(figsize=(6, 4), dpi=150)
        ax1.plot(s_norm, u, color=color, lw=2, label="u(s) 建模")
        if abs(q) >= 1e-12:
            ax1.plot(s_norm, sin_u, color=color, lw=1.2, ls="--", alpha=0.55, label=formula)
        ax1.axhline(0, color="k", lw=0.5, alpha=0.4)
        ax1.set_xlabel("归一化 s / L_chord")
        ax1.set_ylabel("横向偏移 u (mm)")
        ax1.set_title(f"{title} — 线型")
        ax1.legend(fontsize=8)
        ax1.grid(True, alpha=0.3)
        fig1.tight_layout()
        fig1.savefig(single_png, bbox_inches="tight", facecolor="white")
        plt.close(fig1)
        print("Saved:", single_png)

    fig.suptitle("四结构单杆线型 (centre → +,+,+ corner)", fontsize=13, y=0.98)
    fig.tight_layout()
    combined = out_dir / "four_line_types_grid.png"
    fig.savefig(combined, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print("Saved:", combined)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
