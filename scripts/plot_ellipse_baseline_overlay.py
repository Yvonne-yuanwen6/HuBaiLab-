"""
Overlay ellipse 4×4×4 Neo-Hooke paperbox stress-strain for completed Q/align cases.

Per-Q ellmaj vs ellmin overlays, plus one multi-panel PNG (subplot per Q).

  py -3 scripts/plot_ellipse_baseline_overlay.py
  py -3 scripts/plot_ellipse_baseline_overlay.py --with-circular
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

_BASE = "cae_tet0p6mm80_5mmin_paperbox"

# (q_label, align, slug_prefix_variant, color)
CASES = (
    ("Q=0", "ellmaj", "bcc_af2q0", "#1565C0"),
    ("Q=0", "ellmin", "bcc_af2q0", "#C62828"),
    ("Q=0.5", "ellmaj", "sfbls_af2q0p5", "#00838F"),
    ("Q=0.5", "ellmin", "sfbls_af2q0p5", "#EF6C00"),
    ("Q=1", "ellmaj", "sfbls_af2q1", "#6A1B9A"),
    ("Q=1", "ellmin", "sfbls_af2q1", "#AD1457"),
)

Q_ORDER = ("Q=0", "Q=0.5", "Q=1", "Q=1.5")

# Preferred circular (round-strut) Neo-Hooke paperbox CSVs; later entries are fallbacks.
CIRC_CANDIDATES: dict[str, tuple[str, ...]] = {
    "Q=0": (f"hu_bai_bcc_af2q0_L20_4x4x4_solid_cad_f_{_BASE}",),
    "Q=0.5": (f"hu_bai_sfbls_af2q0p5_L20_4x4x4_solid_cad_f_{_BASE}",),
    "Q=1": (
        f"hu_bai_sfbls_af2q1_L20_4x4x4_solid_cad_f_{_BASE}",
        # No exact settle-15% circular Q=1 archive; nosettle Neo-Hooke is closest available.
        f"hu_bai_sfbls_af2q1_L20_4x4x4_solid_cad_f_{_BASE}_paperbox_nosettle",
    ),
}


def _slug(variant: str, align: str) -> str:
    return f"hu_bai_{variant}_L20_4x4x4_solid_cad_f_{_BASE}_ellipse_{align}"


def _load_case(variant: str, align: str) -> tuple[list[float], list[float]] | None:
    slug = _slug(variant, align)
    csv = ABAQUS_POST / slug / f"{slug}_stress_strain.csv"
    if not csv.is_file():
        return None
    return load_csv(str(csv))


def _load_circular(q_lab: str) -> tuple[str, list[float], list[float]] | None:
    for slug in CIRC_CANDIDATES.get(q_lab, ()):
        csv = ABAQUS_POST / slug / f"{slug}_stress_strain.csv"
        if csv.is_file():
            strains, stresses = load_csv(str(csv))
            return ("circular", strains, stresses)
    return None


def plot_panel(
    series: list[tuple[str, list[float], list[float], str]],
    *,
    title: str,
    save_path: str,
    circ: list[tuple[str, list[float], list[float]]] | None = None,
) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(8.5, 5.5))
    for label, strains, stresses, color in series:
        ax.plot(strains, stresses, color=color, linewidth=1.9, label=label)

    if circ:
        for label, strains, stresses in circ:
            ax.plot(
                strains,
                stresses,
                color="#616161",
                linewidth=1.3,
                linestyle="--",
                label=label,
            )

    ax.set_xlabel("Engineering strain")
    ax.set_ylabel("Engineering stress (MPa)")
    ax.set_title(title)
    ax.grid(True, alpha=0.35)
    ax.legend(loc="best", fontsize=8)
    fig.tight_layout()
    os.makedirs(os.path.dirname(save_path) or ".", exist_ok=True)
    fig.savefig(save_path, dpi=150)
    plt.close(fig)
    print("Saved:", save_path)


def plot_subplot_grid(
    by_q: dict[str, list[tuple[str, list[float], list[float], str]]],
    *,
    save_path: str,
    with_circular: bool,
) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    q_present = [q for q in Q_ORDER if q in by_q and by_q[q]]
    if not q_present:
        print("[ERROR] no Q panels to plot")
        return

    n = len(q_present)
    ncols = min(3, n)
    nrows = (n + ncols - 1) // ncols
    fig, axes = plt.subplots(
        nrows,
        ncols,
        figsize=(5.2 * ncols, 4.4 * nrows),
        squeeze=False,
        sharex=True,
        sharey=True,
    )

    for idx, q_lab in enumerate(q_present):
        r, c = divmod(idx, ncols)
        ax = axes[r][c]
        for label, strains, stresses, color in by_q[q_lab]:
            ax.plot(strains, stresses, color=color, linewidth=1.8, label=label)
        if with_circular:
            circ = _load_circular(q_lab)
            if circ is not None:
                clab, cs, ct = circ
                ax.plot(
                    cs,
                    ct,
                    color="#616161",
                    linewidth=1.4,
                    linestyle="--",
                    label=clab,
                )
        ax.set_title(q_lab)
        ax.grid(True, alpha=0.35)
        ax.legend(loc="best", fontsize=8)
        if r == nrows - 1:
            ax.set_xlabel("Engineering strain")
        if c == 0:
            ax.set_ylabel("Engineering stress (MPa)")

    # hide unused axes
    for j in range(n, nrows * ncols):
        r, c = divmod(j, ncols)
        axes[r][c].set_visible(False)

    fig.suptitle(
        "Ellipse 4×4×4 Neo-Hooke baseline — by Q (ellmaj / ellmin overlay)",
        fontsize=12,
        y=1.02,
    )
    fig.tight_layout()
    os.makedirs(os.path.dirname(save_path) or ".", exist_ok=True)
    fig.savefig(save_path, dpi=160, bbox_inches="tight")
    plt.close(fig)
    print("Saved:", save_path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--out-dir",
        default=str(REPORTS_ROOT / "ellipse_baseline"),
    )
    parser.add_argument("--with-circular", action="store_true")
    args = parser.parse_args()
    out_dir = os.path.abspath(args.out_dir)
    os.makedirs(out_dir, exist_ok=True)

    loaded: list[tuple[str, str, str, str, list[float], list[float]]] = []
    for q_lab, align, variant, color in CASES:
        data = _load_case(variant, align)
        if data is None:
            print(f"[SKIP] missing {q_lab} {align}")
            continue
        strains, stresses = data
        peak_i = max(range(len(stresses)), key=lambda i: stresses[i])
        label = f"{align}"
        print(
            f"{q_lab} {align}: n={len(strains)} "
            f"peak={stresses[peak_i]:.3f} MPa @ eps={strains[peak_i]:.4f}"
        )
        loaded.append((q_lab, align, label, color, strains, stresses))

    if not loaded:
        print("[ERROR] no completed ellipse CSVs found")
        return 1

    by_q: dict[str, list] = {}
    for q_lab, align, label, color, strains, stresses in loaded:
        by_q.setdefault(q_lab, []).append((label, strains, stresses, color))

    for q_lab, series in by_q.items():
        circ = None
        if args.with_circular:
            one = _load_circular(q_lab)
            if one is not None:
                circ = [one]
        tag = q_lab.replace("=", "").replace(".", "p").lower()
        png = os.path.join(out_dir, f"{tag}_ellmaj_vs_ellmin_neohooke.png")
        plot_panel(
            series,
            title=f"Ellipse 4×4×4 {q_lab} — Neo-Hooke baseline (80% strain, 5 mm/min)",
            save_path=png,
            circ=circ,
        )

    subplot_name = "by_q_subplots_ellmaj_ellmin_neohooke.png"
    subplot_path = os.path.join(out_dir, subplot_name)
    plot_subplot_grid(
        by_q,
        save_path=subplot_path,
        with_circular=bool(args.with_circular),
    )
    if args.with_circular:
        alt = os.path.join(out_dir, "by_q_subplots_ellmaj_ellmin_circular_neohooke.png")
        if os.path.abspath(alt) != os.path.abspath(subplot_path):
            import shutil

            shutil.copy2(subplot_path, alt)
            print("Saved:", alt)

    all_series = [
        (f"{q} {lab}", s, t, c) for q, _, lab, c, s, t in loaded
    ]
    circ_all = []
    if args.with_circular:
        for q_lab in by_q:
            one = _load_circular(q_lab)
            if one is not None:
                circ_all.append((f"{q_lab} circular", one[1], one[2]))
    plot_panel(
        all_series,
        title="Ellipse 4×4×4 completed — Neo-Hooke baseline overlay",
        save_path=os.path.join(
            out_dir,
            "completed_ellmaj_ellmin_circular_neohooke.png"
            if args.with_circular
            else "completed_ellmaj_ellmin_neohooke.png",
        ),
        circ=circ_all or None,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
