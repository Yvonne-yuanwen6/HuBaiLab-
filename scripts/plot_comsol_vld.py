#!/usr/bin/env python3
"""Plot VLD (vibration level difference) vs frequency from COMSOL freq CSV."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.comsol.plot_isolation import export_isolation_plots, pick_vld_peaks, rows_to_series

PAPER_TABLE33_BCC_HZ = [14.8, 49.8, 68.4]


def _read_rows(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Plot VLD / transmissibility PNGs from COMSOL CSV.")
    parser.add_argument(
        "csv",
        nargs="?",
        default="",
        help="transmissibility or vld CSV path",
    )
    parser.add_argument("--out", default="", help="Output VLD PNG (other plots use job dir naming)")
    parser.add_argument("--title", default="")
    parser.add_argument("--slug", default="")
    parser.add_argument("--paper-bcc", action="store_true", help="Overlay Table 3.3 BCC paper fn lines")
    parser.add_argument("--with-transmissibility", action="store_true", help="Also write T / combo PNGs")
    parser.add_argument("--combo-only", action="store_true", help="Only write combo PNG (requires --with-transmissibility)")
    args = parser.parse_args(argv)

    if args.csv:
        csv_path = Path(args.csv).resolve()
    else:
        csv_path = ROOT / "output/comsol_jobs/comsol_fig321_bcc_444_freq/comsol_fig321_bcc_444_freq_transmissibility.csv"

    if not csv_path.is_file():
        alt = csv_path.with_name(csv_path.name.replace("_transmissibility", "_vld"))
        if alt.is_file():
            csv_path = alt
        else:
            raise SystemExit(f"Not found: {csv_path}")

    rows = _read_rows(csv_path)
    if not rows:
        raise SystemExit(f"Empty CSV: {csv_path}")

    job_dir = csv_path.parent
    slug = args.slug or job_dir.name
    title = args.title
    if not title:
        manifest = job_dir / "case_manifest.json"
        if manifest.is_file():
            data = json.loads(manifest.read_text(encoding="utf-8"))
            variant = data.get("geometry", {}).get("variant", "")
            title = f"{slug}  {variant}  隔振频响"

    paper = PAPER_TABLE33_BCC_HZ if args.paper_bcc or "bcc" in slug else None

    if args.combo_only:
        from src.comsol.plot_isolation import plot_isolation_combo

        out = Path(args.out) if args.out else job_dir / f"{slug}_isolation_combo.png"
        plot_isolation_combo(rows, out, title=title, paper_freqs=paper)
        print(f"Saved: {out}")
        return 0

    outputs = export_isolation_plots(
        rows, job_dir, slug, title=title, paper_freqs=paper, vld_only=not args.with_transmissibility
    )
    if args.out:
        from shutil import copy2

        copy2(outputs["vld_png"], Path(args.out))

    freqs, _, vld = rows_to_series(rows)
    peaks = pick_vld_peaks(freqs, vld)
    print(f"Saved: {outputs['vld_png']}")
    print(f"Saved: {outputs['fig322_png']}")
    if args.with_transmissibility:
        print(f"Saved: {outputs.get('transmissibility_png', '')}")
        print(f"Saved: {outputs.get('combo_png', '')}")
    if peaks:
        print("Top VLD resonance peaks (Hz):", ", ".join(f"{p['freq_hz']:.2f}" for p in peaks[:3]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
