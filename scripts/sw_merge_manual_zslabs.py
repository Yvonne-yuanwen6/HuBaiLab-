"""
Merge 4 manual z-slab STEPs in SolidWorks (COM automation).

Start SolidWorks first, then:

  py -3 scripts/sw_merge_manual_zslabs.py --Q 0.5
  py -3 scripts/sw_merge_manual_zslabs.py --manual-dir output/cad/manual/hu_bai_sfbls_af2q1_L20_4x4x4
  py -3 scripts/sw_merge_manual_zslabs.py --manifest output/cad/manual/.../manual_sw_manifest.json --visible
"""

from __future__ import annotations

import argparse
import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from src.export.sw_manual_merge import merge_from_manifest, merge_manual_zslabs, variant_dir_for_q
from src.export.sw_parasolid import solidworks_com_available


def main() -> int:
    parser = argparse.ArgumentParser(description="SolidWorks COM merge of 4 manual z-slabs")
    parser.add_argument("--Q", type=float, default=None, help="Period factor (resolves manual dir)")
    parser.add_argument("--manual-dir", default="", help="Folder with zslab_iz0..iz3.step")
    parser.add_argument("--manifest", default="", help="manual_sw_manifest.json (preferred)")
    parser.add_argument("--out-step", default="", help="Merged STEP output path")
    parser.add_argument("--out-xt", default="", help="Merged Parasolid X_T output path")
    parser.add_argument("--per-layer-combine", action="store_true")
    parser.add_argument("--no-per-layer-combine", action="store_true")
    parser.add_argument("--visible", action="store_true", help="Show SolidWorks window")
    parser.add_argument("--allow-start-sw", action="store_true", help="Start SW if not running")
    args = parser.parse_args()

    if not solidworks_com_available(require_running=not args.allow_start_sw):
        print(
            "[ERROR] SolidWorks is not running. Open SolidWorks, then re-run.\n"
            "  Or pass --allow-start-sw to launch via COM.",
            file=sys.stderr,
        )
        return 1

    per_layer: bool | None = None
    if args.per_layer_combine:
        per_layer = True
    elif args.no_per_layer_combine:
        per_layer = False

    try:
        if args.manifest:
            stats = merge_from_manifest(
                os.path.abspath(args.manifest),
                out_step=args.out_step or None,
                out_xt=args.out_xt or None,
                per_layer_combine=per_layer,
                visible=args.visible,
                allow_start_sw=args.allow_start_sw,
            )
        else:
            if args.manual_dir:
                manual_dir = os.path.abspath(args.manual_dir)
            elif args.Q is not None:
                manual_dir = variant_dir_for_q(args.Q)
            else:
                print("[ERROR] Pass --manifest, --manual-dir, or --Q", file=sys.stderr)
                return 1

            manifest_path = os.path.join(manual_dir, "manual_sw_manifest.json")
            if os.path.isfile(manifest_path):
                stats = merge_from_manifest(
                    manifest_path,
                    out_step=args.out_step or None,
                    out_xt=args.out_xt or None,
                    per_layer_combine=per_layer,
                    visible=args.visible,
                    allow_start_sw=args.allow_start_sw,
                )
            else:
                slug = os.path.basename(manual_dir)
                out_step = args.out_step or os.path.join(manual_dir, f"{slug}_solid_merged.step")
                out_xt = args.out_xt or os.path.splitext(out_step)[0] + ".x_t"
                stats = merge_manual_zslabs(
                    manual_dir,
                    out_step,
                    out_xt=out_xt,
                    per_layer_combine=bool(per_layer),
                    visible=args.visible,
                    allow_start_sw=args.allow_start_sw,
                )
    except Exception as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1

    print(json.dumps(stats, indent=2, ensure_ascii=False))
    print(f"\nOK: merged STEP → {stats.get('merged_step')}")
    if stats.get("merged_xt"):
        print(f"OK: merged X_T  → {stats['merged_xt']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
