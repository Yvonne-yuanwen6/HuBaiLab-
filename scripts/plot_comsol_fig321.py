#!/usr/bin/env python3
"""Assemble thesis Fig. 3.21 — first three eigenmode shapes for four lattice variants."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Row order matches thesis Fig. 3.21
FIG321_ROWS: tuple[tuple[str, str], ...] = (
    ("bcc", "(a) BCC"),
    ("af2q05", "(b) AF2Q0.5"),
    ("af2q1", "(c) AF2Q1"),
    ("af2q15", "(d) AF2Q1.5"),
)

COL_TITLES = ("第 1 阶", "第 2 阶", "第 3 阶")


def _load_meta(job_dir: Path, slug: str) -> dict | None:
    meta_path = job_dir / f"{slug}_mode_shapes.json"
    if meta_path.is_file():
        return json.loads(meta_path.read_text(encoding="utf-8"))
    return None


def _mode_png(job_dir: Path, slug: str, rank: int) -> Path | None:
    p = job_dir / f"{slug}_mode{rank:02d}.png"
    return p if p.is_file() else None


def plot_fig321(
    cases: list[dict],
    out_png: Path,
    *,
    suptitle: str = "图 3.21  BCC 与 SFBLS 隔振结构前三阶模态",
) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.image as mpimg
    import matplotlib.pyplot as plt

    from src.postprocess.fig33_plot_style import configure_matplotlib_chinese

    configure_matplotlib_chinese()

    nrows = len(cases)
    ncols = 3
    fig, axes = plt.subplots(nrows, ncols, figsize=(11, 3.2 * nrows))
    if nrows == 1:
        axes = [axes]

    for row, case in enumerate(cases):
        label = case["label"]
        job_dir = Path(case["job_dir"])
        slug = case["slug"]
        meta = _load_meta(job_dir, slug)
        freqs = [m["frequency_Hz"] for m in meta.get("modes", [])] if meta else []

        for col in range(ncols):
            ax = axes[row][col]
            png = _mode_png(job_dir, slug, col + 1)
            if png is not None:
                ax.imshow(mpimg.imread(str(png)))
            else:
                ax.text(0.5, 0.5, "无数据", ha="center", va="center", transform=ax.transAxes)
            ax.set_xticks([])
            ax.set_yticks([])
            if col == 0:
                ax.set_ylabel(label, fontsize=11, rotation=0, labelpad=42, va="center")
            if row == 0:
                ax.set_title(COL_TITLES[col], fontsize=11)
            if col < len(freqs):
                ax.text(
                    0.03,
                    0.97,
                    f"{freqs[col]:.1f} Hz",
                    transform=ax.transAxes,
                    fontsize=9,
                    va="top",
                    color="white",
                    bbox=dict(boxstyle="round,pad=0.2", facecolor="black", alpha=0.55),
                )

    fig.suptitle(suptitle, fontsize=13, y=1.01)
    fig.tight_layout()
    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png, dpi=180, bbox_inches="tight")
    plt.close(fig)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compose thesis Fig. 3.21 from exported mode PNGs.")
    parser.add_argument(
        "--jobs-root",
        default=str(ROOT / "output/comsol_jobs"),
        help="Root directory containing per-case job folders",
    )
    parser.add_argument(
        "--out",
        default=str(ROOT / "output/comsol_jobs/fig321_composite/fig321_eigenmodes.png"),
    )
    parser.add_argument(
        "--slug-map",
        default="",
        help='JSON map row_key→slug, e.g. {"bcc":"comsol_fig321_bcc_444",...}',
    )
    args = parser.parse_args(argv)

    jobs_root = Path(args.jobs_root)
    default_slugs = {
        "bcc": "comsol_fig321_bcc_444",
        "af2q05": "comsol_fig321_af2q05_444",
        "af2q1": "comsol_fig321_af2q1_444",
        "af2q15": "comsol_fig321_af2q15_444",
    }
    if args.slug_map:
        slug_map = json.loads(args.slug_map)
    else:
        slug_map = default_slugs

    cases: list[dict] = []
    for key, label in FIG321_ROWS:
        slug = slug_map[key]
        job_dir = jobs_root / slug
        cases.append({"key": key, "label": label, "slug": slug, "job_dir": str(job_dir)})

    out_png = Path(args.out)
    plot_fig321(cases, out_png)
    print(f"Saved: {out_png}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
