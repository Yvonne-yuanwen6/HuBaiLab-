"""
框域点阵填充 —— 手动改参数的主入口。

用法：只改下面「参数」区块，然后运行：
  py -3 scripts/frame_trim_fill_main.py

阵列层数默认由外框与单胞自动算出：
  NX = NY = round(S / L)
  NZ       = round(H / L)
框尺寸 S、H 默认保持你设的值（不会被层数改写）。

结果：output/cad/_frame_trim_fill/
  *_intersect_skin.step  = 点阵 + 内外壁（推荐打开这个）
  *_intersect.step       = 仅裁切点阵（无壁）
"""

from __future__ import annotations

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from scripts.export_frame_trim_fill import run_frame_trim_fill

# =============================================================================
# 参数（只改这里）
# =============================================================================

# --- 外框（方）与内孔（圆） ---
S = 80.0          # 外方边长 [mm]
R_HOLE = 20.0     # 内圆半径 [mm]，须 2*R_HOLE < S
H = 20.0          # 框高度 [mm]（严格按此值，不会被 NZ*L 覆盖）

# --- 单胞 ---
L = 10.0          # 单胞边长 [mm]
ROD_D = 2.0       # 杆径 [mm]
Q = 1.0           # 周期因子：0=直杆 BCC；0.5/1.0/1.5=SFBLS（Q≠0 会重建种子）
AF = 2.0          # 正弦幅值 [mm]（Q=0 不用）

# --- 阵列层数（默认自动） ---
# True: NX=NY=round(S/L), NZ=round(H/L)；只决定放多少胞，不改框高 H
AUTO_GRID_FROM_FRAME = True
SNAP_S_TO_GRID = False  # True 时仅把 S 收到 nx*L；H 永远不 snap
# 仅当 AUTO_GRID_FROM_FRAME=False 时才用手写层数：
NX = 4
NY = 4
NZ = 1

# --- 壁厚（蒙皮）---
# 内圆衬厚度 + 外方画框壁厚；都设 0 = 不要壁
INNER_WALL_MM = 2.0   # 内圆柱衬壁厚 [mm]
OUTER_WALL_MM = 2.0   # 外方框壁厚 [mm]
# 须满足：R_HOLE + INNER_WALL_MM < S/2 − OUTER_WALL_MM

MODE = "intersect"  # "intersect" 裁切+壁 | "full_only" 只放完整胞 | "both"

# --- 一般不用改 ---
N_SEGMENTS = 12
FUZZY_MM = 0.02
SEED_STEP = ""      # 指定已有 1x1 STEP；空则自动找/生成
DOMAIN_STEP = ""    # 任意外形域 STEP；空则用外方内圆
OUT_DIR = ""        # 空 = output/cad/_frame_trim_fill
# True: 只做一层 nx×ny 裁切融合，再 Z 向复制叠层（外方内圆贯通孔时快很多）
Z_COPY_STACK = True
# True: 只融 +x/+y 象限，再绕 Z 旋转复制×4（外方内圆且 nx、ny 为偶数时）
ROTATE_4FOLD = True


def main() -> int:
    print("=== frame_trim_fill_main ===", flush=True)
    if AUTO_GRID_FROM_FRAME:
        print(
            f"  L={L:g}  rod_d={ROD_D:g}  Q={Q:g}  "
            f"grid=auto(S/L, H/L)",
            flush=True,
        )
    else:
        print(
            f"  L={L:g}  rod_d={ROD_D:g}  Q={Q:g}  grid={NX}x{NY}x{NZ}",
            flush=True,
        )
    print(
        f"  S={S:g}  H={H:g}  R_hole={R_HOLE:g}  "
        f"wall_inner={INNER_WALL_MM:g} wall_outer={OUTER_WALL_MM:g}  mode={MODE}",
        flush=True,
    )
    return run_frame_trim_fill(
        S=float(S),
        H=float(H),
        R_hole=float(R_HOLE),
        L=float(L),
        nx=None if AUTO_GRID_FROM_FRAME else int(NX),
        ny=None if AUTO_GRID_FROM_FRAME else int(NY),
        nz=None if AUTO_GRID_FROM_FRAME else int(NZ),
        rod_d=float(ROD_D),
        Af=float(AF),
        Q=float(Q),
        n_segments=int(N_SEGMENTS),
        mode=str(MODE),
        fuzzy_mm=float(FUZZY_MM),
        skin_mm=0.0,  # 由 INNER/OUTER_WALL_MM 覆盖
        inner_wall_mm=float(INNER_WALL_MM),
        outer_wall_mm=float(OUTER_WALL_MM),
        out_dir=str(OUT_DIR),
        seed_step=str(SEED_STEP),
        domain_step=str(DOMAIN_STEP),
        write_domain=True,
        auto_grid_from_frame=bool(AUTO_GRID_FROM_FRAME),
        snap_frame_to_grid=bool(SNAP_S_TO_GRID),
        fit_height_to_layers=False,
        fit_outer_to_grid=False,
        z_copy_stack=bool(Z_COPY_STACK),
        rotate_4fold=bool(ROTATE_4FOLD),
    )


if __name__ == "__main__":
    raise SystemExit(main())
