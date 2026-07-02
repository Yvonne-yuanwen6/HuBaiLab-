"""
Plot BCC paper_box: baseline (ContactSettle) vs nosettle (partial OK).

  py -3 scripts/plot_bcc_paperbox_baseline_vs_nosettle.py
"""

from __future__ import annotations

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

_CASES = (
    (
        "hu_bai_bcc_af2q0_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox",
        "BCC baseline (ContactSettle + STORE OFFSETS)",
        "#1565C0",
    ),
    (
        "hu_bai_bcc_af2q0_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox_paperbox_nosettle",
        "BCC nosettle (no ContactSettle, ~86% run)",
        "#E53935",
    ),
)

_PAPER_ED = HU_BAI_PAPER_DENSIFICATION_STRAIN.get("bcc", 0.70)
_PAPER_YMAX = 0.04


def main() -> int:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(10, 6))
    loaded = 0
    for slug, label, color in _CASES:
        csv = ABAQUS_POST / slug / f"{slug}_stress_strain.csv"
        if not csv.is_file():
            print(f"[WARN] Missing: {csv}")
            continue
        eps, sig = load_csv(str(csv))
        if not eps:
            continue
        loaded += 1
        ax.plot(eps, sig, color=color, linewidth=1.8, label=label)
        dens = estimate_densification_strain(eps, sig)
        ed = dens["densification_strain"]
        sd = dens["densification_stress_MPa"]
        if ed == ed and sd == sd:
            ax.scatter([ed], [sd], color=color, s=40, zorder=5, edgecolors="black", linewidths=0.5)
            ax.annotate(f"εd={ed:.2f}", xy=(ed, sd), xytext=(6, 6), textcoords="offset points", fontsize=8, color=color)
        peak_i = max(range(len(sig)), key=lambda i: sig[i])
        print(f"{label}: {len(eps)} pts, peak {sig[peak_i]:.4f} MPa @ ε={eps[peak_i]:.4f}")

    if not loaded:
        print("[ERROR] No curves loaded")
        return 1

    ax.axhline(_PAPER_YMAX, color="gray", linestyle="--", alpha=0.6, label=f"Fig.3.3 ymax ~{_PAPER_YMAX:g} MPa")
    ax.axvline(_PAPER_ED, color="gray", linestyle=":", alpha=0.5)
    ax.scatter([_PAPER_ED], [_PAPER_YMAX * 0.5], facecolors="none", edgecolors="gray", s=50, marker="s", label=f"paper εd={_PAPER_ED:.2f}")
    ax.set_xlabel("Engineering strain")
    ax.set_ylabel("Engineering stress (MPa)")
    ax.set_title("BCC paper_box CAE C3D4 — baseline vs nosettle")
    ax.grid(True, alpha=0.35)
    ax.legend(loc="upper left", fontsize=8)
    fig.tight_layout()
    out = REPORTS_ROOT / "bcc_paperbox_baseline_vs_nosettle.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=150)
    print("Saved:", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
