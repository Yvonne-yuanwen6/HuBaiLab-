"""
Prepare 4 z-slab STEPs under output/cad/manual/ for SolidWorks manual merge.

Each slab is fused to a single body and already positioned at the correct Z
coordinate (world mm). In SolidWorks: Insert → Part → browse all four STEPs,
then Combine → Add to merge into one solid. Save As Parasolid (*.x_t) for Abaqus.

  py -3 scripts/prepare_manual_zslabs.py --Q 0.5
  py -3 scripts/prepare_manual_zslabs.py --Q 0.5 --skip-generate
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from src.export.sw_parasolid import analyze_step_for_solidworks
from src.generator.hu_bai_bcc import HuBaiLatticeGenerator
from src.paths import CAD_ROOT, ensure_output_dirs

ensure_output_dirs()

_parser = argparse.ArgumentParser(description="Prepare 4 z-slabs in output/cad/manual/")
_parser.add_argument("--Q", type=float, default=0.5)
_parser.add_argument("--Af", type=float, default=2.0)
_parser.add_argument("--nx", type=int, default=4)
_parser.add_argument("--ny", type=int, default=4)
_parser.add_argument("--nz", type=int, default=4)
_parser.add_argument(
    "--skip-generate",
    action="store_true",
    help="Only copy existing z-slab STEPs; do not run fuse for missing layers",
)
_args = _parser.parse_args()

L = 20.0
nx, ny, nz = int(_args.nx), int(_args.ny), int(_args.nz)

gen = HuBaiLatticeGenerator(
    cell_size=L,
    rod_diameter=2.0,
    amplitude=float(_args.Af),
    period_factor=float(_args.Q),
    n_segments=24,
)
gen.build_unitcell()
slug = f"hu_bai_{gen.variant_name.lower()}_L{int(L)}"
manual_dir = os.path.join(str(CAD_ROOT), "manual", f"{slug}_{nx}x{ny}x{nz}")
os.makedirs(manual_dir, exist_ok=True)

py = sys.executable
z_center = lambda iz: (iz - (nz - 1) / 2.0) * L

layers: list[dict] = []
missing: list[int] = []

for iz in range(nz):
    src_name = f"{slug}_zslab_iz{iz}.step"
    src_path = os.path.join(str(CAD_ROOT), src_name)
    dst_name = f"zslab_iz{iz}.step"
    dst_path = os.path.join(manual_dir, dst_name)

    if not os.path.isfile(src_path):
        if _args.skip_generate:
            missing.append(iz)
            continue
        print(f"[gen] iz={iz} -> {src_path}", flush=True)
        rc = subprocess.call(
            [
                py,
                os.path.join(_ROOT, "scripts", "run_hu_bai_bcc_zslab_step_fuse.py"),
                "--Q",
                str(_args.Q),
                "--Af",
                str(_args.Af),
                "--nx",
                str(nx),
                "--ny",
                str(ny),
                "--block-nx",
                str(nx),
                "--block-ny",
                str(ny),
                "--block-nz",
                str(nz),
                "--iz",
                str(iz),
            ],
            cwd=_ROOT,
        )
        if rc != 0:
            raise SystemExit(f"z-slab generation failed for iz={iz} (exit {rc})")

    if not os.path.isfile(src_path):
        missing.append(iz)
        continue

    shutil.copy2(src_path, dst_path)
    report = analyze_step_for_solidworks(dst_path, fused_single=True)
    layers.append(
        {
            "iz": iz,
            "step": dst_path,
            "z_center_mm": z_center(iz),
            "fused_volume_count": report.get("solid_count"),
            "step_solidworks_safe": report.get("solidworks_safe"),
            "size_bytes": os.path.getsize(dst_path),
        }
    )
    print(
        f"  iz={iz}: {dst_path}  z={z_center(iz):g} mm  "
        f"volumes={report.get('solid_count')} sw_safe={report.get('solidworks_safe')}",
        flush=True,
    )

readme = os.path.join(manual_dir, "README_SW_MERGE.txt")
with open(readme, "w", encoding="utf-8") as f:
    f.write(
        f"SolidWorks manual merge — {gen.variant_name} {nx}x{ny}x{nz}\n"
        f"============================================================\n\n"
        f"Files: zslab_iz0.step … zslab_iz{nz - 1}.step (each single fused body)\n"
        f"Cell size L = {L:g} mm; layer centres at z = "
        + ", ".join(f"{z_center(i):g}" for i in range(nz))
        + " mm\n\n"
        "Steps:\n"
        "  1. New Part → Insert → Part → select all zslab_iz*.step\n"
        "  2. Combine → Add (merge bodies into one solid)\n"
        "  3. File → Save As → Parasolid (*.x_t)\n"
        "  4. Re-run export with --cad pointing to the merged STEP or X_T:\n"
        f"       py -3 scripts/run_hu_bai_bcc_solid_cad_export.py --cells {nx} "
        f"--Q {_args.Q} --cad <merged.step>\n\n"
    )

manifest = {
    "slug": f"{slug}_{nx}x{ny}x{nz}",
    "structure": gen.variant_name,
    "method": "manual_sw_zslab_merge",
    "manual_dir": manual_dir,
    "cell_size_mm": L,
    "block": [nx, ny, nz],
    "layers": layers,
    "missing_iz": missing,
    "solidworks_merge_readme": readme,
    "expected_merged_step": os.path.join(
        manual_dir, f"{slug}_{nx}x{ny}x{nz}_solid_merged.step"
    ),
}
manifest_path = os.path.join(manual_dir, "manual_sw_manifest.json")
with open(manifest_path, "w", encoding="utf-8") as f:
    json.dump(manifest, f, indent=2, ensure_ascii=False)
    f.write("\n")

print(f"\nManual folder: {manual_dir}", flush=True)
print(f"Manifest: {manifest_path}", flush=True)
if missing:
    print(f"[WARN] Missing layers: iz={missing}", flush=True)
    raise SystemExit(1)
if len(layers) != nz:
    raise SystemExit(f"Expected {nz} layers, got {len(layers)}")
print(f"OK: {nz} z-slabs ready for SolidWorks merge.", flush=True)
