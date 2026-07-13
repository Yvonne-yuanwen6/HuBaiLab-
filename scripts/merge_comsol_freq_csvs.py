#!/usr/bin/env python3
"""Merge COMSOL transmissibility/VLD CSVs from multiple freq sweeps and plot."""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.comsol.plot_isolation import (
    export_isolation_plots,
    pick_resonance_peaks,
    pick_vld_peaks,
    rows_to_series,
)

PAPER_BCC_HZ = [14.8, 49.8, 68.4]


def _read_rows(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _row_freq(row: dict) -> float:
    return float(row["frequency_Hz"])


def merge_rows(sources: list[tuple[Path, list[dict]]]) -> list[dict]:
    """Later sources override earlier at the same frequency (finer sweep listed last)."""
    by_freq: dict[float, dict] = {}
    for _path, rows in sources:
        for row in rows:
            by_freq[_row_freq(row)] = dict(row)
    merged = [by_freq[f] for f in sorted(by_freq)]
    for row in merged:
        f = float(row["frequency_Hz"])
        t_raw = row.get("transmissibility", row.get("T_eq320", ""))
        if t_raw not in ("", None):
            t = float(t_raw)
            if not math.isnan(t) and t > 0.0:
                row.setdefault("transmissibility", str(t))
                row.setdefault("T_eq320", str(t))
                row.setdefault("VLD_dB", str(20.0 * math.log10(t)))
        row.setdefault("extract_method", row.get("extract_method", "merged"))
    return merged


def write_csv(rows: list[dict], path: Path) -> None:
    if not rows:
        raise ValueError("no rows to write")
    fields = list(rows[0].keys())
    for row in rows:
        for k in row:
            if k not in fields:
                fields.append(k)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Merge COMSOL freq CSVs and plot VLD.")
    parser.add_argument("csvs", nargs="+", help="transmissibility or vld CSV paths (later wins on overlap)")
    parser.add_argument("--out-dir", default="", help="Output directory (default: parent of first CSV)")
    parser.add_argument("--slug", default="merged")
    parser.add_argument("--title", default="")
    parser.add_argument("--paper-bcc", action="store_true")
    args = parser.parse_args(argv)

    paths = [Path(p).resolve() for p in args.csvs]
    for p in paths:
        if not p.is_file():
            alt = p.with_name(p.name.replace("_transmissibility", "_vld"))
            if alt.is_file():
                continue
            raise SystemExit(f"Not found: {p}")

    sources: list[tuple[Path, list[dict]]] = []
    for p in paths:
        if not p.is_file():
            p = p.with_name(p.name.replace("_transmissibility", "_vld"))
        sources.append((p, _read_rows(p)))

    merged = merge_rows(sources)
    out_dir = Path(args.out_dir).resolve() if args.out_dir else paths[0].parent
    slug = args.slug
    title = args.title or f"{slug}  BCC P1  隔振频响 (合并扫频)"

    trans_csv = out_dir / f"{slug}_transmissibility.csv"
    vld_csv = out_dir / f"{slug}_vld.csv"
    write_csv(merged, trans_csv)

    freqs, trans, vld = rows_to_series(merged)
    vld_rows = [
        {
            "frequency_Hz": f,
            "VLD_dB": v,
            "transmissibility": t,
            "extract_method": "merged",
        }
        for f, t, v in zip(freqs, trans, vld, strict=False)
    ]
    write_csv(vld_rows, vld_csv)

    paper = PAPER_BCC_HZ if args.paper_bcc else None
    outputs = export_isolation_plots(
        merged, out_dir, slug, title=title, paper_freqs=paper, vld_only=False
    )

    vld_peaks = pick_vld_peaks(freqs, vld)
    t_peaks = pick_resonance_peaks(freqs, trans)
    summary = {
        "slug": slug,
        "sources": [str(p) for p in paths],
        "n_points": len(merged),
        "freq_min_hz": freqs[0] if freqs else None,
        "freq_max_hz": freqs[-1] if freqs else None,
        "vld_peaks": vld_peaks,
        "T_peaks": t_peaks,
        "outputs": {k: str(v) for k, v in outputs.items()},
    }
    summary_path = out_dir / f"{slug}_merge_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"Merged {len(merged)} points from {len(paths)} CSVs")
    print(f"  range: {freqs[0]:.1f}–{freqs[-1]:.1f} Hz")
    print(f"  transmissibility → {trans_csv}")
    print(f"  VLD → {vld_csv}")
    for k, v in outputs.items():
        print(f"  {k} → {v}")
    if vld_peaks:
        print("VLD peaks (Hz):", ", ".join(f"{p['freq_hz']:.1f}" for p in vld_peaks))
    if t_peaks:
        print("T peaks (Hz):", ", ".join(f"{p['freq_hz']:.1f}" for p in t_peaks))
    print(f"Summary → {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
