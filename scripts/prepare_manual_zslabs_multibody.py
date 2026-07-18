"""
Fallback for Q values where OCC inter-cell fuse fails (e.g. SFBLS Q=1.5).

Export one z-layer as a multi-body STEP: 16 positioned fused unit cells (no
inter-cell boolean). In SolidWorks: Insert → Part → Combine → Add.

  py -3 scripts/prepare_manual_zslabs_multibody.py --Q 1.5
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
    _configure_occ_for_fuse,
    _lattice_cell_center_mm,
    _occ_list_volume_dimtags,
    export_lattice_step_occ,
)
from src.generator.hu_bai_bcc import HuBaiLatticeGenerator
from src.mesh.occ_pipe import prune_occ_for_step_export
from src.paths import CAD_ROOT, ensure_output_dirs

ensure_output_dirs()

_parser = argparse.ArgumentParser(description="Multi-body z-slab STEPs for manual SW merge")
_parser.add_argument("--Q", type=float, default=1.5)
_parser.add_argument("--Af", type=float, default=2.0)
_parser.add_argument("--nx", type=int, default=4)
_parser.add_argument("--ny", type=int, default=4)
_parser.add_argument("--nz", type=int, default=4)
_parser.add_argument("--n-segments", type=int, default=24)
_args = _parser.parse_args()

L = 20.0
nx, ny, nz = int(_args.nx), int(_args.ny), int(_args.nz)

gen = HuBaiLatticeGenerator(
    cell_size=L,
    rod_diameter=2.0,
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
manual_dir = os.path.join(str(CAD_ROOT), "manual", f"{slug}_{nx}x{ny}x{nz}")
work_dir = os.path.join(manual_dir, ".work_multibody")
os.makedirs(manual_dir, exist_ok=True)
os.makedirs(work_dir, exist_ok=True)

seed_path = os.path.join(work_dir, "unitcell_seed.step")
if not os.path.isfile(seed_path):
    print(f"Fuse unit cell -> {seed_path}", flush=True)
    export_lattice_step_occ(
        nodes,
        beams,
        seed_path,
        polylines=polylines,
        junction_spheres=False,
        fuse=True,
    )

import gmsh

z_center = lambda iz: (iz - (nz - 1) / 2.0) * L
layers: list[dict] = []

def _count_step_solids(step_path: str) -> int:
    with open(step_path, "r", encoding="utf-8", errors="ignore") as fh:
        return fh.read().count("MANIFOLD_SOLID_BREP")


for iz in range(nz):
    out_name = f"zslab_iz{iz}.step"
    out_path = os.path.join(manual_dir, out_name)
    if os.path.isfile(out_path) and os.path.getsize(out_path) > 1_000_000:
        n_bodies = _count_step_solids(out_path)
        print(f"  iz={iz}: [skip] exists, bodies={n_bodies}", flush=True)
        layers.append(
            {
                "iz": iz,
                "step": out_path,
                "z_center_mm": z_center(iz),
                "body_count": n_bodies,
                "step_solidworks_safe": None,
                "size_bytes": os.path.getsize(out_path),
                "method": "multibody_16_cells",
            }
        )
        continue

    print(f"Z-layer iz={iz}: 16 positioned cells -> {out_path}", flush=True)

    cell_offsets: list[tuple[float, float, float]] = []
    for iy in range(ny):
        for ix in range(nx):
            cell_offsets.append(
                (
                    _lattice_cell_center_mm(ix, nx, L),
                    _lattice_cell_center_mm(iy, ny, L),
                    _lattice_cell_center_mm(iz, nz, L),
                )
            )

    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add(f"zlayer_iz{iz}")
        gmsh.model.occ.importShapes(os.path.abspath(seed_path))
        gmsh.model.occ.synchronize()
        _configure_occ_for_fuse()

        seed_vols = _occ_list_volume_dimtags()
        if len(seed_vols) != 1:
            raise RuntimeError(f"Seed must be 1 volume, got {len(seed_vols)}")
        seed_vol = seed_vols[0]

        for dx, dy, dz in cell_offsets:
            copied = list(gmsh.model.occ.copy([seed_vol]))
            if abs(dx) > 1e-9 or abs(dy) > 1e-9 or abs(dz) > 1e-9:
                gmsh.model.occ.translate(copied, float(dx), float(dy), float(dz))
            gmsh.model.occ.synchronize()

        gmsh.model.occ.remove([seed_vol], recursive=True)
        gmsh.model.occ.synchronize()
        n_vol = len(gmsh.model.getEntities(3))
        if n_vol != nx * ny:
            raise RuntimeError(f"Expected {nx * ny} volumes, got {n_vol}")

        prune_occ_for_step_export()
        gmsh.write(out_path)
    finally:
        gmsh.finalize()

    n_bodies = _count_step_solids(out_path)
    layers.append(
        {
            "iz": iz,
            "step": out_path,
            "z_center_mm": z_center(iz),
            "body_count": n_bodies,
            "step_solidworks_safe": None,
            "size_bytes": os.path.getsize(out_path),
            "method": "multibody_16_cells",
        }
    )
    print(
        f"  iz={iz}: bodies={n_bodies} size={os.path.getsize(out_path)}",
        flush=True,
    )

readme = os.path.join(manual_dir, "README_SW_MERGE.txt")
with open(readme, "w", encoding="utf-8") as f:
    f.write(
        f"SolidWorks manual merge — {gen.variant_name} {nx}x{ny}x{nz}\n"
        f"(multi-body fallback: OCC inter-cell fuse failed for Q={_args.Q})\n"
        f"============================================================\n\n"
        f"Each zslab_iz*.step contains 16 separate fused unit-cell bodies,\n"
        f"already positioned at the correct world coordinates.\n\n"
        f"Per layer:\n"
        f"  1. New Part → Insert → Part → zslab_izN.step\n"
        f"  2. Combine → Add (merge 16 bodies into one solid)\n\n"
        f"After all 4 layers merged:\n"
        f"  3. Combine → Add the 4 layer solids (if imported separately)\n"
        f"  4. Save As Parasolid (*.x_t) or STEP\n"
        f"  5. Export INP:\n"
        f"       py -3 scripts/run_hu_bai_bcc_solid_cad_export.py --cells {nx} "
        f"--Q {_args.Q} --profile fast --cad <merged.step>\n\n"
    )

manifest = {
    "slug": f"{slug}_{nx}x{ny}x{nz}",
    "structure": gen.variant_name,
    "method": "manual_sw_multibody_zslab",
    "note": "16 bodies per layer; Combine in SolidWorks",
    "manual_dir": manual_dir,
    "cell_size_mm": L,
    "block": [nx, ny, nz],
    "layers": layers,
    "solidworks_merge_readme": readme,
}
manifest_path = os.path.join(manual_dir, "manual_sw_manifest.json")
with open(manifest_path, "w", encoding="utf-8") as f:
    json.dump(manifest, f, indent=2, ensure_ascii=False)
    f.write("\n")

print(f"\nManual folder: {manual_dir}", flush=True)
print(f"OK: {nz} multi-body z-layers ready for SolidWorks merge.", flush=True)
