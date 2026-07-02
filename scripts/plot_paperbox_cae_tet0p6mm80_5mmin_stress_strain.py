"""
Plot BCC + SFBLS Q=0.5/1/1.5 paper_box CAE C3D4 stress-strain curves on one figure.

  py -3 scripts/plot_paperbox_cae_tet0p6mm80_5mmin_stress_strain.py
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
from src.postprocess.compression_curve import (
    HU_BAI_PAPER_DENSIFICATION_STRAIN,
    estimate_densification_strain,
)

_SUFFIX = "cae_tet0p6mm80_5mmin_paperbox"

# slug, legend, color, paper densification key
_CASES = (
    (
        f"hu_bai_bcc_af2q0_L20_4x4x4_solid_cad_f_{_SUFFIX}",
        "Q=0 (BCC, paper_box CAE C3D4)",
        "#89CFF0",
        "bcc",
    ),
    (
        f"hu_bai_sfbls_af2q0p5_L20_4x4x4_solid_cad_f_{_SUFFIX}",
        "Q=0.5 (SFBLS, paper_box CAE C3D4)",
        "#1565C0",
        "q0.5",
    ),
    (
        f"hu_bai_sfbls_af2q1_L20_4x4x4_solid_cad_f_{_SUFFIX}",
        "Q=1.0 (SFBLS, paper_box CAE C3D4)",
        "#F48FB1",
        "q1",
    ),
    (
        f"hu_bai_sfbls_af2q1p5_L20_4x4x4_solid_cad_f_{_SUFFIX}",
        "Q=1.5 (SFBLS, paper_box CAE C3D4)",
        "#E53935",
        "q1.5",
    ),
)

_PAPER_FIG33_STRESS_MAX_MPA = 0.04


def plot_compare(
    series: list[tuple[str, list[float], list[float], str, dict[str, float], float | None]],
    *,
    save_path: str | None,
    show: bool,
) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(10, 6))
    for label, strains, stresses, color, dens, paper_ed in series:
        ax.plot(strains, stresses, color=color, linewidth=1.8, label=label)

        ed = dens["densification_strain"]
        sd = dens["densification_stress_MPa"]
        if ed == ed and sd == sd:  # not NaN
            ax.scatter([ed], [sd], color=color, s=42, zorder=5, edgecolors="black", linewidths=0.6)
            ax.axvline(ed, color=color, linestyle=":", alpha=0.45, linewidth=1.0)
            ax.annotate(
                f"εd={ed:.2f}",
                xy=(ed, sd),
                xytext=(6, 8),
                textcoords="offset points",
                fontsize=8,
                color=color,
            )
        if paper_ed is not None:
            i_ref = min(range(len(strains)), key=lambda i: abs(strains[i] - paper_ed))
            ax.scatter(
                [paper_ed],
                [stresses[i_ref]],
                facecolors="none",
                edgecolors=color,
                s=55,
                linewidths=1.2,
                zorder=4,
                marker="s",
            )

    ax.axhline(
        _PAPER_FIG33_STRESS_MAX_MPA,
        color="gray",
        linestyle="--",
        linewidth=1.0,
        alpha=0.7,
        label=f"Hu & Bai Fig.3.3 sim ymax (~{_PAPER_FIG33_STRESS_MAX_MPA:g} MPa)",
    )

    ax.set_xlabel("Engineering strain")
    ax.set_ylabel("Engineering stress (MPa)")
    ax.set_title(
        "Hu & Bai 4x4x4 paper_box — CAE C3D4 0.6 mm, 80% @ 5 mm/min\n"
        "● εd (this run, η peak)   □ εd (thesis §3.3.1 sim)"
    )
    ax.grid(True, alpha=0.35)
    ax.legend(loc="upper left", fontsize=8)
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
    parser = argparse.ArgumentParser(description="Plot paperbox CAE tet comparison")
    parser.add_argument(
        "--png",
        default=str(REPORTS_ROOT / "paperbox_cae_tet0p6mm80_5mmin_stress_strain_compare.png"),
    )
    parser.add_argument("--show", action="store_true")
    args = parser.parse_args()

    series: list[tuple[str, list[float], list[float], str, dict[str, float], float | None]] = []
    for slug, label, color, paper_key in _CASES:
        csv = ABAQUS_POST / slug / f"{slug}_stress_strain.csv"
        if not csv.is_file():
            print(f"[WARN] Missing: {csv}")
            continue
        strains, stresses = load_csv(str(csv))
        if not strains:
            print(f"[WARN] Empty: {csv}")
            continue
        dens = estimate_densification_strain(strains, stresses)
        paper_ed = HU_BAI_PAPER_DENSIFICATION_STRAIN.get(paper_key)
        peak_i = max(range(len(stresses)), key=lambda i: stresses[i])
        ed = dens["densification_strain"]
        sd = dens["densification_stress_MPa"]
        print(
            f"{label}: {len(strains)} pts, peak {stresses[peak_i]:.4f} MPa @ ε={strains[peak_i]:.4f}; "
            f"εd={ed:.3f} (σ={sd:.4f} MPa)"
            + (f"; thesis εd={paper_ed:.2f}" if paper_ed is not None else "")
        )
        series.append((label, strains, stresses, color, dens, paper_ed))

    if not series:
        print("[ERROR] No curves found")
        return 1

    plot_compare(series, save_path=args.png, show=args.show)
    return 0


if __name__ == "__main__":
    sys.exit(main())
