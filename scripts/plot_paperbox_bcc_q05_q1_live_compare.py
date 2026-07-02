"""Plot BCC baseline + live Q0.5 nosettle + live Q1 settle5p on one figure."""
from __future__ import annotations

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from scripts.plot_stress_strain import load_csv
from src.paths import ABAQUS_POST, REPORTS_ROOT

_CASES = (
    (
        "hu_bai_bcc_af2q0_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox",
        "BCC Q=0 baseline (full, completed)",
        "#89CFF0",
        "_stress_strain.csv",
    ),
    (
        "hu_bai_sfbls_af2q0p5_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox_paperbox_nosettle",
        "Q0.5 nosettle (live partial)",
        "#1565C0",
        "_stress_strain_live.csv",
    ),
    (
        "hu_bai_sfbls_af2q1_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox_paperbox_settle5p",
        "Q1 settle5p (live partial)",
        "#F48FB1",
        "_stress_strain_live.csv",
    ),
)


def main() -> int:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(10, 6))
    series: list[tuple[str, list[float], list[float], str]] = []

    for slug, label, color, suffix in _CASES:
        csv = ABAQUS_POST / slug / f"{slug}{suffix}"
        if not csv.is_file():
            print(f"[WARN] missing {csv}")
            continue
        s, st = load_csv(str(csv))
        if not s:
            print(f"[WARN] empty {csv}")
            continue
        series.append((label, s, st, color))
        print(f"{label}: {len(s)} pts, last eps={s[-1]:.4f}, sig={st[-1]:.4f} MPa")

    if not series:
        print("[ERROR] no curves")
        return 1

    for label, s, st, color in series:
        ax.plot(s, st, color=color, linewidth=1.8, label=label)

    ax.set_xlabel("Engineering strain")
    ax.set_ylabel("Engineering stress (MPa)")
    ax.set_title(
        "paper_box CAE C3D4 — BCC baseline vs live Q0.5 / Q1\n"
        "readOnly ODB extract (jobs uninterrupted)"
    )
    ax.grid(True, alpha=0.35)
    ax.legend(loc="upper left", fontsize=9)
    fig.tight_layout()

    png = REPORTS_ROOT / "paperbox_bcc_q05_q1_live_stress_strain_compare.png"
    os.makedirs(REPORTS_ROOT, exist_ok=True)
    fig.savefig(png, dpi=150)
    print("Saved:", png)
    plt.close(fig)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
