"""
Redo z-slab copies (iz=1..3) and array merge after start_iz copy bug fix.
Keeps fused iz=0; removes bad copies + array STEP, then re-copy and merge.

  py -3 scripts/redo_paper_box_layer_copies.py --Q 1.5
  py -3 scripts/redo_paper_box_layer_copies.py --Q 1.0
"""

from __future__ import annotations

import argparse
import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from src.export.paper_box_array_fuse import (
    export_paper_box_array_from_zslabs,
    export_paper_box_zslab_copies,
    paper_box_seed_step,
)
from src.generator.hu_bai_bcc import HuBaiLatticeGenerator
from src.paths import CAD_ROOT, ensure_output_dirs

ensure_output_dirs()

_parser = argparse.ArgumentParser(description="Redo layer copies + merge (dz fix)")
_parser.add_argument("--Q", type=float, required=True)
_parser.add_argument("--cells", type=int, default=4)
_parser.add_argument("--L", type=float, default=20.0)
_parser.add_argument("--out-dir", default="")
_args = _parser.parse_args()

q = float(_args.Q)
n = int(_args.cells)
L = float(_args.L)
q_tag = str(q).replace(".", "p")

gen = HuBaiLatticeGenerator(
    cell_size=L, rod_diameter=2.0, amplitude=2.0, period_factor=q, n_segments=24,
)
gen.build_unitcell()
variant = gen.variant_name.lower()

out_dir = _args.out_dir.strip() or os.path.join(
    str(CAD_ROOT), f"_paper_box_array_q{q_tag}"
)
os.makedirs(out_dir, exist_ok=True)

ref = os.path.join(out_dir, f"zslab_iz0_{n}x{n}_paper_box_fused.step")
if not os.path.isfile(ref):
    raise SystemExit(f"[FAIL] Missing fused iz=0: {ref}")

zslab_paths = [
    os.path.join(out_dir, f"zslab_iz{iz}_{n}x{n}_paper_box_fused.step")
    for iz in range(n)
]
slug = f"hu_bai_{variant}_L{int(L)}_{n}x{n}x{n}"
array_step = os.path.join(out_dir, f"{slug}_paper_box_array.step")
manifest_path = os.path.join(out_dir, f"{slug}_paper_box_layered_manifest.json")

print(f"=== Redo copies iz=1..{n - 1} (start_iz fix) ===", flush=True)
print(f"  Ref: {ref}", flush=True)

for iz in range(1, n):
    path = zslab_paths[iz]
    if os.path.isfile(path):
        os.remove(path)
    export_paper_box_zslab_copies(ref, [path], cell_size=L, start_iz=iz)

if os.path.isfile(array_step):
    os.remove(array_step)

print(f"\n=== Re-merge {n} z-slabs ===", flush=True)
merge_report = export_paper_box_array_from_zslabs(
    zslab_paths,
    array_step,
    progress_label="paper-box-inter-slab",
)

manifest = {
    "Q": q,
    "variant": gen.variant_name,
    "seed_step": paper_box_seed_step(q),
    "out_dir": os.path.abspath(out_dir),
    "cells": [n, n, n],
    "method": "paper_box_layered_fuse_redo_copies",
    "array_merge": merge_report,
}
with open(manifest_path, "w", encoding="utf-8") as fh:
    json.dump(manifest, fh, indent=2, ensure_ascii=False)
    fh.write("\n")

print(
    f"  OK: vol={merge_report.get('fused_volume_count')} "
    f"sw_safe={merge_report.get('step_solidworks_safe')}",
    flush=True,
)
print(f"  STEP: {array_step}", flush=True)

if int(merge_report.get("fused_volume_count") or 0) != 1:
    raise SystemExit("[FAIL] Expected 1 solid.")
