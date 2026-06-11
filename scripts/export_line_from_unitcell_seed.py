"""
Fuse a line of unit cells from a verified fused unit-cell STEP.

Stepwise QA: start with --count 2, then 4, before 4×4 z-slab.

  py -3 scripts/export_pair_fuse_check.py --Q 1.0
  py -3 scripts/export_line_from_unitcell_seed.py --Q 1.0 --axis y --count 2
  py -3 scripts/export_line_from_unitcell_seed.py --Q 1.0 --axis y --count 4 --compound

Q=1.0: always pass --compound; seed fuse opens as surface bodies in SolidWorks.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from src.export.export_sw import (
    _lattice_cell_offset_xyz_mm,
    export_unitcell_array_from_seed,
)
from src.generator.hu_bai_bcc import HuBaiLatticeGenerator
from src.paths import CAD_ROOT, ensure_output_dirs

ensure_output_dirs()

_parser = argparse.ArgumentParser(description="Line of N cells from unit-cell seed")
_parser.add_argument("--Q", type=float, default=1.0)
_parser.add_argument("--seed", default="")
_parser.add_argument("--count", type=int, default=4)
_parser.add_argument("--axis", choices=("x", "y", "z"), default="y")
_parser.add_argument("--block", type=int, default=4)
_parser.add_argument("--out-dir", default="")
_parser.add_argument("--compound", action="store_true")
_parser.add_argument(
    "--fuse",
    choices=("sequential", "tree", "pairs"),
    default="sequential",
)
_args = _parser.parse_args()

L = 20.0
n = int(_args.count)
block = int(_args.block)
axis = str(_args.axis)

gen = HuBaiLatticeGenerator(
    cell_size=L,
    rod_diameter=2.0,
    amplitude=2.0,
    period_factor=float(_args.Q),
    n_segments=24,
)
gen.build_unitcell()

q_tag = str(_args.Q).replace(".", "p")
out_dir = _args.out_dir.strip() or os.path.join(str(CAD_ROOT), f"_stepwise_q{q_tag}")
os.makedirs(out_dir, exist_ok=True)

seed_step = _args.seed.strip() or os.path.join(
    str(CAD_ROOT),
    "_unitcell_check",
    f"unitcell_{gen.variant_name.lower()}_fused.step",
)
seed_step = os.path.abspath(seed_step)
if not os.path.isfile(seed_step):
    raise SystemExit(f"[FAIL] Seed not found: {seed_step}")

axis_label = {"x": "row_x", "y": "col_y", "z": "stack_z"}[axis]
suffix = "compound" if _args.compound else "fused"
step_path = os.path.join(out_dir, f"line_{axis_label}_{n}cell_iz0_{suffix}_from_seed.step")
manifest_path = os.path.join(out_dir, f"line_{axis_label}_{n}cell_iz0_{suffix}_manifest.json")

offsets: list[tuple[float, float, float]] = []
for i in range(n):
    ix = i if axis == "x" else 0
    iy = i if axis == "y" else 0
    iz_i = i if axis == "z" else 0
    offsets.append(
        _lattice_cell_offset_xyz_mm(
            ix,
            iy,
            iz_i,
            nx=block if axis == "x" else 1,
            ny=block if axis == "y" else 1,
            nz=block if axis == "z" else 1,
            cell_size=L,
        )
    )

print(
    f"Line from seed: {gen.variant_name} {n} cell(s) axis={axis} "
    f"{'compound' if _args.compound else _args.fuse}",
    flush=True,
)
print(f"  Seed: {seed_step}", flush=True)
print(f"  Out:  {step_path}", flush=True)

report = export_unitcell_array_from_seed(
    seed_step,
    step_path,
    offsets,
    fuse=not _args.compound,
    fuse_strategy=_args.fuse,
    compound_max_flatten=64,
)

bbox = report.get("bbox_mm") or {}
span = {
    "x": float(bbox["x"][1]) - float(bbox["x"][0]),
    "y": float(bbox["y"][1]) - float(bbox["y"][0]),
    "z": float(bbox["z"][1]) - float(bbox["z"][0]),
}
primary_span = span[axis]
expected = n * L
if primary_span < expected * 0.85:
    print(
        f"  [WARN] {axis}-span {primary_span:.1f} mm < expected ~{expected:.1f} mm",
        flush=True,
    )

manifest = {
    "structure": gen.variant_name,
    "seed_step": seed_step,
    "step_path": os.path.abspath(step_path),
    "axis": axis,
    "cell_count": n,
    "fuse_strategy": "compound" if _args.compound else _args.fuse,
    "method": report.get("method"),
    "span_mm": span,
    "solid_count": report.get("solid_count"),
    "product_count": report.get("product_count"),
    "step_solidworks_safe": report.get("solidworks_safe"),
}
with open(manifest_path, "w", encoding="utf-8") as fh:
    json.dump(manifest, fh, indent=2, ensure_ascii=False)
    fh.write("\n")

print(
    f"  OK: span=({span['x']:.1f}, {span['y']:.1f}, {span['z']:.1f}) mm "
    f"solids={report.get('solid_count')} sw_safe={report.get('solidworks_safe')}",
    flush=True,
)
print(f"  Manifest: {manifest_path}", flush=True)

if _args.compound:
    if int(report.get("solid_count") or 0) != n:
        raise SystemExit(f"[FAIL] Expected {n} bodies, got {report.get('solid_count')}.")
elif int(report.get("solid_count") or 0) != 1:
    raise SystemExit("[FAIL] Expected 1 fused solid.")
