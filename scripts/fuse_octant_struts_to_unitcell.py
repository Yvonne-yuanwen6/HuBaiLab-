"""
Export Q=1 unit-cell STEP from eight octant-cut struts.

Default: sequential OCC fuse (order 0,1,2,3,4,5,7,6).
Use ``--compound`` for eight centre-extended cut struts in one STEP (manual fuse in CAD).

  py -3 scripts/fuse_octant_struts_to_unitcell.py --Q 1.0
  py -3 scripts/fuse_octant_struts_to_unitcell.py --Q 1.0 --both-end-extension
  py -3 scripts/fuse_octant_struts_to_unitcell.py --Q 1.0 --compound
"""

from __future__ import annotations

import argparse
import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from src.export.unitcell_box_cut import export_unitcell_step_paper_box_cut
from src.generator.hu_bai_bcc import HuBaiLatticeGenerator
from src.paths import CAD_ROOT, ensure_output_dirs

ensure_output_dirs()


def main() -> int:
    p = argparse.ArgumentParser(
        description="Export Q=1 unit cell from 8 octant-cut struts (fuse or compound)"
    )
    p.add_argument("--Q", type=float, default=1.0)
    p.add_argument("--Af", type=float, default=2.0)
    p.add_argument("--L", type=float, default=20.0)
    p.add_argument("--rod-d", type=float, default=2.0)
    p.add_argument("--n-segments", type=int, default=24)
    p.add_argument(
        "--compound",
        action="store_true",
        help="8 centre-extended cut struts in one STEP (manual fuse in CAD)",
    )
    p.add_argument(
        "--both-end-extension",
        action="store_true",
        help="Extend each pipe at centre and corner before octant cut + sequential fuse",
    )
    p.add_argument(
        "--centre-extension-mm",
        type=float,
        default=None,
        help="Centre path extension (default: 1.5× rod radius, min 1 mm)",
    )
    p.add_argument(
        "--corner-extension-mm",
        type=float,
        default=None,
        help="Corner path extension (default: same as centre)",
    )
    p.add_argument(
        "--both-end-compound",
        action="store_true",
        help="Write 8 both-end cut struts in one STEP (skip OCC sequential fuse)",
    )
    p.add_argument("--out", default="")
    args = p.parse_args()

    gen = HuBaiLatticeGenerator(
        cell_size=float(args.L),
        rod_diameter=float(args.rod_d),
        amplitude=float(args.Af),
        period_factor=float(args.Q),
        n_segments=max(3, int(args.n_segments)),
    )
    gen.build_unitcell()
    nodes, beams, polylines = gen.get_data(copy=True)
    slug = gen.variant_name.lower()
    out_dir = os.path.join(str(CAD_ROOT), "_unitcell_paper_box_cut")
    os.makedirs(out_dir, exist_ok=True)
    if args.out:
        out_path = args.out
    elif args.compound:
        out_path = os.path.join(out_dir, f"unitcell_{slug}_paper_box_8struts.step")
    elif args.both_end_compound:
        out_path = os.path.join(out_dir, f"unitcell_{slug}_paper_box_both_ext_8struts.step")
    elif args.both_end_extension:
        out_path = os.path.join(out_dir, f"unitcell_{slug}_paper_box_both_ext.step")
    else:
        out_path = os.path.join(out_dir, f"unitcell_{slug}_paper_box.step")

    q1_mode = "compound" if args.compound else "auto"
    if args.both_end_compound:
        q1_mode = "fuse"
    if args.compound:
        label = "8-strut compound"
    elif args.both_end_compound:
        label = "both-end 8-strut compound"
    elif args.both_end_extension:
        label = "both-end extension + sequential fuse"
    else:
        label = "sequential fuse"
    print(f"Export ({label}) -> {out_path}", flush=True)
    report = export_unitcell_step_paper_box_cut(
        nodes,
        beams,
        out_path,
        polylines=polylines,
        cell_size_mm=float(args.L),
        n_segments_hint=max(3, int(args.n_segments)),
        period_factor=float(args.Q),
        q1_mode=q1_mode,
        both_end_extension=args.both_end_extension or args.both_end_compound,
        centre_extension_mm=args.centre_extension_mm,
        corner_extension_mm=args.corner_extension_mm,
        both_ext_compound=args.both_end_compound,
    )

    meta_path = os.path.splitext(out_path)[0] + "_fuse_meta.json"
    with open(meta_path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, ensure_ascii=False)
        fh.write("\n")

    print(f"Wrote: {report.get('step_path', out_path)}", flush=True)
    print(
        f"  mass_after_cut={report.get('mass_mm3_after_cut'):.1f} mm3 "
        f"solids={report.get('fused_volume_count')} "
        f"sw_safe={report.get('step_solidworks_safe')} "
        f"manual_fuse={report.get('manual_fuse_required', False)} "
        f"strategy={report.get('fuse_strategy')}",
        flush=True,
    )
    print(f"Meta: {meta_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
