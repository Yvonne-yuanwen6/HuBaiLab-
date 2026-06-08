"""
Export Hu & Bai 2024 BCC / SFBLS as STL + Parasolid X_T for SolidWorks.

Default (--fast): merged cylinder + junction sphere mesh, no boolean union (fast).
Optional (--union): single watertight body via trimesh boolean (slow; needs trimesh).

Also writes fused STEP + Parasolid X_T: gmsh STEP (single body) → SolidWorks COM Save As *.x_t.

**Before export:** start SolidWorks (empty or one window). Script attaches via COM, opens STEP,
Save As X_T, closes the temp part — same as your manual workflow.

  py -3 scripts/run_hu_bai_bcc_sw_export.py --cells 3
  py -3 scripts/run_hu_bai_bcc_sw_export.py --no-step-to-xt   # STEP only, no COM
  py -3 scripts/sw_step_to_xt.py path/to/model.step            # convert existing STEP

4×4×4 fused STEP: run_hu_bai_bcc_layered_step_fuse.py (z-layer OCC fuse).
Fallback: trimesh --union STL; B31 INP for quick FEA without solid CAD.
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

from src.export.beam_utils import dedupe_beams
from src.export.export_sw import export_lattice_stl_concat, export_lattice_xt
from src.generator.hu_bai_bcc import HuBaiLatticeGenerator
from src.mesh.solid_union import analyze_cylinder_overlaps, export_union_stl
from src.paths import CAD_ROOT, ensure_output_dirs

ensure_output_dirs()

_parser = argparse.ArgumentParser(description="Hu & Bai BCC/SFBLS → SolidWorks STL")
_parser.add_argument("--Q", type=float, default=0.0, help="Period factor Q (0=BCC)")
_parser.add_argument("--Af", type=float, default=2.0, help="Sinusoidal amplitude A_f [mm]")
_parser.add_argument("--cells", type=int, default=4, help="Cells per axis (paper: 4)")
_parser.add_argument(
    "--unit-cell-only",
    action="store_true",
    help="Export one unit cell only (20 mm cube)",
)
_parser.add_argument(
    "--union",
    action="store_true",
    help="Boolean union via trimesh (slow; watertight single body)",
)
_parser.add_argument(
    "--check-overlap",
    action="store_true",
    help="Run slow penetration analysis (optional QA)",
)
_parser.add_argument(
    "--skip-xt",
    action="store_true",
    help="Skip Parasolid X_T / fused STL generation (concat STL only)",
)
_parser.add_argument(
    "--no-step-to-xt",
    action="store_true",
    help="Skip SolidWorks COM STEP→X_T (write STEP only; SW must be open for auto X_T)",
)
_parser.add_argument(
    "--xt-com",
    action="store_true",
    help=argparse.SUPPRESS,
)
_parser.add_argument(
    "--xt-fuse",
    action="store_true",
    help="Boolean-fuse OCC solids before STEP/X_T (default ON unless --step-multi-body)",
)
_parser.add_argument(
    "--step-multi-body",
    action="store_true",
    help="STEP: keep 700+ separate overlapping bodies (fast; SolidWorks import may crash)",
)
_parser.add_argument(
    "--resolution",
    type=int,
    default=16,
    help="Cylinder/sphere tessellation (default 16; use 12 for 4x4x4 union)",
)
_args = _parser.parse_args()

L = 20.0
ROD_D = 2.0
AF = float(_args.Af)
Q = float(_args.Q)
if _args.unit_cell_only:
    NX = NY = NZ = 1
else:
    NX = NY = NZ = int(_args.cells)
RESOLUTION = max(8, int(_args.resolution))

gen = HuBaiLatticeGenerator(
    cell_size=L,
    rod_diameter=ROD_D,
    amplitude=AF,
    period_factor=Q,
    n_segments=max(24 if abs(Q) > 1e-12 else 12, RESOLUTION),
)
gen.build_lattice(NX, NY, NZ)

nodes, beams, polylines = gen.get_data()
beams, beam_dups = dedupe_beams(beams)
if beam_dups:
    print(f"  Deduped beams: {len(beams)} unique ({beam_dups} duplicates removed)")

variant = gen.variant_name.lower()
slug = f"hu_bai_{variant}_L{int(L)}_{NX}x{NY}x{NZ}"

cad_dir = os.path.join(CAD_ROOT, "hu_bai")
export_dir = os.path.join(_ROOT, "output", "export", "hu_bai", slug)
os.makedirs(cad_dir, exist_ok=True)
os.makedirs(export_dir, exist_ok=True)

stl_name = f"{slug}_solid.stl"
xt_name = f"{slug}_solid.x_t"
step_name = f"{slug}_solid.step"
paths = {
    "cad_stl": os.path.join(cad_dir, stl_name),
    "export_stl": os.path.join(export_dir, stl_name),
    "cad_xt": os.path.join(cad_dir, xt_name),
    "export_xt": os.path.join(export_dir, xt_name),
    "cad_step": os.path.join(cad_dir, step_name),
    "export_step": os.path.join(export_dir, step_name),
    "manifest": os.path.join(cad_dir, f"{slug}_sw_manifest.json"),
}

mode = "union" if _args.union else "concat"
print(f"Export mode: {mode}")
print(f"  {len(nodes)} nodes, {len(beams)} beams, {len(polylines)} polylines")

if _args.union:
    print("  Boolean union (may take several minutes for 4×4×4)...")
    stats = export_union_stl(
        nodes,
        beams,
        paths["cad_stl"],
        polylines=polylines,
        resolution=RESOLUTION,
        junction_spheres=True,
    )
    stats["export_mode"] = "union"
else:
    stats = export_lattice_stl_concat(
        nodes,
        beams,
        paths["cad_stl"],
        polylines=polylines,
        n_theta=RESOLUTION,
        n_sphere_lat=max(6, RESOLUTION // 2),
        n_sphere_lon=RESOLUTION,
        junction_spheres=True,
    )
    stats["export_mode"] = "concat"

shutil.copy2(paths["cad_stl"], paths["export_stl"])

xt_stats: dict | None = None
step_fuse = (not _args.step_multi_body) or _args.xt_fuse
if not _args.skip_xt:
    if _args.step_multi_body:
        print(
            "  [WARN] --step-multi-body: STEP has hundreds of overlapping solids; "
            "SolidWorks may crash. Omit this flag for fused single-body STEP.",
            flush=True,
        )
    fuse_label = "fused single body" if step_fuse else "multi-body (701 parts)"
    step_xt = not _args.no_step_to_xt
    if step_xt and not _args.skip_xt:
        from src.export.sw_parasolid import solidworks_running

        if solidworks_running():
            print("  SolidWorks detected → will convert STEP to X_T via COM", flush=True)
        else:
            print(
                "  [INFO] SolidWorks not running → STEP only; start SW and run "
                "scripts/sw_step_to_xt.py or re-run this script",
                flush=True,
            )
    print(f"  Parasolid / STEP: gmsh {fuse_label}...", flush=True)
    try:
        xt_stats = export_lattice_xt(
            nodes,
            beams,
            paths["cad_xt"],
            polylines=polylines,
            junction_spheres=True,
            fuse=step_fuse,
            keep_step=True,
            step_path=paths["cad_step"],
            mesh_resolution=RESOLUTION,
            step_to_xt=step_xt,
        )
        if xt_stats.get("fused_stl") and os.path.isfile(str(xt_stats["fused_stl"])):
            fused_copy = paths["cad_step"].replace(".step", "_fused.stl")
            shutil.copy2(str(xt_stats["fused_stl"]), fused_copy)
            xt_stats["fused_stl_copy"] = fused_copy
            export_fused = paths["export_stl"].replace("_solid.stl", "_solid_fused.stl")
            shutil.copy2(str(xt_stats["fused_stl"]), export_fused)
            xt_stats["export_fused_stl"] = export_fused
        if xt_stats.get("xt_converted") and os.path.isfile(paths["cad_xt"]):
            shutil.copy2(paths["cad_xt"], paths["export_xt"])
        if os.path.isfile(paths["cad_step"]) and xt_stats.get("method") == "gmsh_occ_step":
            shutil.copy2(paths["cad_step"], paths["export_step"])
        if not xt_stats.get("xt_converted") and xt_stats.get("xt_error"):
            print(f"  [INFO] {xt_stats['xt_error']}", flush=True)
    except Exception as exc:
        print(f"  [WARN] X_T export failed: {exc}", flush=True)
        fused = paths["cad_step"].replace(".step", "_fused.stl")
        xt_stats = {"xt_converted": False, "xt_error": str(exc)}
        if os.path.isfile(fused):
            xt_stats["fused_stl_copy"] = fused
            xt_stats["method"] = "trimesh_union_stl"
        elif os.path.isfile(paths["cad_step"]):
            shutil.copy2(paths["cad_step"], paths["export_step"])
            xt_stats["step_path"] = paths["cad_step"]

if _args.check_overlap:
    print("  Overlap check...", flush=True)
    ov = analyze_cylinder_overlaps(nodes, beams, polylines=polylines)
else:
    ov = {"body_overlap_pairs": None, "skipped": True}
ex, ey, ez = gen.lattice_extent_mm(NX, NY, NZ)

manifest = {
    "slug": slug,
    "structure": gen.variant_name,
    "reference": "Hu & Bai 2024, BCC / SFBLS",
    "export_mode": mode,
    "solidworks_stl": paths["cad_stl"],
    "export_copy": paths["export_stl"],
    "solidworks_xt": paths.get("cad_xt"),
    "solidworks_step": paths.get("cad_step"),
    "export_xt": paths.get("export_xt"),
    "export_step": paths.get("export_step"),
    "paper_params": {
        "cell_size_mm": L,
        "rod_diameter_mm": ROD_D,
        "amplitude_mm": AF,
        "period_factor_Q": Q,
        "block_cells": [NX, NY, NZ],
    },
    "footprint_mm": {"X": ex, "Y": ey, "Z": ez},
    "mesh_stats": stats,
    "xt_stats": xt_stats,
    "overlap_check": ov,
    "solidworks_import": [
        "Auto: gmsh fused STEP → SolidWorks COM → *_solid.x_t (SW must be running)",
        "Manual: py -3 scripts/sw_step_to_xt.py path/to/*_solid.step",
        "Abaqus 2020: import STEP directly (Parasolid ≤ v28) or B31 INP for paper curve",
    ],
}
with open(paths["manifest"], "w", encoding="utf-8") as f:
    json.dump(manifest, f, indent=2, ensure_ascii=False)
    f.write("\n")

print()
print("SolidWorks export complete:")
print(f"  STL:  {paths['cad_stl']}")
print(f"        {paths['export_stl']}")
if xt_stats:
    if xt_stats.get("xt_converted"):
        print(f"  X_T:  {paths['cad_xt']}")
        print(f"        {paths['export_xt']}")
        if xt_stats.get("xt_mesh_only"):
            print("  [NOTE] Auto X_T is mesh-based (small file). For BREP solid, open fused STL manually in SW.")
    elif xt_stats.get("fused_stl_copy") or xt_stats.get("export_fused_stl") or xt_stats.get("xt_manual"):
        fused = xt_stats.get("export_fused_stl") or xt_stats.get("fused_stl_copy") or xt_stats.get("fused_stl")
        if fused:
            print(f"  Fused STL (manual X_T in SolidWorks): {fused}")
            print("    File → Open → Mesh → Solid body → Try to form solid → Save As *.x_t")
    elif xt_stats.get("step_path"):
        print(f"  STEP: {paths['cad_step']} (open in SolidWorks → Save As .x_t)")
        print(f"        {paths['export_step']}")
    if xt_stats.get("xt_converted") and xt_stats.get("method") == "gmsh_occ_step":
        print(f"  STEP: {paths['cad_step']} ({xt_stats.get('solid_count')} analytic solids)")
if mode == "union":
    print(f"  Watertight: {stats.get('watertight')}, volume: {stats.get('volume_mm3', 0):.1f} mm³")
else:
    print(f"  Facets: {stats.get('facet_count')}")
print(f"  Cylinder body overlaps (joint overlap OK): {ov['body_overlap_pairs']}")
print(f"  Manifest: {paths['manifest']}")
