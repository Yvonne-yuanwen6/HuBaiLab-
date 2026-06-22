"""
Plot four voxel0p8mm75_15mmin stress-strain curves on one figure.

  py -3 scripts/plot_voxel0p8mm75_15mmin_stress_strain.py
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

_SUFFIX = "voxel0p8mm75_15mmin"

_CASES = (
    ("hu_bai_bcc_af2q0_L20_4x4x4_solid_cad_f_voxel0p8mm75_15mmin", "Q=0 (BCC)", "#89CFF0"),
    ("hu_bai_sfbls_af2q0p5_L20_4x4x4_solid_cad_f_voxel0p8mm75_15mmin", "Q=0.5 (SFBLS)", "#1565C0"),
    ("hu_bai_sfbls_af2q1_L20_4x4x4_solid_cad_f_voxel0p8mm75_15mmin", "Q=1.0 (SFBLS)", "#E53935"),
    ("hu_bai_sfbls_af2q1p5_L20_4x4x4_solid_cad_f_voxel0p8mm75_15mmin", "Q=1.5 (SFBLS)", "#F48FB1"),
)


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
        ax.plot(strains, stresses, color=color, linewidth=1.8, label=label)

    ax.set_xlabel("Engineering strain")
    ax.set_ylabel("Engineering stress (MPa)")
    ax.set_title("Hu & Bai 4x4x4 — voxel 0.8 mm, 75% strain @ 15 mm/min")
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
    parser = argparse.ArgumentParser(description="Plot voxel0p8mm75_15mmin comparison")
    parser.add_argument(
        "--png",
        default=str(REPORTS_ROOT / "voxel0p8mm75_15mmin_stress_strain_compare.png"),
    )
    parser.add_argument("--show", action="store_true")
    args = parser.parse_args()

    series: list[tuple[str, list[float], list[float], str]] = []
    for slug, base_label, color in _CASES:
        csv = ABAQUS_POST / slug / f"{slug}_stress_strain.csv"
        if not csv.is_file():
            print(f"[WARN] Missing: {csv}")
            continue
        strains, stresses = load_csv(str(csv))
        if not strains:
            print(f"[WARN] Empty: {csv}")
            continue
        peak_i = max(range(len(stresses)), key=lambda i: stresses[i])
        max_strain = strains[peak_i]
        label = base_label
        if max_strain < 0.74:
            label = f"{base_label}, partial {max_strain:.0%}"
        print(
            f"{label}: {len(strains)} pts, "
            f"peak {stresses[peak_i]:.4f} MPa @ strain {max_strain:.4f}"
        )
        series.append((label, strains, stresses, color))

    if not series:
        print("[ERROR] No curves found")
        return 1

    plot_compare(series, save_path=args.png, show=args.show)
    return 0


if __name__ == "__main__":
    sys.exit(main())
