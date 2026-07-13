#!/usr/bin/env python3
"""CLI: embed default harmonic-resonance plot groups in solved .mph."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.comsol.harmonic_plot_embed import (
    DEFAULT_HARMONIC_PLOT,
    HarmonicPlotDefaults,
    embed_harmonic_plot_groups,
    embed_harmonic_plot_groups_from_csv,
    load_settings_from_mph,
    peak_freqs_from_csv,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Embed harmonic resonance plot groups in solved .mph (GUI view)."
    )
    parser.add_argument("mph", help="Solved .mph path")
    parser.add_argument("--freq", type=float, nargs="*", default=None, help="Target Hz")
    parser.add_argument("--from-csv", action="store_true", help="Use T(f) resonance peaks")
    parser.add_argument("--n-peaks", type=int, default=DEFAULT_HARMONIC_PLOT.n_peaks)
    parser.add_argument("--comsol-bin", default="")
    parser.add_argument(
        "--color-max-mm",
        type=float,
        default=0.0,
        help="Manual color max [mm]; 0 = auto",
    )
    parser.add_argument(
        "--skip-if-current",
        action="store_true",
        help="Skip when {slug}_harmonic_plotgroups.json matches current format",
    )
    args = parser.parse_args(argv)

    mph_path = Path(args.mph).resolve()
    settings = load_settings_from_mph(mph_path)
    defaults = HarmonicPlotDefaults(
        n_peaks=args.n_peaks,
        color_max_mm=None if args.color_max_mm <= 0 else float(args.color_max_mm),
    )

    if args.from_csv and not args.freq:
        meta = embed_harmonic_plot_groups_from_csv(
            mph_path,
            settings,
            comsol_bin=args.comsol_bin or None,
            defaults=defaults,
            skip_if_current=args.skip_if_current,
        )
        if meta is None:
            print("Harmonic plot groups already current")
            return 0
        print(f"Embedded {len(meta['plot_groups'])} plot groups in {mph_path.name}")
        return 0

    freq_hz: list[float] = list(args.freq or [])
    if not freq_hz:
        slug = settings.default_slug()
        csv_path = settings.job_dir() / f"{slug}_transmissibility.csv"
        if not csv_path.is_file():
            print(f"ERROR: missing {csv_path} (run extract first)", file=sys.stderr)
            return 1
        freq_hz = peak_freqs_from_csv(csv_path, n=defaults.n_peaks)
        print(f"  Resonance peaks from CSV: {freq_hz}", flush=True)

    if not freq_hz:
        print("ERROR: no frequencies", file=sys.stderr)
        return 1

    meta = embed_harmonic_plot_groups(
        mph_path,
        settings,
        freq_hz=freq_hz,
        comsol_bin=args.comsol_bin or None,
        defaults=defaults,
    )
    print(f"Embedded {len(meta['plot_groups'])} plot groups in {mph_path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
