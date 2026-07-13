"""
Overlay Q=0 ellipse 4×4×4 Neo-Hooke baseline stress-strain (ellmaj vs ellmin).

  py -3 scripts/plot_ellipse_q0_baseline_overlay.py
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

SLUG_MAJ = (
    "hu_bai_bcc_af2q0_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox_ellipse_ellmaj"
)
SLUG_MIN = (
    "hu_bai_bcc_af2q0_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox_ellipse_ellmin"
)
SLUG_CIRC = "hu_bai_bcc_af2q0_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox"

CASES = (
    ("Q=0 ellmaj (major axis || +Z)", SLUG_MAJ, "#1565C0"),
    ("Q=0 ellmin (minor axis || +Z)", SLUG_MIN, "#C62828"),
)


def plot_overlay(
    series: list[tuple[str, list[float], list[float], str]],
    *,
    save_path: str,
    circ: tuple[list[float], list[float]] | None = None,
) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(8.5, 5.5))
    for label, strains, stresses, color in series:
        ax.plot(strains, stresses, color=color, linewidth=1.9, label=label)

    if circ is not None:
        c_str, c_stress = circ
        ax.plot(
            c_str,
            c_stress,
            color="#616161",
            linewidth=1.4,
            linestyle="--",
            label="Q=0 circular (Neo-Hooke baseline)",
        )

    ax.set_xlabel("Engineering strain")
    ax.set_ylabel("Engineering stress (MPa)")
    ax.set_title("Ellipse 4×4×4 Q=0 — Neo-Hooke baseline (80% strain, 5 mm/min)")
    ax.grid(True, alpha=0.35)
    ax.legend(loc="best", fontsize=9)
    fig.tight_layout()

    os.makedirs(os.path.dirname(save_path) or ".", exist_ok=True)
    fig.savefig(save_path, dpi=150)
    plt.close(fig)
    print("Saved:", save_path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--png",
        default=str(REPORTS_ROOT / "ellipse_baseline" / "q0_ellmaj_vs_ellmin_neohooke.png"),
    )
    parser.add_argument("--with-circular", action="store_true", help="Overlay circular Q=0 baseline if CSV exists")
    args = parser.parse_args()

    series: list[tuple[str, list[float], list[float], str]] = []
    for label, slug, color in CASES:
        csv = ABAQUS_POST / slug / f"{slug}_stress_strain.csv"
        if not csv.is_file():
            print(f"[ERROR] Not found: {csv}")
            return 1
        strains, stresses = load_csv(str(csv))
        peak_i = max(range(len(stresses)), key=lambda i: stresses[i])
        print(
            f"{label}: n={len(strains)} peak={stresses[peak_i]:.3f} MPa @ eps={strains[peak_i]:.4f}"
        )
        series.append((label, strains, stresses, color))

    circ = None
    if args.with_circular:
        circ_csv = ABAQUS_POST / SLUG_CIRC / f"{SLUG_CIRC}_stress_strain.csv"
        if circ_csv.is_file():
            circ = load_csv(str(circ_csv))
            print(f"circular baseline: n={len(circ[0])}")
        else:
            print(f"[WARN] circular CSV missing: {circ_csv}")

    plot_overlay(series, save_path=os.path.abspath(args.png), circ=circ)
    return 0


if __name__ == "__main__":
    sys.exit(main())
