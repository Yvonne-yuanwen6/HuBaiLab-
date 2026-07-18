#!/usr/bin/env python3
"""2×2 grid of P1 payload VLD overlays for BCC / AF2Q0.5 / AF2Q1 / AF2Q1.5."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.plot_comsol_vld_payload_overlay import (
    DEFAULT_COLORS,
    PAYLOAD_PRESETS,
    _read_rows,
    payload_f5_150_cases,
)
from src.comsol.plot_isolation import rows_to_series

GRID_ORDER = ("bcc", "af2q05", "af2q1", "af2q15")
PANEL_TITLES = {
    "bcc": "BCC (Q=0)",
    "af2q05": "AF2Q0.5",
    "af2q1": "AF2Q1",
    "af2q15": "AF2Q1.5",
}


def _load_variant_series(variant: str) -> list[tuple[str, list[dict]]]:
    jobs = ROOT / "output/comsol_jobs"
    series: list[tuple[str, list[dict]]] = []
    for label, slug in payload_f5_150_cases(variant):
        csv_path = jobs / slug / f"{slug}_transmissibility.csv"
        if not csv_path.is_file():
            raise FileNotFoundError(f"Missing CSV for {variant}: {csv_path}")
        series.append((label, _read_rows(csv_path)))
    return series


def plot_four_struct_grid(
    out_png: Path,
    *,
    plot: str = "vld",
    suptitle: str = "P1  5–150 Hz  四结构顶载 VLD 叠图",
) -> Path:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    from src.postprocess.fig33_plot_style import configure_matplotlib_chinese

    configure_matplotlib_chinese()
    fig, axes = plt.subplots(2, 2, figsize=(12.0, 8.5), sharex=True)
    axes_flat = axes.ravel()

    legend_handles: list = []
    legend_labels: list[str] = []

    for ax, variant in zip(axes_flat, GRID_ORDER):
        preset = PAYLOAD_PRESETS[variant]
        paper_hz = list(preset["paper_hz"])  # type: ignore[arg-type]
        series = _load_variant_series(variant)

        for i, (label, rows) in enumerate(series):
            freqs, trans, vld = rows_to_series(rows)
            color = DEFAULT_COLORS[i % len(DEFAULT_COLORS)]
            if plot == "trans":
                line, = ax.semilogy(freqs, trans, "-", color=color, linewidth=1.4, label=label)
            else:
                line, = ax.plot(freqs, vld, "-", color=color, linewidth=1.4, label=label)
            if variant == GRID_ORDER[0]:
                legend_handles.append(line)
                legend_labels.append(label)

        for j, pf in enumerate(paper_hz[:3]):
            ax.axvline(
                pf,
                color="#9E9E9E",
                linestyle=":",
                linewidth=0.9,
                alpha=0.55,
            )

        if plot == "trans":
            ax.axhline(1.0, color="#757575", linestyle="--", linewidth=0.9)
            ax.set_ylabel("传递率 T")
        else:
            ax.axhline(0.0, color="#757575", linestyle="--", linewidth=0.9)
            ax.set_ylabel("VLD (dB)")

        ax.set_title(PANEL_TITLES[variant], fontsize=11)
        ax.grid(True, which="both" if plot == "trans" else "major", alpha=0.3)

    for ax in axes[1, :]:
        ax.set_xlabel("频率 (Hz)")
    for ax in axes[:, 0]:
        if plot == "trans":
            ax.set_ylabel("传递率 T（式 3.20）")
        else:
            ax.set_ylabel("VLD (dB)  式 (3.6)")

    fig.suptitle(suptitle, fontsize=13, y=0.98)
    fig.legend(
        legend_handles,
        legend_labels,
        loc="lower center",
        ncol=4,
        bbox_to_anchor=(0.5, 0.02),
        fontsize=9,
        frameon=True,
    )
    fig.tight_layout(rect=(0.0, 0.06, 1.0, 0.96))
    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png, dpi=180, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return out_png


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="2×2 payload VLD grid for four lattice structures.")
    parser.add_argument(
        "--out-dir",
        default="output/comsol_jobs/payload_composite_4struct",
    )
    parser.add_argument("--slug", default="payload_p1_f5_150_4struct")
    parser.add_argument("--with-trans", action="store_true")
    args = parser.parse_args(argv)

    out_dir = Path(args.out_dir).resolve()
    vld_png = plot_four_struct_grid(out_dir / f"{args.slug}_vld_2x2.png", plot="vld")
    print(f"Saved: {vld_png}")

    outputs = {"vld_png": str(vld_png)}
    if args.with_trans:
        trans_png = plot_four_struct_grid(
            out_dir / f"{args.slug}_transmissibility_2x2.png",
            plot="trans",
            suptitle="P1  5–150 Hz  四结构顶载传递率叠图",
        )
        outputs["transmissibility_png"] = str(trans_png)
        print(f"Saved: {trans_png}")

    meta = {
        "slug": args.slug,
        "variants": list(GRID_ORDER),
        "layout": "2x2",
        "outputs": outputs,
    }
    meta_path = out_dir / f"{args.slug}_summary.json"
    meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Summary: {meta_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
