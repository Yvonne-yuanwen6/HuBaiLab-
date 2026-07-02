# CAD 融合路线与已知问题

## 推荐路线（4×4×4）

| 结构 | 推荐 | 脚本 |
|------|------|------|
| **BCC Q=0** | **SW 步进**（当前） | `run_sfbls_sw_stepwise_4x4x4_pipeline.ps1 -Q 0` |
| SFBLS Q=0.5/1/1.5 | SW 步进 **或** paper_box OCC | 见 [unitcell_fusion_strategies.md](unitcell_fusion_strategies.md) |
| **SFBLS Q=1 paper_box** | **OCP 单胞 ✅ → 4×4×4 进行中** | `run_ocp_glue_fuse_pilot.sh` → `run_ocp_q1_4x4x4_array_fuse.sh` |
| BCC Q=0（历史） | OCC 单胞阵列 fuse | `run_hu_bai_bcc_unitcell_array_step_fuse.py`（legacy，见下方问题） |

SW 步进流程（与 SFBLS Q=1.0 已验证路线相同）：

1. Stage 1：单胞 seed + `zslab_iz0_4x4_compound_from_seed.step`（**16 体**）
2. **SolidWorks**：16 体 Combine → 1 体 → `verified/zslab_iz0_4x4_sw_fused_{variant}.STEP`
3. Stage 3：Z 向复制 + `zstack_4x4x4_sw_fused_4layer_compound.step`（**4 体**）
4. **SolidWorks**：4 体 Combine → 1 体 → `verified/hu_bai_{variant}_L20_4x4x4_solid_merged.STEP`
5. Stage 5：fast80 导出 + Abaqus

BCC 工作目录：`output/cad/_stepwise_q0/`  
说明文件：`output/cad/_stepwise_q0/README_SW_BCC.txt`

---

## SFBLS Q=1 paper_box — 当前状态（2026-06）

| 阶段 | 路线 | 状态 |
|------|------|------|
| 单胞 1×1×1 | OCP `sequential_glue_shift`（`run_ocp_glue_fuse_pilot.sh`） | ✅ 已验收 |
| 单胞 1×1×1 | gmsh `export_unitcell_paper_box_cut.py --Q 1.0` | ⚠️ 未作当前基准 |
| 阵列 4×4×4 | OCP `run_ocp_q1_4x4x4_array_fuse.sh` | ❌ 尚未成功 |
| 阵列 4×4×4 | gmsh `run_hu_bai_paper_box_4x4x4_array_fuse.py` | ❌ 尚未成功 |

OCP 单胞种子：`output/cad/_ocp_glue_pilot/unitcell_af2q1_L20_ocp_stub_sequential-glue-shift.step`  
详情：[unitcell_fusion_strategies.md](unitcell_fusion_strategies.md)

---

## BCC OCC 自动融合 — 已知问题（2026-06，待修）

实验脚本：`scripts/run_hu_bai_array_auto_fuse.py`  
实现：`src/export/array_auto_fuse.py`（safe inter-cell，**不修改** `export_sw.py`）

### 症状

1. **Legacy 路径**（`run_hu_bai_bcc_unitcell_array_step_fuse.py` → `export_sw._fuse_occ_layer_volumes`）  
   - 在 `inter-cell-z0-b0_1` 报：`Unknown OpenCASCADE entity of dimension 3 with tag 12`  
   - 原因：pairwise stall 后 sequential 回退使用 **已失效的 dimtag**（pairwise 已消费旧 tag）

2. **Safe 路径**（`array_auto_fuse.py`）  
   - 修复了 stale tag 问题，iz0 整层可跑通  
   - 但 4×4×4 全流程 **极慢**（每层多组 sequential fuse），且多次运行中在 **iz1 中途静默退出**（无 traceback、无 STEP 落盘）  
   - 2026-06 实测最远进度：iz0 ✅，iz1 约 2/4 块后进程消失

### 已尝试的 safe 修复（保留在 `array_auto_fuse.py`）

- pairwise 结果只保留 `dim==3` 的体  
- stall 后用 **live** post-pairwise tag，不用 stall 前的 `current`  
- sequential / stall 使用 `restrict_cleanup=True`，避免 `_occ_remove_all_volumes_except` 误删未融合单胞  

### 后续修改方向（TODO）

- [ ] iz1+ 静默退出：加 gmsh 超时/心跳日志；分 z-slab 写中间 STEP 便于断点续跑  
- [ ] 减少 sequential 次数：BCC 直杆可尝试整层 16 体 compound（无 OCC fuse）+ 仅 SW 合并（与 SFBLS 相同）  
- [ ] 或 z-slab OCC fuse（`run_hu_bai_bcc_zslab_step_fuse.py`）逐层融合再 inter-slab merge  
- [ ] 修复 legacy `export_sw._fuse_occ_layer_volumes` stall 逻辑（**需单独 PR，勿影响 SFBLS Q>0 在用手动路线**）  
- [ ] 历史成功案例（3×3×3 / 4×4×4 BCC fast80）曾用 `_solid_array.step`；磁盘上文件已缺失，需用 SW 或修好 OCC 后重生成

### Q 配置门控（`AUTO_FUSE_Q_PROFILES`）

| Q | auto_fuse | 当前策略 |
|---|-----------|----------|
| 0 | **disabled** | SW 步进（本文件） |
| 0.5 / 1.0 / 1.5 | disabled | SW 步进 |

启用 auto-fuse 前须在本地跑通 `--cells 4` 并验收 `fused_volume_count==1`。
