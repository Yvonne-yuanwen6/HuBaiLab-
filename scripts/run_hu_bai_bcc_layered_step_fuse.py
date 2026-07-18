"""
Fused single-body STEP via z-layer hierarchical Gmsh OCC fuse.

Each z-slab (e.g. 4×4×1) is boolean-unioned separately, then slab solids are
tree-fused into one MANIFOLD_SOLID_BREP. Targets 4×4×4 where monolithic fuse fails.

  py -3 scripts/run_hu_bai_bcc_layered_step_fuse.py --cells 4
  py -3 scripts/run_hu_bai_bcc_layered_step_fuse.py --cells 4 --Q 0
  py -3 scripts/validate_step_solidworks.py output/cad/*_layered.step
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
from src.export.export_sw import export_lattice_step_occ_layered
from src.generator.hu_bai_bcc import HuBaiLatticeGenerator
from src.paths import CAD_ROOT, ensure_output_dirs

ensure_output_dirs()

_parser = argparse.ArgumentParser(
    description="Hu & Bai BCC/SFBLS → fused STEP (z-layer OCC fuse)"
)
_parser.add_argument("--Q", type=float, default=0.0, help="Period factor Q (0=BCC)")
_parser.add_argument("--Af", type=float, default=2.0, help="Sinusoidal amplitude A_f [mm]")
_parser.add_argument("--cells", type=int, default=4, help="Cells per axis (paper: 4)")
_parser.add_argument(
    "--n-segments",
    type=int,
    default=24,
    help="Centerline samples per strut for pipe sweep (default 24)",
)
_parser.add_argument(
    "--keep-layer-steps",
    action="store_true",
    help="Keep per-z-slab STEP files (*_layer0.step, ...)",
)
_args = _parser.parse_args()

L = 20.0
ROD_D = 2.0
n = int(_args.cells)
nz = n

gen = HuBaiLatticeGenerator(
    cell_size=L,
    rod_diameter=ROD_D,
    amplitude=float(_args.Af),
    period_factor=float(_args.Q),
    n_segments=max(3, int(_args.n_segments)),
)

layer_data: list[tuple[list, list, list]] = []
for iz in range(nz):
    gen.build_lattice_z_layer(n, n, nz, iz)
    nodes, beams, polylines = gen.get_data(copy=True)
    beams, dups = dedupe_beams(beams)
    if dups:
        print(f"  Layer {iz}: deduped {dups} beams", flush=True)
    layer_data.append((nodes, beams, polylines))

slug = f"hu_bai_{gen.variant_name.lower()}_L{int(L)}_{n}x{n}x{n}"
cad_dir = str(CAD_ROOT)
os.makedirs(cad_dir, exist_ok=True)
step_path = os.path.join(cad_dir, f"{slug}_solid_layered.step")
manifest_path = os.path.join(cad_dir, f"{slug}_layered_sw_manifest.json")

print(
    f"Gmsh OCC layered fuse: {gen.variant_name} {n}x{n}x{n} "
    f"({nz} z-slabs) -> {step_path}",
    flush=True,
)
stats = export_lattice_step_occ_layered(
    layer_data,
    step_path,
    junction_spheres=False,
    keep_layer_steps=_args.keep_layer_steps,
)

bbox = stats.get("bbox_mm") or {}
z_span = float(bbox.get("z", [0, 0])[1]) - float(bbox.get("z", [0, 0])[0])
expected_z = n * L
if z_span < expected_z * 0.9:
    print(
        f"  [FAIL] Z extent {z_span:.1f} mm < expected ~{expected_z:.1f} mm "
        f"({n} cells) — see layer_stats.",
        flush=True,
    )
    sys.exit(1)

manifest = {
    "slug": slug,
    "structure": gen.variant_name,
    "method": stats.get("method"),
    "step_path": step_path,
    "layer_count": stats.get("layer_count"),
    "layer_stats": stats.get("layer_stats"),
    "solid_count": stats.get("solid_count"),
    "fused_volume_count": stats.get("fused_volume_count"),
    "step_product_count": stats.get("step_product_count"),
    "step_solidworks_safe": stats.get("step_solidworks_safe"),
    "paper_params": {
        "cell_size_mm": L,
        "rod_diameter_mm": ROD_D,
        "amplitude_mm": float(_args.Af),
        "period_factor_Q": float(_args.Q),
        "block_cells": [n, n, n],
    },
}
with open(manifest_path, "w", encoding="utf-8") as f:
    json.dump(manifest, f, indent=2, ensure_ascii=False)
    f.write("\n")

print(
    f"  OK: primitives={stats.get('solid_count')} "
    f"fused_volumes={stats.get('fused_volume_count')} "
    f"step_products={stats.get('step_product_count')} "
    f"sw_safe={stats.get('step_solidworks_safe')}",
    flush=True,
)
print(f"  Manifest: {manifest_path}", flush=True)

if int(stats.get("fused_volume_count") or 0) != 1:
    print(
        "  [FAIL] Expected 1 fused MANIFOLD_SOLID_BREP — see layer_stats in manifest.",
        flush=True,
    )
    sys.exit(1)
