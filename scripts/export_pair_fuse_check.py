"""
Stepwise QA: 2-cell compound along Y and X before larger arrays.

  py -3 scripts/export_pair_fuse_check.py --Q 1.0

Q=1.0: use compound only — STEP-seed boolean fuse opens as surface bodies in SW.
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

_parser = argparse.ArgumentParser(description="2-cell fuse QA (Y + X)")
_parser.add_argument("--Q", type=float, default=1.0)
_parser.add_argument("--seed", default="")
_parser.add_argument("--out-dir", default="")
_args = _parser.parse_args()

L = 20.0
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
    "_unitcell_paper_box_cut",
    f"unitcell_{gen.variant_name.lower()}_paper_box.step",
)
seed_step = os.path.abspath(seed_step)
if not os.path.isfile(seed_step):
    raise SystemExit(
        f"[FAIL] Seed not found: {seed_step}\n"
        "Generate with: py -3 scripts/export_unitcell_paper_box_cut.py "
        f"--Q {_args.Q}"
    )

cases = [
    ("col_y_2cell_compound", "y", False, "sequential"),
    ("row_x_2cell_compound", "x", False, "sequential"),
]

manifest_entries: list[dict] = []
print(f"Pair fuse QA: {gen.variant_name}", flush=True)
print(f"  Seed (paper_box): {seed_step}", flush=True)
print(
    "  If struts look wrong, re-run: "
    f"py -3 scripts/export_unitcell_paper_box_cut.py --Q {_args.Q}",
    flush=True,
)

for slug, axis, do_fuse, strategy in cases:
    offsets: list[tuple[float, float, float]] = []
    for i in range(2):
        ix = i if axis == "x" else 0
        iy = i if axis == "y" else 0
        iz_i = i if axis == "z" else 0
        offsets.append(
            _lattice_cell_offset_xyz_mm(
                ix,
                iy,
                iz_i,
                nx=4 if axis == "x" else 1,
                ny=4 if axis == "y" else 1,
                nz=4 if axis == "z" else 1,
                cell_size=L,
            )
        )
    step_path = os.path.join(out_dir, f"pair_{slug}_from_seed.step")
    print(f"  {slug} -> {step_path}", flush=True)
    report = export_unitcell_array_from_seed(
        seed_step,
        step_path,
        offsets,
        fuse=do_fuse,
        fuse_strategy=strategy,
    )
    bbox = report.get("bbox_mm") or {}
    span = {
        "x": float(bbox["x"][1]) - float(bbox["x"][0]),
        "y": float(bbox["y"][1]) - float(bbox["y"][0]),
        "z": float(bbox["z"][1]) - float(bbox["z"][0]),
    }
    entry = {
        "slug": slug,
        "axis": axis,
        "fused": do_fuse,
        "step_path": step_path,
        "method": report.get("method"),
        "solid_count": report.get("solid_count"),
        "product_count": report.get("product_count"),
        "sw_safe": report.get("solidworks_safe"),
        "span_mm": span,
    }
    manifest_entries.append(entry)
    print(
        f"    OK: solids={entry['solid_count']} products={entry['product_count']} "
        f"span=({span['x']:.1f}, {span['y']:.1f}, {span['z']:.1f}) mm",
        flush=True,
    )

manifest_path = os.path.join(out_dir, "pair_fuse_check_manifest.json")
with open(manifest_path, "w", encoding="utf-8") as fh:
    json.dump(
        {
            "structure": gen.variant_name,
            "seed_step": seed_step,
            "cases": manifest_entries,
            "next_steps": [
                "SW: verify pair_col_y_2cell_compound + pair_row_x_2cell_compound",
                "Then: export_line --count 4 --compound, then z-slab 4x4 --compound",
            ],
        },
        fh,
        indent=2,
        ensure_ascii=False,
    )
    fh.write("\n")

print(f"\nManifest: {manifest_path}", flush=True)
print("Open pair_* STEPs in SolidWorks before running 4-cell or 4x4 exports.", flush=True)
