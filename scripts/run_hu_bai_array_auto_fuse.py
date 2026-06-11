"""
OCC auto-fuse array STEP (experimental; BCC Q=0 currently DISABLED — use SW stepwise).

  py -3 scripts/run_hu_bai_array_auto_fuse.py --list-profiles
  py -3 scripts/run_hu_bai_array_auto_fuse.py --Q 0 --cells 4   # raises until re-enabled

BCC / SFBLS 4x4x4 production route:
  powershell -File scripts/run_sfbls_sw_stepwise_4x4x4_pipeline.ps1 -Q 0 -Stage 2

Known OCC issues: docs/cad_fuse_routes.md
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from src.export.array_auto_fuse import (
    AUTO_FUSE_Q_PROFILES,
    assert_auto_fuse_enabled,
    export_lattice_step_occ_unitcell_array_auto,
)
from src.export.beam_utils import dedupe_beams
from src.generator.hu_bai_bcc import HuBaiLatticeGenerator
from src.paths import CAD_ROOT, CAD_VERIFIED_ROOT, ensure_output_dirs

ensure_output_dirs()

_parser = argparse.ArgumentParser(
    description="Hu & Bai OCC auto-fuse array STEP (BCC Q=0 enabled; other Q gated)"
)
_parser.add_argument("--Q", type=float, default=0.0, help="Period factor (0=BCC)")
_parser.add_argument("--Af", type=float, default=2.0)
_parser.add_argument("--cells", type=int, default=4, help="Cells per axis")
_parser.add_argument("--n-segments", type=int, default=24)
_parser.add_argument(
    "--no-junction-spheres",
    action="store_true",
    help="Overlap struts at nodes (fewer OCC parts)",
)
_parser.add_argument(
    "--copy-verified",
    action="store_true",
    help="Also copy STEP to output/cad/verified/ for solid_cad_export",
)
_parser.add_argument(
    "--list-profiles",
    action="store_true",
    help="Print AUTO_FUSE_Q_PROFILES and exit",
)
_args = _parser.parse_args()

if _args.list_profiles:
    print(json.dumps(AUTO_FUSE_Q_PROFILES, indent=2, ensure_ascii=False))
    raise SystemExit(0)

L = 20.0
ROD_D = 2.0
n = int(_args.cells)
q = float(_args.Q)

profile = assert_auto_fuse_enabled(q)
print(f"Auto-fuse: {profile['label']}  {n}x{n}x{n}", flush=True)

gen = HuBaiLatticeGenerator(
    cell_size=L,
    rod_diameter=ROD_D,
    amplitude=float(_args.Af),
    period_factor=q,
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
manifest_path = os.path.join(cad_dir, f"{slug}_array_auto_fuse_manifest.json")

print(f"  -> {step_path}", flush=True)
stats = export_lattice_step_occ_unitcell_array_auto(
    nodes,
    beams,
    step_path,
    nx=n,
    ny=n,
    nz=n,
    cell_size=L,
    polylines=polylines,
    junction_spheres=not _args.no_junction_spheres,
)

bbox = stats.get("bbox_mm") or {}
z_span = float(bbox.get("z", [0, 0])[1]) - float(bbox.get("z", [0, 0])[0])
expected_z = n * L
if z_span < expected_z * 0.9:
    print(
        f"  [FAIL] Z extent {z_span:.1f} mm < expected ~{expected_z:.1f} mm.",
        flush=True,
    )
    raise SystemExit(1)

verified_step = None
if _args.copy_verified:
    os.makedirs(str(CAD_VERIFIED_ROOT), exist_ok=True)
    verified_step = os.path.join(
        str(CAD_VERIFIED_ROOT),
        f"{slug}_solid_array.step",
    )
    shutil.copy2(step_path, verified_step)
    print(f"  Verified copy: {verified_step}", flush=True)

manifest = {
    "slug": slug,
    "structure": gen.variant_name,
    "auto_fuse_profile": profile,
    "method": stats.get("method"),
    "step_path": os.path.abspath(step_path),
    "verified_step": os.path.abspath(verified_step) if verified_step else None,
    "unitcell_primitive_count": stats.get("unitcell_primitive_count"),
    "cell_count": stats.get("cell_count"),
    "fused_volume_count": stats.get("fused_volume_count"),
    "step_product_count": stats.get("step_product_count"),
    "step_solidworks_safe": stats.get("step_solidworks_safe"),
    "bbox_mm": stats.get("bbox_mm"),
    "paper_params": {
        "cell_size_mm": L,
        "rod_diameter_mm": ROD_D,
        "amplitude_mm": float(_args.Af),
        "period_factor_Q": q,
        "block_cells": [n, n, n],
    },
}
with open(manifest_path, "w", encoding="utf-8") as fh:
    json.dump(manifest, fh, indent=2, ensure_ascii=False)
    fh.write("\n")

print(
    f"  OK: cells={stats.get('cell_count')} "
    f"fused_volumes={stats.get('fused_volume_count')} "
    f"sw_safe={stats.get('step_solidworks_safe')}",
    flush=True,
)
print(f"  Manifest: {manifest_path}", flush=True)

if int(stats.get("fused_volume_count") or 0) != 1:
    print("  [FAIL] Expected 1 fused MANIFOLD_SOLID_BREP.", flush=True)
    raise SystemExit(1)
