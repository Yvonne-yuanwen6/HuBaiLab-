# Hu & Bai 点阵：Abaqus CAD 实体压缩说明

## CAD 实体（STEP）→ 压板压缩 + 应力应变曲线（主路径）

X_T 与 STEP 为同一 BREP。脚本对 **STEP 做 gmsh 体网格（C3D4）**，写 Explicit INP：

- **顶板刚体**通过 `LATTICE_TOP` ↔ `PLATE_BOT` **接触**下压（默认 `contact_mode=pair`，非运动学耦合）
- **底板固定刚体** + `LATTICE_BOTTOM` ↔ `PLATE_FIXED_TOP` 接触
- 点阵 **自接触** `ALL EXTERIOR`；板位 `plate_standoff=0`、`plate_embed=0.02 mm` 贴合顶面
- 板 XY 比点阵大 `plate_margin=10 mm`

```powershell
# fast 加速档：45% 应变、1.2 mm、10 mm/min、dt=5e-4
py -3 scripts/run_hu_bai_bcc_solid_cad_export.py --cells 3 --profile fast

# fast80（Fig.3.3）：80% 应变、0.8 mm、论文 5 mm/min、dt=1e-4
py -3 scripts/run_hu_bai_bcc_solid_cad_export.py --cells 4 --case-suffix fast80
powershell -File scripts/submit_hu_bai_bcc_solid_cad_compression.ps1 -Cells 3 -Profile fast -ForceRerun

# 论文满行程（0.6 mm、70%、5 mm/min，数天级）
py -3 scripts/run_hu_bai_bcc_solid_cad_export.py --cells 3 --profile paper
powershell -File scripts/submit_hu_bai_bcc_solid_cad_compression.ps1 -Cells 3 -Profile paper

# 粗网格 QA（15% 应变、1.0 mm 网格，slug *_solid_cad_p）
py -3 scripts/run_hu_bai_bcc_solid_cad_export.py --cells 3 --stroke pilot
powershell -File scripts/submit_hu_bai_bcc_solid_cad_compression.ps1 -Stroke pilot -Cells 3
```

加载与论文 §2.4 一致：**5 mm/min** 准静态、工程应变 **70%**、Explicit `dt=1e-4 s`、质量缩放 **×50**、摩擦 **μ=0.1**。  
3×3×3 满行程步长约 **504 s**（42 mm）；4×4×4 约 **672 s**（56 mm）。算例较久，请预留机时。

旧版 `coupling_nodes`（顶面节点与板同步、CAE 里板悬空）仅作调试：

```powershell
py -3 scripts/run_hu_bai_bcc_solid_cad_export.py --contact-mode coupling_nodes --case-suffix cpl
```

### 加速档位（3×3×3，默认 **70% 应变 / 42 mm** + 接触传力）

墙钟 ≈ `(step_time / dt) × 每步 CPU 成本`。

| 档位 | 命令要点 | 行程 | step_time | dt | 粗算墙钟 |
|------|----------|------|-----------|-----|----------|
| **论文满行程（默认）** | `--stroke full` | 42 mm | 504 s | 1e-4 | 数小时 |
| pilot 粗网格 QA | `--stroke pilot` | 9 mm (15%) | 108 s | 1e-4 | ~2 h 量级 |
| dt 加倍 | `--explicit-dt 2e-4 --case-suffix dt2e4` | 同左 | 同左 | 2e-4 | ~0.5× 增量 |

```powershell
# 满行程应力–应变（推荐）
py -3 scripts/run_hu_bai_bcc_solid_cad_export.py --cells 3
powershell -File scripts/submit_hu_bai_bcc_solid_cad_compression.ps1 -Cells 3 -ForceRerun
```

也可用 `--step-time 14.4` 直接覆盖步长。`case_manifest.json` 会记录 `load_rate_mm_min`、`explicit_dt`、`explicit_n_increments_est`。

---


## 若必须从 SolidWorks 导入实体

### 为什么 X_T 会报 “cannot be read”

1. **文件实质是网格，不是 BREP 实体**  
   从 STL 导入后若特征树里是 **网格实体 (Mesh Body)** 或 **图形体**，另存为 `.x_t` 时内容多为 `MESH4` / `GUISE=transmit_mesh`（约 3 KB 的 `.x_t` 或几 MB 的 `.m_t`）。  
   Abaqus 的 *Create Part from Parasolid* 需要 **MANIFOLD_SOLID_BREP** 实体，会判为无效文件。

2. **Parasolid 版本过新**  
   SolidWorks 2025 导出为 **Parasolid 36.1**。若 Abaqus 内核较旧（常见为 v28–v33），也会无法读取。  
   另存为 Parasolid 时如有 **版本** 选项，请选 **28.0 或 30.0**（低于你安装的 Abaqus 所支持版本）。

### 在 SolidWorks 中检查（另存前）

- 特征树应有 **实体文件夹 (Solid Bodies)**，且体积 > 0。  
- 若只有 **网格** / **图形体**，需先 **转为实体**（如：网格建模 → 从网格生成实体 / 曲面缝合），再另存。

### Abaqus 推荐导入方式（按优先级）

| 方式 | 操作 |
|------|------|
| **1. 直接跑 LatticeLab INP** | 见上文，与论文一致 |
| **2. STEP** | SW：另存为 `*.step` → Abaqus：File → Import → Part → **STEP (*.stp, *.step)**，单位 **mm** |
| **3. STL 网格** | Abaqus：Import → **STL** 或作为 Orphan Mesh，再划分实体单元（工作量大） |
| **4. Parasolid** | 仅当 SW 中已是 **真实实体** 且 Parasolid **版本** ≤ Abaqus 支持版本；用 `.x_t` 或 `.x_b` |

### 不要用这些文件进 Abaqus Parasolid 导入

- `*_solid.x_t`（约 3 KB，内含 `MESH4`）  
- `*.m_t`（`GUISE=transmit_mesh`，网格 Parasolid）

### 若 Abaqus 提示 imprecise geometry（不精确几何）

常见于 **OCC 布尔融合** 的 STEP：多根圆柱在节点处硬交、无结点球，或融合容差留下碎边/小面。

**LatticeLab 已更新**：融合 STEP 使用 **结点球 + 杆件重叠**（不修剪杆端，否则 OCC 会留下 90+ 个独立实体，SolidWorks 打开时会报「窗口资源极低」）。

**推荐生成路径（4×4×4，已验证单实体）**：

```powershell
py -3 scripts/run_hu_bai_bcc_unitcell_array_step_fuse.py --cells 4 --Q 0
py -3 scripts/validate_step_solidworks.py output/cad/*_array.step
```

备选：`run_hu_bai_bcc_layered_step_fuse.py`（z 层分层，较慢）。勿用一次性 monolithic fuse（512+ primitive，超 gmsh 256 上限）。

Abaqus 中可：**工具 → 几何编辑 → 修复** 或导入时提高缝合容差；划分网格时用 **四面体 (C3D4/C3D10)**，避免对含碎面的模型用 medial-axis 六面体。

### Abaqus/CAE 内置六面体（C3D8R）与仓库自动体素网格的区别

| 路径 | 谁划分网格 | 单元 | 本仓库状态 |
|------|-----------|------|------------|
| **CAE 内置** | Abaqus Mesh 模块对 **Part 实体** 扫掠/映射/Hex-dominated | C3D8R 等 | **未接入** 压缩 INP 流水线；需 Part 有可扫掠的 `cells` |
| **体素 C3D8R**（`--mesh-method voxel`） | LatticeLab 体素填充 → 写入 INP | C3D8R | **已跑通** 四模型 80%（`voxel1mm80_25mmin_noself`） |
| **Gmsh 四面体**（默认 `tet` / fast80） | Gmsh 读 STEP | C3D4 | 论文主路径 |

**说明：** 体素路线生成的也是 Abaqus **C3D8R 六面体单元**，只是网格在导出 INP 前由 Python 完成，不是在 CAE 里点「划分网格」。

### CAE 内置六面体试点（BCC STEP）

脚本（需 CAE 许可证）：

```powershell
powershell -File scripts/run_abaqus_cae_hex_mesh_pilot.ps1 -SeedMm 1.2
```

当前在本机实测：`mdb.openStep` 对 `verified/*_solid_merged.step` **未生成可划分的 Part**（`Parts: []`），因此 CAE 无法继续 `generateMesh`。常见原因：OCC 融合 STEP 的实体类型/碎面与 Abaqus 批处理导入不兼容，需在 CAE 里 **File → Import → Part → STEP** 并做几何修复，或另存为 Abaqus 支持的 ACIS/Parasolid 版本后再导入。

曲杆 SFBLS 即便导入成功，**全网六面体** 通常仍需大量 **Partition + 扫掠/结构化**；复杂单实体往往只能 Hex-dominated（混有四面体）或退回四面体。项目文档见上文「避免 medial-axis 六面体」。

**推荐顺序：**

1. 若目标是 **打印对齐的均匀六面体砖块**：继续用已完成的 **体素 C3D8R**（老师路线）。
2. 若必须 **CAE 里亲手划六面体**：先在 CAE 交互导入 BCC STEP，划分成功后 **File → Export → Input File**，再把网格并入压缩边界条件（需额外开发 INP 合并）。
3. 若目标是 **论文复现**：用 **Gmsh C3D4 fast80**，不是 CAE 六面体。


### SolidWorks 报「窗口资源极低 / 不能再打开任何窗口」

Windows **GDI 句柄**用尽，常见于：同时打开多个 STEP、反复打开 3×3/4×4×4 大模型、未关闭旧零件。

**处理：**

1. 点 **确定**，在 SW 中 **文件 → 关闭** 所有不需要的零件（只留当前一个）。
2. 仍不行：**完全退出 SolidWorks**，任务管理器确认无 `SLDWORKS.exe`，再重新打开 **仅一个** STEP。
3. **不要**在 SW 里连续打开 `test_fuse_3x.step`、`*_fused.stl`、concat STL 等多个窗口对比。
4. **推荐绕过 SW：** Abaqus 2020 直接 **File → Import → STEP**（`test_fuse_3x_v2.step`），单位 mm，再按需另存或直接在 CAE 里网格化。
5. 复现 Hu & Bai 曲线：用 `run_hu_bai_bcc_export.py` 的 **B31 INP**，无需 SW；实体 CAD 用 `*_solid_array.step`（推荐）或 `*_solid_layered.step`。

---

`output/cad/` 下的单胞 STEP 可在 Abaqus 中试导验证流程；4×4×4 请用 `run_hu_bai_bcc_unitcell_array_step_fuse.py` 或 z 层脚本生成 STEP，或 B31 INP。
