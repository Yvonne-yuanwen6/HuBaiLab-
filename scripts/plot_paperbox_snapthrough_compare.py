"""
Overlay baseline vs snap-through sweep variants (BCC + Q0.5).

  py -3 scripts/plot_paperbox_snapthrough_compare.py
"""

from __future__ import annotations

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from scripts.plot_stress_strain import load_csv
from src.paths import ABAQUS_POST, REPORTS_ROOT

_VARIANTS = (
    ("baseline", "cae_tet0p6mm80_5mmin_paperbox", "#333333", "-"),
    ("B nosettle", "cae_tet0p6mm80_5mmin_paperbox_paperbox_nosettle", "#1565C0", "-"),
    ("D dt1e-4", "cae_tet0p6mm80_5mmin_paperbox_paperbox_nosettle_dt1e4", "#E53935", "--"),
    ("E nohold", "cae_tet0p6mm80_5mmin_paperbox_paperbox_nosettle_dt1e4_nohold", "#FB8C00", "-."),
)
_TAGS = (
    ("BCC Q=0", "bcc_af2q0"),
    ("SFBLS Q=0.5", "sfbls_af2q0p5"),
)


def main() -> int:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, 2, figsize=(14, 5.5), sharey=True)
    for ax, (title, tag) in zip(axes, _TAGS):
        for vlabel, suffix, color, ls in _VARIANTS:
            slug = f"hu_bai_{tag}_L20_4x4x4_solid_cad_f_{suffix}"
            csv = ABAQUS_POST / slug / f"{slug}_stress_strain.csv"
            if not csv.is_file():
                continue
            eps, sig = load_csv(str(csv))
            ax.plot(eps, sig, color=color, ls=ls, lw=1.6, label=vlabel)
        ax.axhline(0.04, color="gray", ls=":", alpha=0.6)
        ax.set_title(title)
        ax.set_xlabel("Engineering strain")
        ax.grid(True, alpha=0.3)
        ax.legend(fontsize=8)
    axes[0].set_ylabel("Engineering stress (MPa)")
    fig.suptitle("Snap-through sweep vs baseline (paper_box CAE C3D4)")
    fig.tight_layout()
    out = REPORTS_ROOT / "paperbox_snapthrough_sweep_compare.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=150)
    print("Saved:", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
