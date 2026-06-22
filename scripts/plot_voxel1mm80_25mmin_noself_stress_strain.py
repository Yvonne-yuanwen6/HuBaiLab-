"""
Plot all voxel1mm80_25mmin_noself stress-strain curves on one figure.

  py -3 scripts/plot_voxel1mm80_25mmin_noself_stress_strain.py
"""

from __future__ import annotations

import argparse
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from scripts.plot_stress_strain import load_csv
from src.paths import ABAQUS_POST, REPORTS_ROOT

CASES = (
    ("Q=0 (BCC)", "hu_bai_bcc_af2q0_L20_4x4x4_solid_cad_f_voxel1mm80_25mmin_noself"),
    ("Q=0.5 (SFBLS)", "hu_bai_sfbls_af2q0p5_L20_4x4x4_solid_cad_f_voxel1mm80_25mmin_noself"),
    ("Q=1.0 (SFBLS)", "hu_bai_sfbls_af2q1_L20_4x4x4_solid_cad_f_voxel1mm80_25mmin_noself"),
    ("Q=1.5 (SFBLS)", "hu_bai_sfbls_af2q1p5_L20_4x4x4_solid_cad_f_voxel1mm80_25mmin_noself"),
)

# BCC=浅蓝, Q0.5=深蓝, Q1=红, Q1.5=粉
CASE_COLORS = {
    "bcc_af2q0": "#89CFF0",
    "sfbls_af2q0p5": "#1565C0",
    "sfbls_af2q1": "#E53935",
    "sfbls_af2q1p5": "#F48FB1",
}


def _color_for_slug(slug: str) -> str:
    for key in sorted(CASE_COLORS, key=len, reverse=True):
        if key in slug:
            return CASE_COLORS[key]
    return "#333333"


def plot_compare(
    series: list[tuple[str, list[float], list[float], str]],
    *,
    save_path: str | None,
    show: bool,
) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(9, 5.5))

    for label, strains, stresses, color in series:
        ax.plot(
            strains,
            stresses,
            color=color,
            linewidth=1.8,
            label=label,
        )

    ax.set_xlabel("Engineering strain")
    ax.set_ylabel("Engineering stress (MPa)")
    ax.set_title("C3D8R voxel hex / 1 mm / 25 mm/min / 80% strain — 4×4×4 comparison")
    ax.grid(True, alpha=0.35)
    ax.legend(loc="best", fontsize=9)
    fig.tight_layout()

    if save_path:
        save_path = os.path.abspath(save_path)
        os.makedirs(os.path.dirname(save_path) or ".", exist_ok=True)
        fig.savefig(save_path, dpi=150)
        print("Saved:", save_path)
    if show:
        plt.show()
    plt.close(fig)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Plot voxel1mm80_25mmin_noself stress-strain comparison"
    )
    parser.add_argument(
        "--png",
        default=str(REPORTS_ROOT / "voxel1mm80_25mmin_noself_stress_strain_compare.png"),
    )
    parser.add_argument("--show", action="store_true")
    args = parser.parse_args()

    series: list[tuple[str, list[float], list[float], str]] = []
    for label, slug in CASES:
        csv_path = ABAQUS_POST / slug / f"{slug}_stress_strain.csv"
        if not csv_path.is_file():
            print(f"[ERROR] Not found: {csv_path}")
            return 1
        strains, stresses = load_csv(str(csv_path))
        if not strains:
            print(f"[ERROR] Empty CSV: {csv_path}")
            return 1
        peak_i = max(range(len(stresses)), key=lambda i: stresses[i])
        color = _color_for_slug(slug)
        print(
            f"{label}: {len(strains)} pts, "
            f"peak {stresses[peak_i]:.4f} MPa @ strain {strains[peak_i]:.4f}, color={color}"
        )
        series.append((label, strains, stresses, color))

    plot_compare(series, save_path=args.png, show=args.show)
    return 0


if __name__ == "__main__":
    sys.exit(main())
