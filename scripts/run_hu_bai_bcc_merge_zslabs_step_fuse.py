"""
Merge independently fused z-slab STEPs into one block solid (in-memory OCC fuse).

  py -3 scripts/run_hu_bai_bcc_merge_zslabs_step_fuse.py --Q 0.5 --through-iz 1
  py -3 scripts/run_hu_bai_bcc_merge_zslabs_step_fuse.py --Q 0.5 --nz 4
"""

from __future__ import annotations

import argparse
import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from src.export.export_sw import _merge_step_solids_in_memory
from src.export.sw_parasolid import analyze_step_for_solidworks
from src.generator.hu_bai_bcc import HuBaiLatticeGenerator
from src.paths import CAD_ROOT, ensure_output_dirs

ensure_output_dirs()

_parser = argparse.ArgumentParser(description="Merge z-slab STEPs → block STEP")
_parser.add_argument("--Q", type=float, default=0.0)
_parser.add_argument("--Af", type=float, default=2.0)
_parser.add_argument("--nx", type=int, default=4)
_parser.add_argument("--ny", type=int, default=4)
_parser.add_argument("--nz", type=int, default=4)
_parser.add_argument(
    "--through-iz",
    type=int,
    default=None,
    help="Merge z-slabs iz=0..N only (e.g. 1 → iz0+iz1 for SW check)",
)
_parser.add_argument("--work-dir", default=None)
_args = _parser.parse_args()

L = 20.0
nx, ny, nz = int(_args.nx), int(_args.ny), int(_args.nz)
through_iz = int(_args.through_iz) if _args.through_iz is not None else nz - 1
if not (0 <= through_iz < nz):
    raise SystemExit(f"--through-iz must be in [0, {nz - 1}], got {through_iz}")

gen = HuBaiLatticeGenerator(
    cell_size=L,
    rod_diameter=2.0,
    amplitude=float(_args.Af),
    period_factor=float(_args.Q),
    n_segments=24,
)
gen.build_unitcell()
slug = f"hu_bai_{gen.variant_name.lower()}_L{int(L)}"

slab_paths: list[str] = []
for iz in range(through_iz + 1):
    p = os.path.join(str(CAD_ROOT), f"{slug}_zslab_iz{iz}.step")
    if not os.path.isfile(p):
        raise SystemExit(
            f"Missing z-slab STEP: {p}\n"
            f"Run run_hu_bai_bcc_zslab_step_fuse.py --Q {_args.Q} --iz {iz} first."
        )
    slab_paths.append(p)

work_dir = _args.work_dir or os.path.join(
    str(CAD_ROOT),
    f".__translate_fuse_{slug}_{nx}x{ny}x{nz}_solid_array",
)
os.makedirs(work_dir, exist_ok=True)

merge_inputs = slab_paths[: through_iz + 1]
merge_path = os.path.join(work_dir, f"_merge_0{through_iz}.step")
is_final = through_iz == nz - 1
out_path = (
    os.path.join(str(CAD_ROOT), f"{slug}_{nx}x{ny}x{nz}_solid_array.step")
    if is_final
    else merge_path
)
manifest_path = os.path.join(
    str(CAD_ROOT),
    f"{slug}_{nx}x{ny}x{nz}_merge_0{through_iz}_sw_manifest.json"
    if not is_final
    else f"{slug}_{nx}x{ny}x{nz}_solid_array_sw_manifest.json",
)

print(
    f"Merge z-slabs iz=0..{through_iz} ({len(merge_inputs)} slab(s)) -> {out_path}",
    flush=True,
)
for iz, p in enumerate(merge_inputs):
    print(f"  input iz={iz}: {p}", flush=True)

report = _merge_step_solids_in_memory(
    merge_inputs,
    merge_path,
    progress_label=f"inter-slab-0-{through_iz}",
)

if is_final and merge_path != out_path:
    import shutil

    shutil.copy2(merge_path, out_path)

manifest = {
    "slug": f"{slug}_{nx}x{ny}x{nz}_merge_0{through_iz}" if not is_final else f"{slug}_{nx}x{ny}x{nz}_solid_array",
    "structure": gen.variant_name,
    "method": "gmsh_occ_zslab_inmem_merge",
    "step_path": out_path,
    "zslab_inputs": merge_inputs,
    "through_iz": through_iz,
    "fused_volume_count": report.get("solid_count"),
    "step_product_count": report.get("product_count"),
    "step_solidworks_safe": report.get("solidworks_safe"),
}
with open(manifest_path, "w", encoding="utf-8") as f:
    json.dump(manifest, f, indent=2, ensure_ascii=False)
    f.write("\n")

print(
    f"  OK: volumes={report.get('solid_count')} products={report.get('product_count')} "
    f"sw_safe={report.get('solidworks_safe')}",
    flush=True,
)
print(f"  STEP: {out_path}", flush=True)

if int(report.get("solid_count") or 0) != 1:
    raise SystemExit("[FAIL] Expected 1 fused MANIFOLD_SOLID_BREP.")
