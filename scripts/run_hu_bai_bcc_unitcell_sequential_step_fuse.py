"""
Fused single-body STEP for Hu & Bai BCC/SFBLS 4×4×4 arrays.

Default strategy ``translate``: fuse one z-slab (iz=0), z-translate-copy other
layers, then inter-slab merge (~5–12 min for SFBLS Q=0.5).

Legacy strategy ``sequential``: unit-cell seed + 64 cell STEPs + row/z-slab merge.

  py -3 scripts/run_hu_bai_bcc_unitcell_sequential_step_fuse.py --cells 4 --Q 0.5
  py -3 scripts/run_hu_bai_bcc_unitcell_sequential_step_fuse.py --cells 4 --Q 0.5 --keep-work-dir
  py -3 scripts/run_hu_bai_bcc_unitcell_sequential_step_fuse.py --cells 4 --Q 0.5 --strategy legacy
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
from src.export.export_sw import (
    export_lattice_step_occ_unitcell_array_sequential,
    export_lattice_step_occ_unitcell_array_translate,
)
from src.generator.hu_bai_bcc import HuBaiLatticeGenerator
from src.paths import CAD_ROOT, ensure_output_dirs

ensure_output_dirs()

_parser = argparse.ArgumentParser(
    description="Hu & Bai BCC/SFBLS → fused STEP (unit-cell sequential / z-slab)"
)
_parser.add_argument("--Q", type=float, default=0.0, help="Period factor Q (0=BCC)")
_parser.add_argument("--Af", type=float, default=2.0, help="Sinusoidal amplitude A_f [mm]")
_parser.add_argument("--cells", type=int, default=4, help="Cells per axis (paper: 4)")
_parser.add_argument("--n-segments", type=int, default=24)
_parser.add_argument("--no-junction-spheres", action="store_true")
_parser.add_argument("--keep-work-dir", action="store_true")
_parser.add_argument("--no-resume", action="store_true", help="Regenerate all intermediate STEPs")
_parser.add_argument(
    "--strategy",
    choices=("translate", "legacy"),
    default="translate",
    help="translate: one z-slab + z-copy (default); legacy: 64-cell sequential merge",
)
_parser.add_argument(
    "--zslab-ref",
    default="",
    help="Reuse existing fused z-slab STEP (e.g. output/cad/..._zslab_iz0.step)",
)
_args = _parser.parse_args()

L = 20.0
ROD_D = 2.0
n = int(_args.cells)

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

slug = f"hu_bai_{gen.variant_name.lower()}_L{int(L)}_{n}x{n}x{n}"
cad_dir = str(CAD_ROOT)
os.makedirs(cad_dir, exist_ok=True)
step_path = os.path.join(cad_dir, f"{slug}_solid_array.step")
manifest_path = os.path.join(cad_dir, f"{slug}_array_sw_manifest.json")

zslab_ref = _args.zslab_ref.strip() or None
print(
    f"Gmsh OCC array ({_args.strategy}): {gen.variant_name} {n}x{n}x{n} -> {step_path}",
    flush=True,
)
if _args.strategy == "translate":
    stats = export_lattice_step_occ_unitcell_array_translate(
        nodes,
        beams,
        step_path,
        nx=n,
        ny=n,
        nz=n,
        cell_size=L,
        polylines=polylines,
        junction_spheres=not _args.no_junction_spheres,
        keep_work_dir=_args.keep_work_dir,
        resume=not _args.no_resume,
        zslab_ref_path=zslab_ref,
    )
else:
    stats = export_lattice_step_occ_unitcell_array_sequential(
        nodes,
        beams,
        step_path,
        nx=n,
        ny=n,
        nz=n,
        cell_size=L,
        polylines=polylines,
        junction_spheres=not _args.no_junction_spheres,
        keep_work_dir=_args.keep_work_dir,
        resume=not _args.no_resume,
    )

bbox = stats.get("bbox_mm") or {}
z_span = float(bbox.get("z", [0, 0])[1]) - float(bbox.get("z", [0, 0])[0])
expected_z = n * L
if z_span < expected_z * 0.9:
    print(
        f"  [FAIL] Z extent {z_span:.1f} mm < expected ~{expected_z:.1f} mm ({n} cells).",
        flush=True,
    )
    sys.exit(1)

manifest = {
    "slug": slug,
    "structure": gen.variant_name,
    "method": stats.get("method"),
    "step_path": step_path,
    "unitcell_primitive_count": stats.get("unitcell_primitive_count"),
    "cell_count": stats.get("cell_count"),
    "solid_count": stats.get("solid_count"),
    "fused_volume_count": stats.get("fused_volume_count"),
    "step_product_count": stats.get("step_product_count"),
    "step_solidworks_safe": stats.get("step_solidworks_safe"),
    "bbox_mm": stats.get("bbox_mm"),
    "step_brep_face_count": stats.get("step_brep_face_count"),
    "step_mass_mm3": stats.get("step_mass_mm3"),
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
    f"  OK: unitcell_primitives={stats.get('unitcell_primitive_count')} "
    f"cells={stats.get('cell_count')} "
    f"fused_volumes={stats.get('fused_volume_count')} "
    f"step_products={stats.get('step_product_count')} "
    f"sw_safe={stats.get('step_solidworks_safe')}",
    flush=True,
)
print(f"  Manifest: {manifest_path}", flush=True)

if int(stats.get("fused_volume_count") or 0) != 1:
    print("  [FAIL] Expected 1 fused MANIFOLD_SOLID_BREP.", flush=True)
    sys.exit(1)
