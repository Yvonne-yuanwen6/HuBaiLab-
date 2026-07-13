# CAD 融合路线与已知问题

Hu & Bai 论文 Fig.2.6 点阵 CAD：**8 根扫掠管 + 虚拟 L³ 盒切割（`paper_box`）**，**无节点球**。  
仿真 export 只认 `output/cad/verified/` 下已验收 STEP；压缩 INP 流程见 [`Abaqus_CAD实体压缩说明.md`](Abaqus_CAD实体压缩说明.md)。  
单胞 OCC 策略细节见 [`单胞融合策略.md`](单胞融合策略.md)。

---

## 1. 当前总览（4×4×4，2026-07）

| Q | 变体 | **推荐阵列路线** | verified 目标文件 | 状态 |
|---|------|------------------|-------------------|------|
| **0** | BCC | gmsh **layered fuse**（pipe-first 单胞） | `hu_bai_bcc_af2q0_L20_4x4x4_paper_box_array.step` | ✅ 已用于 CAE 压缩 |
| **0.5** | SFBLS | 同上 | `hu_bai_sfbls_af2q0p5_L20_4x4x4_paper_box_array.step` | ✅ 已用于 Fig.3.3 / 网格收敛 |
| **1.0** | SFBLS | **OCP GlueShift** layered fuse（单胞 OCP 种子） | `hu_bai_sfbls_af2q1_L20_4x4x4_paper_box_array.step` | ✅ OCP444 已装 verified |
| **1.5** | SFBLS | gmsh layered fuse | `hu_bai_sfbls_af2q1p5_L20_4x4x4_paper_box_array.step` | ✅ 已用于 CAE 压缩 |

**仿真侧自动查找**（`src/export/cad_solid_paths.py`）优先 `*_paper_box_array.step`，其次才是历史的 `*_solid_merged` / `*_solid_array`。

---

## 2. 标准流水线：单胞 → 4×4×4 → verified

```
export_unitcell_paper_box_cut.py          # 单胞 1×1×1
        ↓
run_hu_bai_paper_box_4x4x4_array_fuse.py   # 4×4×4 阵列（默认 layered）
        ↓
validate_step_solidworks.py              # 可选：SW 导入前自动检查
        ↓
人工 SW 目视 / vol=1 验收
        ↓
复制 → output/cad/verified/*_paper_box_array.step
        ↓
run_hu_bai_bcc_solid_cad_cae_tet_export.py / run_paperbox_cae_tet_pipeline.sh
```

### 2.1 单胞（1×1×1）

```powershell
py -3 scripts/export_unitcell_paper_box_cut.py --Q 0 0.5 1.0 1.5
```

输出目录：`output/cad/_unitcell_paper_box_cut/unitcell_{variant}_paper_box.step`

| Q | 单胞融合策略 | 说明 |
|---|--------------|------|
| 0 / 0.5 | pipe-first → L³ 相交 | 直杆 / 正弦杆，gmsh OCC 通常一次成功 |
| 1.0 | **8×octant 切杆 → 顺序 fuse** | 禁止 junction-sphere 种子；详见单胞策略文档 |
| 1.5 | 逐杆 full L³ box-cut → merge | pipe-first 不稳定 |

**Q=1 单胞备选（OCP）**：`bash scripts/linux/run_ocp_glue_fuse_pilot.sh`  
→ `output/cad/_ocp_glue_pilot/unitcell_af2q1_L20_ocp_stub_sequential-glue-shift.step`

单胞验收：`fused_volume_count=1`、`step_solidworks_safe=True`；SW 中 **只打开一个 STEP → 一个零件窗口**。

### 2.2 阵列 4×4×4（layered fuse，默认）

思路：iz=0 做 **4×4** 单层 OCC 融合 → 复制 iz=1..3 → 四层 merge 为 **1 solid**。

**gmsh 后端（Q=0 / 0.5 / 1.5，及 Q=1 对照）**

```powershell
py -3 scripts/run_hu_bai_paper_box_4x4x4_array_fuse.py --Q 0.5 --backend gmsh --force
```

服务器可恢复跑（内存 watchdog）：

```bash
Q=0.5 bash scripts/linux/run_paper_box_layered_safe.sh
# Q=1.0 gmsh 对照：Q=1.0 bash scripts/linux/run_paper_box_layered_safe.sh
```

输出：`output/cad/_paper_box_array_q{tag}/hu_bai_{variant}_L20_4x4x4_paper_box_array.step`

**OCP 后端（Q=1 主用）**

```bash
bash scripts/linux/run_ocp_q1_4x4x4_array_fuse.sh
# 或本机：py -3 scripts/run_hu_bai_paper_box_4x4x4_array_fuse.py --Q 1.0 --backend ocp --force
```

输出：`output/cad/_paper_box_array_q1p0_ocp/hu_bai_sfbls_af2q1_L20_4x4x4_paper_box_array.step`

装 verified（服务器）：

```bash
cp output/cad/_paper_box_array_q1p0_ocp/hu_bai_sfbls_af2q1_L20_4x4x4_paper_box_array.step \
   output/cad/verified/
# 或：bash scripts/linux/run_q1_ocp444_best_pair.sh（顺带清旧 mesh / 提交对照算例）
```

> **注意**：`run_hu_bai_paper_box_4x4x4_array_fuse.py` 默认 `--backend ocp`；对 Q=0/0.5/1.5 **必须**显式 `--backend gmsh`，否则会误用 Q=1 的 OCP 单胞种子。

### 2.3 装入 `verified/` 前检查

```powershell
py -3 scripts/validate_step_solidworks.py output\cad\_paper_box_array_q0p5\*.step
```

| 检查项 | 期望 |
|--------|------|
| `fused_volume_count` | **1** |
| `step_solidworks_safe` | **True** |
| Z 向包络 | ≈ `4 × L` = **80 mm**（4×4×4, L=20） |
| SW 打开 | 单窗口、单实体（可选人工 QA） |

确认后复制为 `output/cad/verified/hu_bai_{variant}_L20_4x4x4_paper_box_array.step`。  
`cad_solid_paths.py` **不接受** verified 以外的路径。

---

## 3. 各 Q 补充说明

### Q=0（BCC）

- 单胞 pipe-first + box-cut 稳定；阵列用 **gmsh layered**（`--backend gmsh`）。
- **不要**再用 `run_hu_bai_bcc_unitcell_array_step_fuse.py` 生成 `_solid_array` 作为论文基准（见 §5 legacy）。
- BCC SW 步进（`_solid_merged`）若磁盘上仍有，仅作历史对照，非 Fig.2.6 几何。

### Q=0.5 / Q=1.5（SFBLS）

- 与 Q=0 相同用 gmsh layered；Q=1.5 单胞走 per-strut box-cut。
- Fig.3.3 / 网格收敛算例已绑定 verified 中的 `paper_box_array` STEP。

### Q=1.0（SFBLS，最复杂）

| 阶段 | 路线 | 状态 |
|------|------|------|
| 单胞 1×1×1 | gmsh octant 顺序 fuse | ✅ ~381 mm³，可作 gmsh 阵列种子 |
| 单胞 1×1×1 | OCP `sequential_glue_shift` | ✅ 当前 **OCP 阵列** 种子 |
| 阵列 4×4×4 | gmsh layered | ✅ ~7 min，`vol=1`（2026-06 验收） |
| 阵列 4×4×4 | OCP layered（`run_ocp_q1_4x4x4_array_fuse.sh`） | ✅ **OCP444** → verified 主文件 |

**禁止**作为 paper_box 阵列种子：SW 手工 Combine 的 8 体 compound、junction-sphere 单胞、一次性 batch fuse 8 octant（会静默丢杆）。细节见 [`单胞融合策略.md`](单胞融合策略.md)。

---

## 4. 阵列融合备选模式（非默认）

| 模式 | 命令 | 用途 |
|------|------|------|
| **layered**（默认） | 无额外 flag | 生产 4×4×4 单实体 |
| `--stepwise-only` | 输出 16 体 compound | SW 手工 Combine（legacy `solid_merged` 路线） |
| `--auto-only` | 64 胞一次性 OCC | 需稳定 1-volume 种子；大阵列易失败 |
| `--strategy in_memory_block` | gmsh iz=0 策略 | 调试 pairwise 顺序 |

SW 步进 compound 输出后须人工 Combine，文件名形如 `zslab_iz0_4x4_paper_box_sw_fused_{variant}.STEP`；**不是**当前仿真输入。

---

## 5. Legacy：`solid_merged` SW 步进（结点球几何）

曾用于 SFBLS Q=1 fast80 与 BCC Q=0 试验；几何含 **9 节点结点球**，与论文 Fig.2.6 **不一致**。  
保留脚本供对照或应急，**新算例请走 paper_box**。

`run_sfbls_sw_stepwise_4x4x4_pipeline.ps1` 流程：

1. Stage 1：单胞 seed + `zslab_iz0_4x4_compound_from_seed.step`（**16 体**）
2. **SolidWorks**：16 体 Combine → `verified/zslab_iz0_4x4_sw_fused_{variant}.STEP`
3. Stage 3：Z 向复制 → `zstack_4x4x4_sw_fused_4layer_compound.step`（**4 体**）
4. **SolidWorks**：4 体 Combine → `verified/hu_bai_{variant}_L20_4x4x4_solid_merged.STEP`
5. Stage 5：fast80 gmsh 导出（旧路线）

BCC 工作目录：`output/cad/_stepwise_q0/`（说明：`README_SW_BCC.txt`）。

---

## 6. BCC OCC 自动融合 — 已知问题（仍暂停）

实验脚本：`scripts/run_hu_bai_array_auto_fuse.py`  
实现：`src/export/array_auto_fuse.py`（safe inter-cell，**不修改** `export_sw.py`）

### 症状

1. **Legacy 路径**（`run_hu_bai_bcc_unitcell_array_step_fuse.py` → `export_sw._fuse_occ_layer_volumes`）  
   - 在 `inter-cell-z0-b0_1` 报：`Unknown OpenCASCADE entity of dimension 3 with tag 12`  
   - 原因：pairwise stall 后 sequential 回退使用 **已失效的 dimtag**

2. **Safe 路径**（`array_auto_fuse.py`）  
   - iz0 整层可跑通；4×4×4 全流程 **极慢**，iz1+ 曾 **静默退出**（无 traceback、无 STEP 落盘）  
   - 2026-06 最远：iz0 ✅，iz1 约 2/4 块后进程消失

### 门控（`AUTO_FUSE_Q_PROFILES`）

| Q | auto_fuse | 当前策略 |
|---|-----------|----------|
| 0 | **disabled** | paper_box gmsh layered |
| 0.5 / 1.0 / 1.5 | disabled | paper_box（Q=1 阵列用 OCP） |

启用 auto-fuse 前须本地跑通 `--cells 4` 且 `fused_volume_count==1`。

### 后续方向（TODO）

- [ ] iz1+ 静默退出：gmsh 心跳日志；分 z-slab 写中间 STEP 断点续跑  
- [ ] BCC 直杆：整层 16 体 compound + 仅 SW 合并（与 legacy 步进相同思路，但输出应转 paper_box 验收）  
- [ ] z-slab OCC（`run_hu_bai_bcc_zslab_step_fuse.py`）逐层融合  
- [ ] 修复 legacy `export_sw._fuse_occ_layer_volumes` stall 逻辑（**单独 PR**）

---

## 7. 目录与脚本索引

| 路径 / 脚本 | 用途 |
|-------------|------|
| `output/cad/_unitcell_paper_box_cut/` | 单胞 paper_box STEP |
| `output/cad/_paper_box_array_q{tag}/` | gmsh 阵列工作目录 |
| `output/cad/_paper_box_array_q1p0_ocp/` | Q=1 OCP 阵列 |
| `output/cad/_ocp_glue_pilot/` | Q=1 OCP 单胞 |
| `output/cad/verified/` | **仿真唯一输入** |
| `export_unitcell_paper_box_cut.py` | 单胞批导出 |
| `run_hu_bai_paper_box_4x4x4_array_fuse.py` | 4×4×4 阵列（layered / stepwise / auto） |
| `run_paper_box_layered_safe.sh` | 服务器可恢复 gmsh layered |
| `run_ocp_q1_4x4x4_array_fuse.sh` | Q=1 OCP 阵列 |
| `run_ocp_glue_fuse_pilot.sh` | Q=1 OCP 单胞 |
| `validate_step_solidworks.py` | STEP 单实体 / 孤儿 PRODUCT 检查 |
| `run_sfbls_sw_stepwise_4x4x4_pipeline.ps1` | **Legacy** SW 步进 → `_solid_merged` |
| `run_hu_bai_bcc_unitcell_array_step_fuse.py` | **Legacy** OCC → `_solid_array` |
| `run_hu_bai_array_auto_fuse.py` | **暂停** BCC safe auto-fuse |

---

## 附录：历史几何对照（简记）

| 后缀 | 几何特征 | 现状 |
|------|----------|------|
| `_paper_box_array` | Fig.2.6，无球，平面 RVE 切 | **仿真主用** |
| `_solid_merged` | SW 步进，常含结点球 | Legacy；部分 fast80 旧算例 |
| `_solid_array` | OCC 单胞平铺 fuse | Legacy BCC fast80；4×4 auto-fuse 暂停 |
| `_solid_layered` | z 层分层 OCC | 备选，慢 |
| junction-sphere 单胞 | 9 节点球 + pipe | 仅 QA，非 paper_box |
