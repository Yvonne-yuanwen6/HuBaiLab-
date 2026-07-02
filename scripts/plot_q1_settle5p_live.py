"""Plot live Q1 settle5p partial curve vs baseline at same sim time."""
from __future__ import annotations

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from scripts.plot_stress_strain import load_csv
from src.paths import ABAQUS_POST, REPORTS_ROOT

_Q1 = (
    "hu_bai_sfbls_af2q1_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox_paperbox_settle5p"
)
_BASE = "hu_bai_sfbls_af2q1_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox"


def main() -> int:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    q1_csv = ABAQUS_POST / _Q1 / f"{_Q1}_stress_strain_live.csv"
    base_csv = ABAQUS_POST / _BASE / f"{_BASE}_stress_strain_partial.csv"
    png = REPORTS_ROOT / "q1_settle5p_live_stress_strain.png"

    fig, ax = plt.subplots(figsize=(9, 5.5))
    for path, label, color in (
        (base_csv, "Q1 baseline settle15% (same sim time ~88s)", "#F48FB1"),
        (q1_csv, "Q1 settle5p live readOnly ODB", "#1565C0"),
    ):
        if not path.is_file():
            print(f"[WARN] missing {path}")
            continue
        s, st = load_csv(str(path))
        ax.plot(s, st, color=color, lw=2, marker="o", ms=6, label=label)
        if s:
            print(f"{label}: {len(s)} pts, last eps={s[-1]:.4f}, sig={st[-1]:.4f} MPa")

    ax.set_xlabel("Engineering strain")
    ax.set_ylabel("Engineering stress (MPa)")
    ax.set_title(
        "Q1 paperbox settle5p — live partial curve (sim ~88 s, ~9% est.)\n"
        "Server readOnly ODB extract (job uninterrupted)"
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
