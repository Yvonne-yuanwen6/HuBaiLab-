"""
Copy a SW-manually-fused 4×4 z-slab (1 solid) along +Z to build iz1..iz3,
and a 4-body compound for final SW merge.

  py -3 scripts/export_zstack_from_sw_fused_layer.py ^
      --seed output/cad/verified/zslab_iz0_4x4_sw_fused.STEP

Outputs go to output/cad/_stepwise_q1p0/sw_zstack/ (never writes into verified/).
Copy your final SW-merged 4×4×4 STEP into verified/ yourself when ready.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from src.export.export_sw import export_unitcell_array_from_seed
from src.paths import CAD_ROOT, ensure_output_dirs

ensure_output_dirs()

_DEFAULT_OUT = os.path.join(str(CAD_ROOT), "_stepwise_q1p0", "sw_zstack")

_parser = argparse.ArgumentParser(description="Z-stack copies from SW-fused 4×4 layer")
_parser.add_argument(
    "--seed",
    default=os.path.join(str(CAD_ROOT), "verified", "zslab_iz0_4x4_sw_fused.STEP"),
    help="Read-only input (typically under verified/)",
)
_parser.add_argument("--cell-size", type=float, default=20.0)
_parser.add_argument("--layers", type=int, default=4)
_parser.add_argument(
    "--out-dir",
    default=_DEFAULT_OUT,
    help=f"Work output dir (default: {_DEFAULT_OUT})",
)
_args = _parser.parse_args()

seed = os.path.abspath(_args.seed)
if not os.path.isfile(seed):
    raise SystemExit(f"[FAIL] Seed not found: {seed}")

out_dir = os.path.abspath(_args.out_dir.strip() or _DEFAULT_OUT)
verified_root = os.path.abspath(os.path.join(str(CAD_ROOT), "verified"))
try:
    out_common = os.path.commonpath([out_dir, verified_root])
except ValueError:
    out_common = ""
if out_common == verified_root:
    raise SystemExit(
        f"[FAIL] Refusing to write into {verified_root}. "
        f"Use --out-dir (default: {_DEFAULT_OUT})."
    )

os.makedirs(out_dir, exist_ok=True)
L = float(_args.cell_size)
n_layers = max(1, int(_args.layers))

offsets = [(0.0, 0.0, float(iz) * L) for iz in range(n_layers)]

print(f"Z-stack from SW fused layer: {seed}", flush=True)
print(f"  Pitch L={L:g} mm, layers={n_layers}", flush=True)

layer_reports: list[dict] = []
for iz, (dx, dy, dz) in enumerate(offsets):
    out_step = os.path.join(out_dir, f"zslab_iz{iz}_4x4_sw_fused_copy.step")
    print(f"  iz={iz} dz={dz:g} -> {out_step}", flush=True)
    report = export_unitcell_array_from_seed(
        seed,
        out_step,
        [(dx, dy, dz)],
        fuse=False,
        compound_max_flatten=64,
    )
    bbox = report.get("bbox_mm") or {}
    span = {
        k: float(bbox[k][1]) - float(bbox[k][0]) for k in ("x", "y", "z") if bbox
    }
    z_center = (float(bbox["z"][0]) + float(bbox["z"][1])) / 2.0 if bbox else 0.0
    layer_reports.append(
        {
            "iz": iz,
            "dz_mm": dz,
            "step_path": os.path.abspath(out_step),
            "z_center_mm": z_center,
            "span_mm": span,
            "solid_count": report.get("solid_count"),
            "step_solidworks_safe": report.get("solidworks_safe"),
        }
    )
    print(
        f"    OK: z_center={z_center:.1f} span=({span.get('x', 0):.1f}, "
        f"{span.get('y', 0):.1f}, {span.get('z', 0):.1f}) solids={report.get('solid_count')}",
        flush=True,
    )

compound_path = os.path.join(out_dir, "zstack_4x4x4_sw_fused_4layer_compound.step")
print(f"  4-layer compound -> {compound_path}", flush=True)
compound_report = export_unitcell_array_from_seed(
    seed,
    compound_path,
    offsets,
    fuse=False,
    compound_max_flatten=64,
)
cbbox = compound_report.get("bbox_mm") or {}
cspan = {
    k: float(cbbox[k][1]) - float(cbbox[k][0]) for k in ("x", "y", "z") if cbbox
}
manifest = {
    "seed_step": seed,
    "cell_size_mm": L,
    "layers": n_layers,
    "layer_steps": layer_reports,
    "compound_step": os.path.abspath(compound_path),
    "compound_span_mm": cspan,
    "compound_solid_count": compound_report.get("solid_count"),
    "compound_sw_safe": compound_report.get("solidworks_safe"),
    "next_step": (
        "SolidWorks: open zstack_4x4x4_sw_fused_4layer_compound.step "
        "(4 solids, 1 window) → Combine → Add → manually save to "
        "output/cad/verified/hu_bai_sfbls_af2q1_L20_4x4x4_solid_merged.step"
    ),
}
manifest_path = os.path.join(out_dir, "zstack_4x4x4_sw_fused_manifest.json")
with open(manifest_path, "w", encoding="utf-8") as fh:
    json.dump(manifest, fh, indent=2, ensure_ascii=False)
    fh.write("\n")

print(
    f"  Compound OK: span=({cspan.get('x', 0):.1f}, {cspan.get('y', 0):.1f}, "
    f"{cspan.get('z', 0):.1f}) solids={compound_report.get('solid_count')} "
    f"sw_safe={compound_report.get('solidworks_safe')}",
    flush=True,
)
print(f"\nManifest: {manifest_path}", flush=True)

if int(compound_report.get("solid_count") or 0) != n_layers:
    raise SystemExit(
        f"[FAIL] Expected {n_layers} solids in compound, got {compound_report.get('solid_count')}."
    )
