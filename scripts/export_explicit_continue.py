#!/usr/bin/env python3
"""Export Abaqus/Explicit restart continuation INP from a completed source job."""

from __future__ import annotations

import argparse
import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from src.export.explicit_continue import (
    EXPLICIT_RESTART_FILE_EXTENSIONS,
    compute_continue_segment,
    default_continue_slug,
    link_restart_files,
    required_restart_files,
    write_continue_meta,
    write_explicit_continue_inp,
)
from src.paths import ABAQUS_JOBS, ABAQUS_POST, EXPORT_ROOT


def _meta_path(slug: str) -> str:
    return os.path.join(EXPORT_ROOT, slug, f"{slug}_meta.json")


def main() -> int:
    parser = argparse.ArgumentParser(description="Export Explicit restart continuation INP")
    parser.add_argument("--from-slug", required=True, help="Completed source job slug")
    parser.add_argument("--to-slug", default="", help="Continuation job slug (default: auto)")
    parser.add_argument("--to-strain", type=float, required=True, help="Target total engineering strain")
    parser.add_argument("--load-rate-mm-min", type=float, default=None)
    parser.add_argument("--hold-fraction", type=float, default=None)
    parser.add_argument("--restart-interval", type=int, default=None)
    parser.add_argument("--copy-restart-files", action="store_true", help="Copy .res/.stt/.odb into target job dir")
    args = parser.parse_args()

    source_slug = args.from_slug.strip()
    target_slug = args.to_slug.strip() or default_continue_slug(source_slug, args.to_strain)
    source_meta_path = _meta_path(source_slug)
    if not os.path.isfile(source_meta_path):
        print(f"[ERROR] missing meta: {source_meta_path}")
        return 1
    with open(source_meta_path, encoding="utf-8") as f:
        source_meta = json.load(f)

    source_job_dir = os.path.join(ABAQUS_JOBS, source_slug)
    missing = required_restart_files(source_job_dir, source_slug)
    if missing:
        print(f"[ERROR] source job missing restart files in {source_job_dir}: {', '.join(missing)}")
        return 1

    segment = compute_continue_segment(
        source_slug=source_slug,
        target_slug=target_slug,
        source_meta=source_meta,
        target_strain=args.to_strain,
        load_rate_mm_min=args.load_rate_mm_min,
        hold_fraction=args.hold_fraction,
        restart_number_interval=args.restart_interval,
    )

    export_dir = os.path.join(EXPORT_ROOT, target_slug)
    job_dir = os.path.join(ABAQUS_JOBS, target_slug)
    post_dir = os.path.join(ABAQUS_POST, target_slug)
    for d in (export_dir, job_dir, post_dir):
        os.makedirs(d, exist_ok=True)

    continue_inp = os.path.join(export_dir, f"{target_slug}.inp")
    write_explicit_continue_inp(continue_inp, segment=segment, source_meta=source_meta)
    meta_out = os.path.join(export_dir, f"{target_slug}_meta.json")
    write_continue_meta(
        meta_out,
        segment=segment,
        source_meta=source_meta,
        continue_inp=continue_inp,
    )

    if args.copy_restart_files:
        linked = link_restart_files(source_job_dir, job_dir, source_slug)
        print(f"linked restart files ({len(linked)}): {', '.join(linked)}")

    print(f"Wrote continuation INP: {continue_inp}")
    print(
        f"  {segment.source_strain:.1%} -> {segment.target_strain:.1%} "
        f"(+{segment.delta_strain:.1%}, disp {segment.additional_displacement_mm:.1f} mm, "
        f"step {segment.step_time_s:.1f} s)"
    )
    print(f"Submit: bash scripts/linux/submit_job.sh --slug {target_slug} --restart-from {source_slug} --background")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
