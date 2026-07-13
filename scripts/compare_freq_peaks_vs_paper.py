#!/usr/bin/env python3
"""Pick resonance peaks from transmissibility CSV and compare to Table 3.3."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.comsol.table33_compare import compare_batch_case, print_compare_table, write_compare_csv
from src.paths import COMSOL_JOBS_ROOT


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compare transmissibility peaks vs Table 3.3.")
    parser.add_argument("--jobs-root", default=str(COMSOL_JOBS_ROOT))
    parser.add_argument("--key", default="bcc")
    parser.add_argument("--min-hz", type=float, default=1.0)
    parser.add_argument("--min-sep-hz", type=float, default=8.0)
    parser.add_argument(
        "--out-json",
        default=str(COMSOL_JOBS_ROOT / "fig321_composite" / "fig321_freq_peaks_vs_paper.json"),
    )
    args = parser.parse_args(argv)

    jobs_root = Path(args.jobs_root)
    result = compare_batch_case(
        args.key, jobs_root, min_hz=args.min_hz, min_sep_hz=args.min_sep_hz
    )
    if not result.get("harmonic", {}).get("modes"):
        print(f"No transmissibility CSV for key={args.key}", file=sys.stderr)
        return 1

    print_compare_table(result)
    out = Path(args.out_json)
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {"cases": [result]}
    if out.is_file():
        try:
            existing = json.loads(out.read_text(encoding="utf-8"))
            cases = {c["case_key"]: c for c in existing.get("cases", [])}
            cases[result["case_key"]] = result
            payload = {"cases": list(cases.values())}
        except Exception:
            pass
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"\nSaved: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
