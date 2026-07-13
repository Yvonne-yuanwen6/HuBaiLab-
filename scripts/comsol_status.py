#!/usr/bin/env python3
"""Print COMSOL batch log tail for a job slug."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.comsol.runner import job_dir_for_slug, tail_batch_log


def main() -> int:
    parser = argparse.ArgumentParser(description="Tail COMSOL batch log.")
    parser.add_argument("--slug", required=True)
    parser.add_argument("--lines", type=int, default=40)
    args = parser.parse_args()

    job_dir = job_dir_for_slug(args.slug)
    print(f"Job dir: {job_dir}")
    print(tail_batch_log(args.slug, lines=args.lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
