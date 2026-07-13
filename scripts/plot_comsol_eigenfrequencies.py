#!/usr/bin/env python3
"""Plot COMSOL eigenfrequency CSV (mode index vs frequency)."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(description="Plot COMSOL eigenfrequencies CSV.")
    parser.add_argument(
        "csv",
        nargs="?",
        default=str(ROOT / "output/comsol_jobs/comsol_iso_af2q0_444/comsol_iso_af2q0_444_eigenfrequencies.csv"),
    )
    parser.add_argument(
        "--out",
        default="",
        help="PNG path (default: same stem as CSV)",
    )
    parser.add_argument("--title", default="")
    args = parser.parse_args()

    csv_path = Path(args.csv).resolve()
    if not csv_path.is_file():
        raise SystemExit(f"Not found: {csv_path}")

    modes: list[int] = []
    freqs: list[float] = []
    with csv_path.open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            modes.append(int(row["mode"]))
            freqs.append(float(row["frequency_Hz"]))

    out_path = Path(args.out) if args.out else csv_path.with_suffix(".png")
    job_dir = csv_path.parent
    title = args.title
    if not title:
        manifest = job_dir / "case_manifest.json"
        if manifest.is_file():
            data = json.loads(manifest.read_text(encoding="utf-8"))
            slug = data.get("slug", csv_path.stem)
            geom = data.get("geometry", {})
            cells = geom.get("cells", [])
            cell_str = "×".join(str(c) for c in cells)
            title = f"{slug}（{cell_str} 胞元，特征频率）"

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    from src.postprocess.fig33_plot_style import configure_matplotlib_chinese

    configure_matplotlib_chinese()

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 4.5))

    ax1.plot(modes, freqs, "o-", color="#1565C0", markersize=5, linewidth=1.2)
    ax1.set_xlabel("模态阶次")
    ax1.set_ylabel("频率 (Hz)")
    ax1.set_title("特征频率")
    ax1.grid(True, alpha=0.3)

    ax2.semilogy(modes, freqs, "s-", color="#C62828", markersize=5, linewidth=1.2)
    ax2.set_xlabel("模态阶次")
    ax2.set_ylabel("频率 (Hz)")
    ax2.set_title("特征频率（对数坐标）")
    ax2.grid(True, which="both", alpha=0.3)

    fig.suptitle(title, fontsize=11)
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=160, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {out_path}")
    print(f"Modes: {len(freqs)}, f1={freqs[0]:.2f} Hz, f30={freqs[-1]:.2f} Hz")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
