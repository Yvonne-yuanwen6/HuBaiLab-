"""
Fuse an nx×ny×nz unit-cell block into one solid STEP (SFBLS/BCC).

Hierarchical in-memory fuse: row → z-slab → inter-slab.

  py -3 scripts/run_hu_bai_bcc_block_step_fuse.py --Q 0.5 --nx 4 --ny 4 --nz 4
  py -3 scripts/validate_step_solidworks.py output/cad/hu_bai_sfbls_af2q0p5_L20_4x4x4_solid_array.step
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
from src.export.export_sw import export_lattice_step_occ_block
from src.export.sw_parasolid import analyze_step_for_solidworks
from src.generator.hu_bai_bcc import HuBaiLatticeGenerator
from src.paths import CAD_ROOT, ensure_output_dirs

ensure_output_dirs()

_parser = argparse.ArgumentParser(description="Hu & Bai → fused block STEP")
_parser.add_argument("--Q", type=float, default=0.0)
_parser.add_argument("--Af", type=float, default=2.0)
_parser.add_argument("--n-segments", type=int, default=24)
_parser.add_argument("--nx", type=int, default=4)
_parser.add_argument("--ny", type=int, default=4)
_parser.add_argument("--nz", type=int, default=4)
_args = _parser.parse_args()

L = 20.0
ROD_D = 2.0
nx, ny, nz = int(_args.nx), int(_args.ny), int(_args.nz)

gen = HuBaiLatticeGenerator(
    cell_size=L,
    rod_diameter=ROD_D,
    amplitude=float(_args.Af),
    period_factor=float(_args.Q),
    n_segments=max(3, int(_args.n_segments)),
)
gen.build_unitcell()
nodes, beams, polylines = gen.get_data(copy=True)
beams, dups = dedupe_beams(beams)
if dups:
    print(f"  Deduped beams: {dups}", flush=True)

slug = f"hu_bai_{gen.variant_name.lower()}_L{int(L)}"
step_path = os.path.join(
    str(CAD_ROOT), f"{slug}_{nx}x{ny}x{nz}_solid_array.step"
)
manifest_path = os.path.join(
    str(CAD_ROOT), f"{slug}_{nx}x{ny}x{nz}_solid_array_sw_manifest.json"
)

print(
    f"Block fuse: {gen.variant_name} {nx}x{ny}x{nz} -> {step_path}",
    flush=True,
)

stats = export_lattice_step_occ_block(
    nodes,
    beams,
    step_path,
    nx=nx,
    ny=ny,
    nz=nz,
    cell_size=L,
    polylines=polylines,
    junction_spheres=False,
)

report = analyze_step_for_solidworks(step_path, fused_single=True)
bbox = stats.get("bbox_mm") or {}
x_span = float(bbox.get("x", [0, 0])[1]) - float(bbox.get("x", [0, 0])[0])
y_span = float(bbox.get("y", [0, 0])[1]) - float(bbox.get("y", [0, 0])[0])
z_span = float(bbox.get("z", [0, 0])[1]) - float(bbox.get("z", [0, 0])[0])
expected = nx * L
if (
    x_span < expected * 0.8
    or y_span < expected * 0.8
    or z_span < expected * 0.8
):
    raise SystemExit(
        f"[FAIL] Block bbox too small: x={x_span:.1f} y={y_span:.1f} z={z_span:.1f} mm "
        f"(expected ~{expected:.0f} mm per axis)."
    )

manifest = {
    "slug": f"{slug}_{nx}x{ny}x{nz}_solid_array",
    "structure": gen.variant_name,
    "method": stats.get("method"),
    "step_path": step_path,
    "block": stats.get("block"),
    "bbox_mm": bbox,
    "fused_volume_count": report.get("solid_count"),
    "step_product_count": report.get("product_count"),
    "step_solidworks_safe": report.get("solidworks_safe"),
    "paper_params": {
        "cell_size_mm": L,
        "rod_diameter_mm": ROD_D,
        "period_factor_Q": float(_args.Q),
    },
}
with open(manifest_path, "w", encoding="utf-8") as f:
    json.dump(manifest, f, indent=2, ensure_ascii=False)
    f.write("\n")

print(
    f"  OK: volumes={report.get('solid_count')} products={report.get('product_count')} "
    f"sw_safe={report.get('solidworks_safe')} "
    f"span=({x_span:.1f}, {y_span:.1f}, {z_span:.1f}) mm",
    flush=True,
)
print(f"  bbox_mm: {bbox}", flush=True)
print(f"  STEP: {step_path}", flush=True)
print(f"  Manifest: {manifest_path}", flush=True)
print("  -> Open this STEP in SolidWorks to inspect.", flush=True)

if int(report.get("solid_count") or 0) != 1:
    raise SystemExit("[FAIL] Expected 1 fused MANIFOLD_SOLID_BREP.")
