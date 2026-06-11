"""
Plot all completed fast80 stress-strain curves on one figure.

  py -3 scripts/plot_fast80_stress_strain.py
"""

from __future__ import annotations

import argparse
import os
import re
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from scripts.plot_stress_strain import load_csv
from src.paths import ABAQUS_POST, REPORTS_ROOT

_LABELS = {
    "bcc_af2q0": "Q=0 (BCC)",
    "sfbls_af2q0p5": "Q=0.5 (SFBLS)",
    "sfbls_af2q1": "Q=1.0 (SFBLS)",
    "sfbls_af2q1p5": "Q=1.5 (SFBLS)",
}


def _label_from_slug(slug: str) -> str:
    m = re.search(r"hu_bai_(\w+)_L\d+_(\d+x\d+x\d+)_", slug)
    if not m:
        return slug
    variant, cells = m.group(1), m.group(2)
    q = _LABELS.get(variant, variant)
    return f"{q} {cells}"


def discover_fast80_csvs() -> list[tuple[str, str]]:
    post = ABAQUS_POST
    if not post.is_dir():
        return []
    found: list[tuple[str, str]] = []
    for d in sorted(post.iterdir()):
        if not d.is_dir() or not d.name.endswith("_fast80"):
            continue
        csv = d / f"{d.name}_stress_strain.csv"
        if csv.is_file():
            found.append((_label_from_slug(d.name), str(csv)))
    return found


def plot_compare(
    series: list[tuple[str, list[float], list[float]]],
    *,
    save_path: str | None,
    show: bool,
) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    colors = ("#1f77b4", "#d62728", "#2ca02c", "#9467bd", "#ff7f0e", "#8c564b")
    fig, ax = plt.subplots(figsize=(9, 5.5))

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
    ax.set_title("Hu & Bai lattice — fast80 stress-strain comparison")
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
    parser = argparse.ArgumentParser(description="Plot all fast80 stress-strain curves")
    parser.add_argument(
        "--png",
        default=str(REPORTS_ROOT / "fast80_stress_strain_compare.png"),
    )
    parser.add_argument("--show", action="store_true")
    args = parser.parse_args()

    cases = discover_fast80_csvs()
    if not cases:
        print("[ERROR] No fast80 stress_strain CSV found under output/post/")
        return 1

    series: list[tuple[str, list[float], list[float]]] = []
    for label, path in cases:
        strains, stresses = load_csv(path)
        if not strains:
            print(f"[WARN] Empty: {path}")
            continue
        peak_i = max(range(len(stresses)), key=lambda i: stresses[i])
        print(
            f"{label}: {len(strains)} pts, "
            f"peak {stresses[peak_i]:.4f} MPa @ strain {strains[peak_i]:.4f}"
        )
        series.append((label, strains, stresses))

    if not series:
        print("[ERROR] No usable curves")
        return 1

    plot_compare(series, save_path=args.png, show=args.show)
    return 0


if __name__ == "__main__":
    sys.exit(main())
