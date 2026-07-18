"""
In-memory hierarchical z-slab fuse (Q1.0 stepwise QA).

STEP seed copy+fuse fails for pipe-first geometry; this path rebuilds the
unit cell in gmsh, uses array-safe intra-cell fuse, then row/block inter-cell fuse.

  py -3 scripts/export_fused_inmem_stepwise.py --Q 1.0 --nx 1 --ny 4
  py -3 scripts/export_fused_inmem_stepwise.py --Q 1.0 --nx 4 --ny 4
"""

from __future__ import annotations

import argparse
import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from src.export.beam_utils import dedupe_beams
from src.export.export_sw import export_lattice_step_occ_zslab
from src.export.sw_parasolid import analyze_step_for_solidworks
from src.generator.hu_bai_bcc import HuBaiLatticeGenerator
from src.paths import CAD_ROOT, ensure_output_dirs

ensure_output_dirs()

_parser = argparse.ArgumentParser(description="In-memory fused z-slab / line (stepwise)")
_parser.add_argument("--Q", type=float, default=1.0)
_parser.add_argument("--nx", type=int, default=4)
_parser.add_argument("--ny", type=int, default=4)
_parser.add_argument("--iz", type=int, default=0)
_parser.add_argument("--block", type=int, default=4)
_parser.add_argument("--out-dir", default="")
_args = _parser.parse_args()

L = 20.0
nx, ny = int(_args.nx), int(_args.ny)
iz = int(_args.iz)
block = int(_args.block)

gen = HuBaiLatticeGenerator(
    cell_size=L,
    rod_diameter=2.0,
    amplitude=2.0,
    period_factor=float(_args.Q),
    n_segments=24,
)
gen.build_unitcell()
nodes, beams, polylines = gen.get_data(copy=True)
beams, dups = dedupe_beams(beams)
if dups:
    print(f"  Deduped beams: {dups}", flush=True)

q_tag = str(_args.Q).replace(".", "p")
out_dir = _args.out_dir.strip() or os.path.join(str(CAD_ROOT), f"_stepwise_q{q_tag}")
os.makedirs(out_dir, exist_ok=True)

if nx == 1 and ny > 1:
    slug = f"line_col_y_{ny}cell_iz{iz}_fused_inmem"
elif ny == 1 and nx > 1:
    slug = f"line_row_x_{nx}cell_iz{iz}_fused_inmem"
else:
    slug = f"zslab_iz{iz}_{nx}x{ny}_fused_inmem"

step_path = os.path.join(out_dir, f"{slug}.step")
manifest_path = os.path.join(out_dir, f"{slug}_manifest.json")

print(f"In-memory fuse: {gen.variant_name} {nx}x{ny} iz={iz} -> {step_path}", flush=True)

stats = export_lattice_step_occ_zslab(
    nodes,
    beams,
    step_path,
    nx=nx,
    ny=ny,
    iz=iz,
    block_nx=block,
    block_ny=block,
    block_nz=block,
    cell_size=L,
    polylines=polylines,
    junction_spheres=False,
)

report = analyze_step_for_solidworks(step_path, fused_single=True)
bbox = stats.get("bbox_mm") or {}
span = {
    "x": float(bbox["x"][1]) - float(bbox["x"][0]),
    "y": float(bbox["y"][1]) - float(bbox["y"][0]),
    "z": float(bbox["z"][1]) - float(bbox["z"][0]),
}
exp_x, exp_y = nx * L, ny * L
if span["x"] < exp_x * 0.8 or span["y"] < exp_y * 0.8:
    raise SystemExit(
        f"[FAIL] Bbox span too small: ({span['x']:.1f}, {span['y']:.1f}) mm "
        f"(expected ~{exp_x:.0f} x {exp_y:.0f})."
    )

manifest = {
    "structure": gen.variant_name,
    "step_path": os.path.abspath(step_path),
    "nx": nx,
    "ny": ny,
    "iz": iz,
    "method": stats.get("method"),
    "span_mm": span,
    "fused_volume_count": report.get("solid_count"),
    "step_solidworks_safe": report.get("solidworks_safe"),
    "note": "in-memory gmsh_occ_zslab_fuse; not STEP-seed boolean",
}
with open(manifest_path, "w", encoding="utf-8") as fh:
    json.dump(manifest, fh, indent=2, ensure_ascii=False)
    fh.write("\n")

print(
    f"  OK: span=({span['x']:.1f}, {span['y']:.1f}, {span['z']:.1f}) mm "
    f"vol={report.get('solid_count')} sw_safe={report.get('solidworks_safe')}",
    flush=True,
)
print(f"  Manifest: {manifest_path}", flush=True)

if int(report.get("solid_count") or 0) != 1:
    raise SystemExit("[FAIL] Expected 1 fused MANIFOLD_SOLID_BREP.")
