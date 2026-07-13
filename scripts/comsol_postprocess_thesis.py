#!/usr/bin/env python3
"""Post-process COMSOL isolation results for thesis Eq.3.20, Table 3.3, Fig.3.22."""

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

from src.comsol.hu_bai_settings import THESIS_BASE_ACCELERATION_M_S2
from src.comsol.plot_isolation import export_isolation_plots
from src.comsol.table33_compare import (
    compare_from_job_dir,
    print_compare_table,
    write_compare_csv,
)
from src.comsol.table33_reference import paper_sim_hz, resolve_case_key


def _read_trans_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def build_summary(trans_rows: list[dict], *, a_in: float) -> dict:
    """VLD / Eq.3.20 metrics: resonance peak (max VLD), isolation band (VLD<0)."""
    peak_vld = float("nan")
    peak_f = float("nan")
    iso_onset = float("nan")
    for row in trans_rows:
        f = float(row["frequency_Hz"])
        vld = float(row.get("VLD_dB", "nan"))
        if math.isnan(vld):
            continue
        if math.isnan(peak_vld) or vld > peak_vld:
            peak_vld, peak_f = vld, f
        if math.isnan(iso_onset) and vld < 0.0:
            iso_onset = f

    return {
        "thesis": "Eq.3.6 VLD / Fig.3.20 / Fig.3.22 summary",
        "vld_formula": "VLD = 20·log10(A_out/A_in)",
        "A_in_nom_m_s2": a_in,
        "peak_VLD_dB": peak_vld,
        "peak_VLD_freq_Hz": peak_f,
        "isolation_onset_Hz_VLD_lt_0": iso_onset,
        "n_freq_points": len(trans_rows),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Thesis Eq.3.20 / Table 3.3 / Fig.3.22 post-process.")
    parser.add_argument("job_dir", help="output/comsol_jobs/{slug}/")
    parser.add_argument("--slug", default="")
    parser.add_argument("--a-in", type=float, default=THESIS_BASE_ACCELERATION_M_S2)
    parser.add_argument("--min-hz", type=float, default=1.0)
    parser.add_argument("--min-sep-hz", type=float, default=8.0)
    parser.add_argument("--no-compare", action="store_true", help="Skip Table 3.3 eigen vs harmonic compare")
    parser.add_argument(
        "--no-harmonic-plots",
        action="store_true",
        help="Skip embedding harmonic plot groups in *_solved.mph",
    )
    parser.add_argument(
        "--force-harmonic-plots",
        action="store_true",
        help="Re-embed harmonic plot groups even if metadata is current",
    )
    args = parser.parse_args(argv)

    job_dir = Path(args.job_dir).resolve()
    manifest = json.loads((job_dir / "case_manifest.json").read_text(encoding="utf-8"))
    slug = args.slug or manifest.get("slug", job_dir.name)
    variant = manifest.get("geometry", {}).get("variant", "")
    case_key = resolve_case_key(slug=slug, variant=str(variant), Q=manifest.get("geometry", {}).get("Q"))

    trans_path = job_dir / f"{slug}_transmissibility.csv"
    trans_rows = _read_trans_csv(trans_path) if trans_path.is_file() else []

    if not trans_rows:
        raise SystemExit(f"Missing transmissibility CSV: {trans_path} (run freq study + extract first)")

    summary = build_summary(trans_rows, a_in=args.a_in)
    summary_path = job_dir / f"{slug}_isolation_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    paper = paper_sim_hz(case_key)
    title = f"{slug}  {variant}  4×4×4  §2.4.3"
    plot_paths = export_isolation_plots(trans_rows, job_dir, slug, title=title, paper_freqs=paper, vld_only=True)
    fig_path = Path(plot_paths["fig322_png"])

    compare_result = None
    if not args.no_compare:
        compare_result = compare_from_job_dir(
            job_dir,
            slug=slug,
            case_key=case_key,
            min_hz=args.min_hz,
            min_sep_hz=args.min_sep_hz,
        )
        compare_json = job_dir / f"{slug}_table33_compare.json"
        compare_csv = job_dir / f"{slug}_table33_compare.csv"
        compare_json.write_text(
            json.dumps(compare_result, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        write_compare_csv(compare_result, compare_csv)
        print_compare_table(compare_result)
        print(f"  Table 3.3 compare → {compare_csv}")

    print(f"  Isolation summary → {summary_path}")
    print(f"  VLD PNG → {plot_paths['vld_png']}")
    print(f"  Fig. 3.20/3.22 → {fig_path}")
    if compare_result:
        harm = compare_result.get("harmonic", {}).get("modes", [])
        if harm:
            print(
                f"  Harmonic fn1 ≈ {harm[0]['freq_hz']:.2f} Hz, "
                f"VLD ≈ {20*math.log10(harm[0]['transmissibility']):.2f} dB"
                if harm[0].get("transmissibility")
                else f"  Harmonic fn1 ≈ {harm[0]['freq_hz']:.2f} Hz"
            )
    else:
        print(f"  VLD_max ≈ {summary['peak_VLD_dB']:.2f} dB @ {summary['peak_VLD_freq_Hz']:.1f} Hz")

    if not args.no_harmonic_plots:
        from src.comsol.harmonic_plot_embed import embed_harmonic_plot_groups_from_csv

        solved = job_dir / f"{slug}_solved.mph"
        if solved.is_file():
            try:
                meta = embed_harmonic_plot_groups_from_csv(
                    solved,
                    skip_if_current=not args.force_harmonic_plots,
                )
                if meta is not None:
                    print(
                        f"  Harmonic plot groups → {slug}_harmonic_plotgroups.json "
                        f"({len(meta['plot_groups'])} peaks)"
                    )
            except Exception as exc:
                print(f"  WARN: harmonic plot embed failed: {exc}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
