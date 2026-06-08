"""
Hu & Bai 2024 — BCC / SFBLS 3D wireframe preview (Fig. 3.3).

  py -3 scripts/preview_hu_bai_sfbls.py --all-q --cells 1
  py -3 scripts/preview_hu_bai_sfbls.py --Q 0.5 --cells 1
"""

from __future__ import annotations

import argparse
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from src.export.beam_utils import dedupe_beams
from src.generator.hu_bai_bcc import HuBaiLatticeGenerator
from src.visualization.plot_lattice import plot_lattice

_parser = argparse.ArgumentParser(description="Hu & Bai SFBLS 3D wireframe preview")
_parser.add_argument("--Q", type=float, default=None, help="Period factor; default all Fig.3.3 Q values")
_parser.add_argument("--cells", type=int, default=1, help="Cells per axis (1=unit cell)")
_parser.add_argument("--n-segments", type=int, default=16, help="Polyline segments per strut")
_parser.add_argument("--Af", type=float, default=2.0)
_parser.add_argument("--all-q", action="store_true", help="Plot Q=0,0.5,1,1.5")
_args = _parser.parse_args()

L = 20.0
ROD_D = 2.0
AF = float(_args.Af)
NX = NY = NZ = int(_args.cells)
N_SEG = max(4, int(_args.n_segments))

out_dir = os.path.join(_ROOT, "output", "export", "hu_bai", "previews")
os.makedirs(out_dir, exist_ok=True)

if _args.all_q or _args.Q is None:
    q_values = [0.0, 0.5, 1.0, 1.5]
else:
    q_values = [float(_args.Q)]

for q in q_values:
    gen = HuBaiLatticeGenerator(
        cell_size=L,
        rod_diameter=ROD_D,
        amplitude=AF,
        period_factor=q,
        n_segments=N_SEG,
    )
    gen.build_lattice(NX, NY, NZ)
    nodes, beams, polylines = gen.get_data()
    beams, dups = dedupe_beams(beams)
    ex, ey, ez = gen.lattice_extent_mm(NX, NY, NZ)

    tag = gen.variant_name.lower()
    cell_tag = f"{NX}x{NY}x{NZ}"
    seg_tag = f"seg{N_SEG}"
    iso = os.path.join(out_dir, f"{tag}_{cell_tag}_{seg_tag}_iso.png")

    title = (
        f"Hu & Bai {gen.variant_name}  {cell_tag} cells  "
        f"L={L} d={ROD_D} Af={AF} Q={q}  n_seg={N_SEG}"
    )
    plot_lattice(nodes, beams, save_path=iso, polylines=polylines, title=title)

    print(f"{gen.variant_name}: {cell_tag}, footprint {ex:.0f}x{ey:.0f}x{ez:.0f} mm")
    print(f"  nodes={len(nodes)} beams={len(beams)} polylines={len(polylines)} dedup={dups}")
    print(f"  iso: {iso}")

print(f"\nPreviews: {out_dir}")
