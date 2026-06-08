"""Fused single-body STEP for Hu & Bai SFBLS (gmsh OCC batch fuse, no trimesh)."""

from __future__ import annotations

import argparse
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from src.export.beam_utils import dedupe_beams
from src.export.export_sw import export_lattice_step_occ
from src.generator.hu_bai_bcc import HuBaiLatticeGenerator
from src.paths import CAD_ROOT

_parser = argparse.ArgumentParser(description="SFBLS fused STEP via gmsh OCC")
_parser.add_argument("--Q", type=float, required=True, help="Period factor Q")
_parser.add_argument("--cells", type=int, default=3)
_parser.add_argument("--Af", type=float, default=2.0)
_parser.add_argument(
    "--n-segments",
    type=int,
    default=24,
    help="Centerline samples per strut for pipe sweep wire (default 24)",
)
_parser.add_argument(
    "--no-junction-spheres",
    action="store_true",
    help="Overlap struts at nodes (fewer OCC parts, faster fuse)",
)
_args = _parser.parse_args()

gen = HuBaiLatticeGenerator(
    cell_size=20.0,
    rod_diameter=2.0,
    amplitude=float(_args.Af),
    period_factor=float(_args.Q),
    n_segments=max(3, int(_args.n_segments)),
)
n = int(_args.cells)
gen.build_lattice(n, n, n)
nodes, beams, polylines = gen.get_data()
beams, dups = dedupe_beams(beams)
if dups:
    print(f"  Deduped beams: {dups}")

slug = f"hu_bai_{gen.variant_name.lower()}_L20_{n}x{n}x{n}"
cad_dir = str(CAD_ROOT)
os.makedirs(cad_dir, exist_ok=True)
step_path = os.path.join(cad_dir, f"{slug}_solid.step")

print(f"Gmsh OCC fuse: {gen.variant_name} {n}x{n}x{n} -> {step_path}", flush=True)
stats = export_lattice_step_occ(
    nodes,
    beams,
    step_path,
    polylines=polylines,
    junction_spheres=not _args.no_junction_spheres,
    fuse=True,
)
print(
    f"  OK: solids={stats.get('solid_count')} fused_volumes={stats.get('fused_volume_count')} "
    f"step_products={stats.get('step_product_count')} "
    f"path={step_path}"
)
