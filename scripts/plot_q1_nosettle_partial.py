"""Plot partial Q1 nosettle live curve vs baseline at same sim time."""
from __future__ import annotations

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from scripts.plot_stress_strain import load_csv
from src.paths import ABAQUS_POST, REPORTS_ROOT

_NOS = (
    "hu_bai_sfbls_af2q1_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox_paperbox_nosettle"
)
_BASE = "hu_bai_sfbls_af2q1_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox"


def main() -> int:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    nos_csv = ABAQUS_POST / _NOS / f"{_NOS}_stress_strain_live.csv"
    base_csv = ABAQUS_POST / _BASE / f"{_BASE}_stress_strain_partial.csv"
    png = REPORTS_ROOT / "q1_nosettle_partial_stress_strain.png"

    curves = []
    for path, label, color in (
        (base_csv, "Q1 baseline (ContactSettle, same sim time)", "#F48FB1"),
        (nos_csv, "Q1 nosettle (live, readOnly ODB)", "#1565C0"),
    ):
        if not path.is_file():
            print(f"[WARN] missing {path}")
            continue
        s, st = load_csv(str(path))
        curves.append((label, s, st, color))
        print(f"{label}: {len(s)} pts, last ε={s[-1]:.4f}, σ={st[-1]:.4f} MPa")

    if not curves:
        print("[ERROR] no curves")
        return 1

    fig, ax = plt.subplots(figsize=(9, 5.5))
    for label, s, st, color in curves:
        ax.plot(s, st, color=color, linewidth=2.0, marker="o", markersize=5, label=label)

    ax.set_xlabel("Engineering strain")
    ax.set_ylabel("Engineering stress (MPa)")
    ax.set_title(
        "Q1 paper_box partial curve — nosettle vs baseline (matched sim time)\n"
        "Server readOnly ODB extract (no job interruption)"
    )
    ax.grid(True, alpha=0.35)
    ax.legend(loc="upper left", fontsize=9)
    fig.tight_layout()
    os.makedirs(REPORTS_ROOT, exist_ok=True)
    fig.savefig(png, dpi=150)
    print("Saved:", png)
    plt.close(fig)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
