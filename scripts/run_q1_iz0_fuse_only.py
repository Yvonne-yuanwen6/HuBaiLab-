"""Fuse Q1 iz=0 z-slab only (OCP GlueShift, same row order as layered route)."""
from __future__ import annotations

import argparse
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from src.export.ocp_paper_box_array_fuse import (
    export_ocp_paper_box_zslab_fuse,
    ocp_default_q1_seed_step,
)
from src.paths import CAD_ROOT

_parser = argparse.ArgumentParser(description="Q1 iz=0 OCP z-slab fuse only")
_parser.add_argument("--seed", default="", help="1-volume OCP unit-cell STEP")
_parser.add_argument(
    "--out-dir",
    default=os.path.join(str(CAD_ROOT), "_paper_box_array_q1p0_ocp"),
)
_parser.add_argument("--force", action="store_true")
_args = _parser.parse_args()

seed = os.path.abspath(_args.seed.strip() or ocp_default_q1_seed_step())
if not os.path.isfile(seed):
    raise SystemExit(f"[FAIL] Seed not found: {seed}")

out_dir = os.path.abspath(_args.out_dir)
os.makedirs(out_dir, exist_ok=True)
out = os.path.join(out_dir, "zslab_iz0_4x4_paper_box_fused.step")

if _args.force and os.path.isfile(out):
    os.remove(out)

print("=== Q1 iz=0 OCP fuse ===", flush=True)
print(f"  Seed: {seed}", flush=True)
print(f"  Out:  {out}", flush=True)

rep = export_ocp_paper_box_zslab_fuse(seed, out)
print(
    f"OK vol={rep.get('fused_volume_count')} "
    f"sw_safe={rep.get('step_solidworks_safe')} "
    f"mass={rep.get('merged_mass_mm3'):.0f} mm³",
    flush=True,
)
