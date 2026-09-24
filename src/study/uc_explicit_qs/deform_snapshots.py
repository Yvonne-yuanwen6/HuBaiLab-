"""Plot deformed-shape snapshots (0/30/60/100%) for snap-through inspection."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any


def plot_deform_snapshots(
    deform_dir: Path,
    out_dir: Path,
    *,
    case_id: str,
    title_prefix: str = "",
) -> list[str]:
    """Read deform_*pct.csv and write orthogonal + 3D overview PNGs."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from mpl_toolkits.mplot3d import Axes3D  # noqa: F401

    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    csvs = sorted(deform_dir.glob("deform_*pct.csv"))
    if not csvs:
        return written

    # Combined 2x2 figure
    fig, axes = plt.subplots(2, 2, figsize=(10.5, 9.0), subplot_kw={"projection": "3d"})
    axes_flat = list(axes.ravel())

    for i, csv_path in enumerate(csvs[:4]):
        rows = []
        with csv_path.open(newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                try:
                    rows.append(
                        (
                            float(row["x"]),
                            float(row["y"]),
                            float(row["z"]),
                            float(row.get("u_mag") or 0.0),
                        )
                    )
                except (KeyError, ValueError):
                    continue
        if not rows:
            continue
        # Downsample for plotting speed
        step = max(1, len(rows) // 8000)
        pts = rows[::step]
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        zs = [p[2] for p in pts]
        um = [p[3] for p in pts]

        ax = axes_flat[i]
        sc = ax.scatter(xs, ys, zs, c=um, s=2, cmap="viridis", linewidths=0)
        pct = csv_path.stem.replace("deform_", "").replace("pct", "")
        ax.set_title(f"{case_id} @ {pct}%")
        ax.set_xlabel("X")
        ax.set_ylabel("Y")
        ax.set_zlabel("Z")
        # Isometric-ish view: look along +Y to see curved rods buckling in XZ
        ax.view_init(elev=18, azim=-60)
        fig.colorbar(sc, ax=ax, shrink=0.55, label="|U| mm")

        # Also save single frame XY / XZ projections for snap judgment
        fig2, (ax_xz, ax_xy) = plt.subplots(1, 2, figsize=(9.5, 4.2))
        ax_xz.scatter(xs, zs, c=um, s=2, cmap="viridis", linewidths=0)
        ax_xz.set_xlabel("X (mm)")
        ax_xz.set_ylabel("Z (mm)")
        ax_xz.set_title(f"{case_id} XZ @ {pct}%")
        ax_xz.set_aspect("equal", adjustable="datalim")
        ax_xz.grid(True, alpha=0.25)
        ax_xy.scatter(xs, ys, c=um, s=2, cmap="viridis", linewidths=0)
        ax_xy.set_xlabel("X (mm)")
        ax_xy.set_ylabel("Y (mm)")
        ax_xy.set_title(f"{case_id} XY @ {pct}%")
        ax_xy.set_aspect("equal", adjustable="datalim")
        ax_xy.grid(True, alpha=0.25)
        fig2.suptitle(f"{title_prefix}{case_id} deformation {pct}%".strip())
        fig2.tight_layout()
        single = out_dir / f"{case_id}_deform_{pct}pct.png"
        fig2.savefig(single, dpi=140)
        plt.close(fig2)
        written.append(str(single))

    fig.suptitle(f"{title_prefix}{case_id} — compression snapshots (snap-through check)".strip())
    fig.tight_layout()
    grid = out_dir / f"{case_id}_deform_grid.png"
    fig.savefig(grid, dpi=140)
    plt.close(fig)
    written.append(str(grid))
    return written


def summarize_snap_proxy(fu_points: list[tuple[float, float]]) -> dict[str, Any]:
    """Simple force-drop snap proxy from F–U curve."""
    if len(fu_points) < 5:
        return {"snap_detected": False, "reason": "too_few_points"}
    peak_f = max(f for _, f in fu_points)
    peak_u = next(u for u, f in fu_points if f == peak_f)
    # After peak, look for drop > 8%
    after = [(u, f) for u, f in fu_points if u >= peak_u]
    if not after:
        return {"snap_detected": False, "peak_force_N": peak_f, "peak_u_mm": peak_u}
    fmin = min(f for _, f in after)
    drop = (peak_f - fmin) / peak_f if peak_f > 1e-12 else 0.0
    return {
        "snap_detected": drop >= 0.08,
        "peak_force_N": peak_f,
        "peak_u_mm": peak_u,
        "post_peak_min_force_N": fmin,
        "force_drop_frac": drop,
    }
