#!/usr/bin/env python3
"""Compare eigen fn vs harmonic-resonance peaks against thesis Table 3.3."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.comsol.table33_compare import (
    compare_batch_case,
    compare_from_job_dir,
    print_compare_table,
    write_compare_csv,
    write_compare_csv_batch,
)
from src.comsol.table33_reference import EIGEN_SLUGS
from src.paths import COMSOL_JOBS_ROOT


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Compare COMSOL eigen vs transmissibility peaks vs Table 3.3."
    )
    parser.add_argument(
        "job_dir",
        nargs="?",
        default="",
        help="Single job dir (output/comsol_jobs/{slug}/). Omit for batch Fig.3.21 cases.",
    )
    parser.add_argument("--slug", default="")
    parser.add_argument("--key", default="", help="Table 3.3 case key (bcc, af2q05, …)")
    parser.add_argument("--jobs-root", default=str(COMSOL_JOBS_ROOT))
    parser.add_argument("--min-hz", type=float, default=1.0)
    parser.add_argument("--min-sep-hz", type=float, default=8.0)
    parser.add_argument("--out-json", default="", help="JSON output path")
    parser.add_argument("--out-csv", default="", help="CSV output path")
    parser.add_argument(
        "--batch",
        action="store_true",
        help="Run all Fig.3.21 keys with separate eigen + freq job dirs",
    )
    args = parser.parse_args(argv)

    jobs_root = Path(args.jobs_root)

    if args.job_dir:
        job_dir = Path(args.job_dir).resolve()
        result = compare_from_job_dir(
            job_dir,
            slug=args.slug,
            case_key=args.key or None,
            min_hz=args.min_hz,
            min_sep_hz=args.min_sep_hz,
        )
        results = [result]
        default_json = job_dir / f"{result['slug']}_table33_compare.json"
        default_csv = job_dir / f"{result['slug']}_table33_compare.csv"
    elif args.batch or not args.key:
        keys = tuple(EIGEN_SLUGS.keys())
        results = [
            compare_batch_case(k, jobs_root, min_hz=args.min_hz, min_sep_hz=args.min_sep_hz)
            for k in keys
        ]
        composite = jobs_root / "fig321_composite"
        default_json = composite / "table33_eigen_vs_harmonic_vs_paper.json"
        default_csv = composite / "table33_eigen_vs_harmonic_vs_paper.csv"
    else:
        result = compare_batch_case(
            args.key, jobs_root, min_hz=args.min_hz, min_sep_hz=args.min_sep_hz
        )
        results = [result]
        default_json = jobs_root / "fig321_composite" / f"table33_{args.key}_compare.json"
        default_csv = jobs_root / "fig321_composite" / f"table33_{args.key}_compare.csv"

    for result in results:
        print_compare_table(result)

    out_json = Path(args.out_json) if args.out_json else default_json
    out_csv = Path(args.out_csv) if args.out_csv else default_csv
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(
        json.dumps({"cases": results}, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    if len(results) == 1:
        write_compare_csv(results[0], out_csv)
    else:
        write_compare_csv_batch(results, out_csv)

    print(f"\nSaved: {out_json}")
    print(f"Saved: {out_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
