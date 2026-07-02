"""Resume Q1 iz=0 inter-cell merge from existing .work_zslab_cells, then copy + array merge."""
from __future__ import annotations

import glob
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from src.export.paper_box_array_fuse import (
    export_paper_box_array_from_zslabs,
    export_paper_box_zslab_copies,
)
from src.export.paper_box_array_fuse import _fuse_paper_box_zslab_from_cell_steps
from src.paths import CAD_ROOT

adir = os.path.join(str(CAD_ROOT), "_paper_box_array_q1p0")
cells = sorted(glob.glob(os.path.join(adir, ".work_zslab_cells", "cell_*.step")))
if len(cells) != 16:
    raise SystemExit(f"[FAIL] expected 16 cell STEPs, got {len(cells)}")

iz0 = os.path.join(adir, "zslab_iz0_4x4_paper_box_fused.step")
print("=== Merge 16 cells -> iz=0 ===", flush=True)
rep, bbox = _fuse_paper_box_zslab_from_cell_steps(
    cells,
    iz0,
    nx=4,
    ny=4,
    iz=0,
    progress_label="paper-box-zslab-iz0",
)
print(f"  OK iz=0: vol={rep.get('solid_count')}", flush=True)

for iz in range(1, 4):
    out = os.path.join(adir, f"zslab_iz{iz}_4x4_paper_box_fused.step")
    print(f"=== Copy iz=0 -> iz={iz} ===", flush=True)
    export_paper_box_zslab_copies(iz0, [out], cell_size=20.0, start_iz=iz)

array = os.path.join(adir, "hu_bai_sfbls_af2q1_L20_4x4x4_paper_box_array.step")
zslabs = [os.path.join(adir, f"zslab_iz{i}_4x4_paper_box_fused.step") for i in range(4)]
print("=== Merge 4 z-slabs -> array ===", flush=True)
merge = export_paper_box_array_from_zslabs(zslabs, array)
print(f"  OK array: vol={merge.get('fused_volume_count')}", flush=True)
print(array)
