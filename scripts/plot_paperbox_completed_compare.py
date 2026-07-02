"""Overlay completed paperbox stress-strain curves (full ODB extract)."""
from __future__ import annotations

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from scripts.plot_stress_strain import load_csv
from src.paths import ABAQUS_POST, REPORTS_ROOT

_PAPER_YMAX = 0.04

_CASES = (
    (
        "hu_bai_bcc_af2q0_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox",
        "BCC Q=0 baseline (settle15%)",
        "#89CFF0",
        "-",
    ),
    (
        "hu_bai_sfbls_af2q0p5_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox_paperbox_nosettle",
        "Q0.5 nosettle",
        "#0D47A1",
        "--",
    ),
    (
        "hu_bai_sfbls_af2q0p5_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox_paperbox_settle5p",
        "Q0.5 settle5p (24c, completed)",
        "#1565C0",
        "-",
    ),
    (
        "hu_bai_sfbls_af2q1_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox",
        "Q1 baseline (settle15%)",
        "#F06292",
        ":",
    ),
    (
        "hu_bai_sfbls_af2q1_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox_paperbox_settle5p",
        "Q1 settle5p (completed)",
        "#C2185B",
        "-",
    ),
)


def main() -> int:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(10, 6))
    n = 0
    for slug, label, color, ls in _CASES:
        csv = ABAQUS_POST / slug / f"{slug}_stress_strain.csv"
        if not csv.is_file():
            print(f"[WARN] missing {csv}")
            continue
        eps, sig = load_csv(str(csv))
        if not eps:
            continue
        n += 1
        ax.plot(eps, sig, color=color, ls=ls, lw=1.8, label=label)
        print(f"{label}: {len(eps)} pts, peak={max(sig):.4f} MPa @ eps={eps[sig.index(max(sig))]:.3f}")

    if not n:
        print("[ERROR] no curves loaded")
        return 1

    ax.axhline(_PAPER_YMAX, color="gray", ls="--", alpha=0.65, label=f"Fig.3.3 ymax ~{_PAPER_YMAX:g} MPa")
    ax.set_xlabel("Engineering strain")
    ax.set_ylabel("Engineering stress (MPa)")
    ax.set_title("paper_box CAE C3D4 0.6 mm — completed runs compare")
    ax.grid(True, alpha=0.35)
    ax.legend(loc="upper left", fontsize=8)
    fig.tight_layout()

    out = REPORTS_ROOT / "paperbox_completed_stress_strain_compare.png"
    os.makedirs(REPORTS_ROOT, exist_ok=True)
    fig.savefig(out, dpi=150)
    print("Saved:", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
