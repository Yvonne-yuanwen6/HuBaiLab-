"""
Plot Q=0 and Q=0.5 stress-strain curves on one figure (4x4x4 CAD solid, default).

  .venv\\Scripts\\python.exe scripts\\plot_q0_q05_stress_strain.py
  .venv\\Scripts\\python.exe scripts\\plot_q0_q05_stress_strain.py --png output\\reports\\q0_q05_stress_strain.png
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

DEFAULT_CASES = (
    (
        "Q=0 (BCC)",
        ABAQUS_POST
        / "hu_bai_bcc_af2q0_L20_4x4x4_solid_cad_f_fast"
        / "hu_bai_bcc_af2q0_L20_4x4x4_solid_cad_f_fast_stress_strain.csv",
    ),
    (
        "Q=0.5 (SFBLS)",
        ABAQUS_POST
        / "hu_bai_sfbls_af2q0p5_L20_4x4x4_solid_cad_f_fast80"
        / "hu_bai_sfbls_af2q0p5_L20_4x4x4_solid_cad_f_fast80_stress_strain.csv",
    ),
)


def plot_compare(
    series: list[tuple[str, list[float], list[float]]],
    *,
    save_path: str | None,
    show: bool,
) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    colors = ("#1f77b4", "#d62728", "#2ca02c", "#9467bd")
    fig, ax = plt.subplots(figsize=(8, 5.5))

    for i, (label, strains, stresses) in enumerate(series):
        ax.plot(
            strains,
            stresses,
            color=colors[i % len(colors)],
            linewidth=1.8,
            label=label,
        )

    ax.set_xlabel("Engineering strain")
    ax.set_ylabel("Engineering stress (MPa)")
    ax.set_title("Hu & Bai lattice — Q=0 vs Q=0.5 (4×4×4, CAD solid)")
    ax.grid(True, alpha=0.35)
    ax.legend(loc="best")
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
    parser = argparse.ArgumentParser(description="Plot Q=0 and Q=0.5 stress-strain curves")
    parser.add_argument(
        "--png",
        default=str(REPORTS_ROOT / "q0_q05_stress_strain_4x4x4.png"),
    )
    parser.add_argument("--show", action="store_true", help="Display interactively (requires GUI backend)")
    args = parser.parse_args()

    series: list[tuple[str, list[float], list[float]]] = []
    for label, csv_path in DEFAULT_CASES:
        path = str(csv_path)
        if not os.path.isfile(path):
            print(f"[ERROR] Not found: {path}")
            return 1
        strains, stresses = load_csv(path)
        if not strains:
            print(f"[ERROR] Empty CSV: {path}")
            return 1
        peak_i = max(range(len(stresses)), key=lambda i: stresses[i])
        print(
            f"{label}: {len(strains)} points, "
            f"peak {stresses[peak_i]:.4f} MPa @ strain {strains[peak_i]:.4f}"
        )
        series.append((label, strains, stresses))

    plot_compare(series, save_path=args.png, show=args.show)
    return 0


if __name__ == "__main__":
    sys.exit(main())
