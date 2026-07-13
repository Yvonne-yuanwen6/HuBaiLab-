#!/usr/bin/env python3
"""Overlay VLD / transmissibility curves for multiple top-payload cases."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.comsol.plot_isolation import rows_to_series

DEFAULT_COLORS = ("#1565C0", "#2E7D32", "#C62828", "#6A1B9A", "#EF6C00", "#00838F")
PAPER_BCC_HZ = [14.8, 49.8, 68.4]
PAPER_AF2Q05_HZ = [15.4, 53.9, 94.3]
PAPER_AF2Q1_HZ = [29.1, 44.4, 94.2]
PAPER_AF2Q15_HZ = [15.4, 40.6, 67.8]

PAYLOAD_PRESETS: dict[str, dict[str, object]] = {
    "bcc": {
        "prefix": "comsol_fig321_bcc_444_mesh_p1",
        "title": "BCC P1  5–150 Hz  不同顶载 VLD 叠图",
        "paper_hz": PAPER_BCC_HZ,
    },
    "af2q05": {
        "prefix": "comsol_fig321_af2q05_444_mesh_p1",
        "title": "AF2Q0.5 P1  5–150 Hz  不同顶载 VLD 叠图",
        "paper_hz": PAPER_AF2Q05_HZ,
    },
    "af2q1": {
        "prefix": "comsol_fig321_af2q1_444_mesh_p1",
        "title": "AF2Q1 P1  5–150 Hz  不同顶载 VLD 叠图",
        "paper_hz": PAPER_AF2Q1_HZ,
    },
    "af2q15": {
        "prefix": "comsol_fig321_af2q15_444_mesh_p1",
        "title": "AF2Q1.5 P1  5–150 Hz  不同顶载 VLD 叠图",
        "paper_hz": PAPER_AF2Q15_HZ,
    },
}


def payload_f5_150_cases(variant: str) -> list[tuple[str, str]]:
    preset = PAYLOAD_PRESETS[variant]
    prefix = str(preset["prefix"])
    return [
        ("0 g", f"{prefix}_f5_150"),
        ("100 g", f"{prefix}_100g_f5_150"),
        ("300 g", f"{prefix}_300g_f5_150"),
        ("500 g", f"{prefix}_500g_f5_150"),
    ]


def _read_rows(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def plot_payload_overlay(
    series: list[tuple[str, list[dict]]],
    out_png: Path,
    *,
    title: str,
    plot: str = "vld",
    paper_bcc: bool = False,
    paper_hz: Sequence[float] | None = None,
) -> Path:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    from src.postprocess.fig33_plot_style import configure_matplotlib_chinese

    configure_matplotlib_chinese()
    fig, ax = plt.subplots(figsize=(8.0, 4.8))

    for i, (label, rows) in enumerate(series):
        freqs, trans, vld = rows_to_series(rows)
        color = DEFAULT_COLORS[i % len(DEFAULT_COLORS)]
        if plot == "trans":
            ax.semilogy(freqs, trans, "-", color=color, linewidth=1.5, label=label)
        else:
            ax.plot(freqs, vld, "-", color=color, linewidth=1.5, label=label)

    if plot == "trans":
        ax.axhline(1.0, color="#757575", linestyle="--", linewidth=1.0, label="T = 1")
        ax.set_ylabel("传递率 T（式 3.20）")
    else:
        ax.axhline(0.0, color="#757575", linestyle="--", linewidth=1.0, label="VLD = 0 dB")
        ax.set_ylabel("振动水平差 VLD (dB)  式 (3.6)")

    if paper_hz:
        for j, pf in enumerate(paper_hz[:3]):
            ax.axvline(
                pf,
                color="#9E9E9E",
                linestyle=":",
                linewidth=0.9,
                alpha=0.55,
                label="论文 fn 参考" if j == 0 else None,
            )
    elif paper_bcc:
        for j, pf in enumerate(PAPER_BCC_HZ[:3]):
            ax.axvline(
                pf,
                color="#9E9E9E",
                linestyle=":",
                linewidth=0.9,
                alpha=0.55,
                label="论文 fn 参考" if j == 0 else None,
            )

    ax.set_xlabel("频率 (Hz)")
    ax.set_title(title)
    ax.grid(True, which="both" if plot == "trans" else "major", alpha=0.3)
    ax.legend(loc="best", fontsize=9)
    fig.tight_layout()
    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png, dpi=180, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return out_png


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Overlay COMSOL VLD/T curves for payload sweep.")
    parser.add_argument(
        "--case",
        action="append",
        nargs=2,
        metavar=("LABEL", "CSV"),
        help='Series label and transmissibility CSV, e.g. --case "300 g" path/to.csv',
    )
    parser.add_argument(
        "--bcc-f5-150",
        action="store_true",
        help="Use default BCC P1 f5-150 slugs for 0/100/300/500 g",
    )
    parser.add_argument(
        "--preset",
        default="",
        help="Payload sweep preset: f5-150 (requires --variant)",
    )
    parser.add_argument(
        "--variant",
        default="bcc",
        choices=sorted(PAYLOAD_PRESETS),
        help="Lattice variant for --preset f5-150",
    )
    parser.add_argument("--out-dir", default="output/comsol_jobs/bcc_payload_composite")
    parser.add_argument("--slug", default="bcc_p1_f5_150_payload_overlay")
    parser.add_argument("--title", default="")
    parser.add_argument("--paper-bcc", action="store_true")
    parser.add_argument("--with-trans", action="store_true", help="Also write transmissibility overlay")
    args = parser.parse_args(argv)

    cases: list[tuple[str, Path]] = []
    paper_hz: Sequence[float] | None = None
    default_title = ""
    if args.bcc_f5_150:
        args.variant = "bcc"
        args.preset = "f5-150"
    if args.preset == "f5-150":
        preset = PAYLOAD_PRESETS[args.variant]
        default_title = str(preset["title"])
        paper_hz = list(preset["paper_hz"])  # type: ignore[arg-type]
        root = ROOT / "output/comsol_jobs"
        for label, slug in payload_f5_150_cases(args.variant):
            csv_path = root / slug / f"{slug}_transmissibility.csv"
            cases.append((label, csv_path))
    elif args.case:
        for label, csv in args.case:
            cases.append((label, Path(csv).resolve()))
    else:
        parser.error("Provide --preset f5-150, --bcc-f5-150, or one/more --case LABEL CSV")

    series: list[tuple[str, list[dict]]] = []
    missing: list[str] = []
    for label, csv_path in cases:
        if not csv_path.is_file():
            missing.append(f"{label}: {csv_path}")
            continue
        series.append((label, _read_rows(csv_path)))

    if missing:
        print("Missing CSVs:", file=sys.stderr)
        for m in missing:
            print(f"  {m}", file=sys.stderr)
        if not series:
            return 1

    out_dir = Path(args.out_dir).resolve()
    title = args.title or default_title or "P1  5–150 Hz  不同顶载 VLD 叠图"
    if args.paper_bcc and paper_hz is None:
        paper_hz = PAPER_BCC_HZ
    vld_png = out_dir / f"{args.slug}_vld.png"
    plot_payload_overlay(
        series, vld_png, title=title, plot="vld", paper_bcc=args.paper_bcc, paper_hz=paper_hz
    )
    print(f"Saved: {vld_png}")

    outputs = {"vld_png": str(vld_png)}
    if args.with_trans:
        trans_png = out_dir / f"{args.slug}_transmissibility.png"
        plot_payload_overlay(
            series,
            trans_png,
            title=title.replace("VLD", "传递率 T"),
            plot="trans",
            paper_bcc=args.paper_bcc,
            paper_hz=paper_hz,
        )
        outputs["transmissibility_png"] = str(trans_png)
        print(f"Saved: {trans_png}")

    meta = {
        "slug": args.slug,
        "series": [{"label": label, "csv": str(csv)} for label, csv in cases if Path(csv).is_file()],
        "missing": missing,
        "outputs": outputs,
    }
    meta_path = out_dir / f"{args.slug}_summary.json"
    meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Summary: {meta_path}")
    return 0 if not missing else 2


if __name__ == "__main__":
    raise SystemExit(main())
