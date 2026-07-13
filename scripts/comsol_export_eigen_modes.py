#!/usr/bin/env python3
"""Export first N physical eigenmode shape PNGs from a solved COMSOL .mph."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.comsol.hu_bai_settings import HuBaiComsolSettings
from src.comsol.mph_builder import export_eigenmode_plots


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export eigenmode PNGs from solved COMSOL .mph.")
    parser.add_argument("mph", help="Solved .mph path")
    parser.add_argument("--modes", type=int, default=3, help="Number of physical modes to export")
    parser.add_argument("--min-hz", type=float, default=1.0, help="Skip modes below this |f|")
    parser.add_argument("--slug", default="")
    parser.add_argument("--comsol-bin", default="")
    parser.add_argument("--no-save-mph", action="store_true", help="Do not embed plot groups in .mph")
    args = parser.parse_args(argv)

    mph_path = Path(args.mph).resolve()
    if not mph_path.is_file():
        raise SystemExit(f"Not found: {mph_path}")

    manifest = mph_path.parent / "case_manifest.json"
    if manifest.is_file():
        data = json.loads(manifest.read_text(encoding="utf-8"))
        sdict = data.get("settings", {})
        settings = HuBaiComsolSettings(
            **{k: v for k, v in sdict.items() if k in HuBaiComsolSettings.__dataclass_fields__}
        )
    else:
        settings = HuBaiComsolSettings(slug=args.slug or mph_path.stem.replace("_solved", ""))

    export_eigenmode_plots(
        mph_path,
        settings,
        n_modes=args.modes,
        min_hz=args.min_hz,
        comsol_bin=args.comsol_bin or None,
        save_mph=not args.no_save_mph,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
