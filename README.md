# HuBaiLab

重庆大学 Hu & Bai (2024) **BCC / SFBLS** 点阵结构复现工具：几何生成、融合实体 STEP、Abaqus 压缩仿真与应力–应变曲线提取。

从 [LatticeLab](https://github.com/) 主仓库中提取的 **Hu & Bai 专用子集**，供课题组独立克隆使用。

## 功能

| 能力 | 说明 |
|------|------|
| 点阵生成 | BCC (Q=0) 与正弦屈曲杆 SFBLS (Q>0)，单胞 20 mm，杆径 2 mm |
| 融合 STEP | 单胞 OCC 阵列（**推荐**）、z 层分层、小块 monolithic fuse |
| SolidWorks | STL 预览、STEP → Parasolid X_T（需 Windows + SolidWorks） |
| Abaqus 实体压缩 | STEP → gmsh 四面体网格 → Explicit INP + 刚体压板；**paper_box** 另路：CAE C3D4 + STORE OFFSETS |
| B31 梁单元 | 无实体 CAD 时快速出工程应力–应变曲线 |
| 后处理 | 从 ODB 提取曲线、屈服/极限点分析 |

## 目录结构

```
HuBaiLab/
├── src/
│   ├── generator/hu_bai_bcc.py    # 点阵几何核心
│   ├── export/                      # INP / STEP / CSV 导出
│   ├── mesh/                        # gmsh OCC 扫掠、体网格
│   ├── postprocess/                 # 压缩曲线元数据
│   └── validation/                  # 穿透风险检查
├── scripts/                         # 运行入口（见下表）
├── docs/Abaqus_CAD实体压缩说明.md # Abaqus / SW 导入详解
├── output/                          # 运行结果（含示例算例，见 output/README.md）
│   ├── cad/                         # 融合 STEP
│   ├── export/{slug}/               # INP / manifest
│   ├── jobs/{slug}/                 # Abaqus 作业
│   └── post/{slug}/                 # 应力–应变曲线
└── requirements.txt
```

## 环境准备

**必需**

- Python 3.11+
- PowerShell 5+（Windows 一键提交脚本）

**按用途可选**

| 依赖 | 用途 |
|------|------|
| `gmsh` | 融合 STEP、体网格（**核心路径必需**） |
| `numpy`, `matplotlib` | 几何与线框预览 |
| `trimesh`, `manifold3d` | STL 布尔合并（`--union` 可选） |
| `pywin32` | SolidWorks COM 转 X_T（Windows） |
| Abaqus（PATH 中有 `abaqus`） | Explicit 求解与 ODB 后处理 |
| SolidWorks | STEP → X_T、手动 CAD 检查 |

```powershell
git clone https://github.com/Yvonne-yuanwen6/HuBaiLab-.git
cd HuBaiLab-

py -3 -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
```

已有算例数据（STEP、ODB、曲线等）由组内打包分发，解压到 `output/` 对应子目录即可（见下方「算例数据分发」）。

## 快速开始

### 0. 单胞融合 STEP（SolidWorks QA，阵列前必做）

**paper box-cut（论文 Fig.2.6，无节点球）** — 推荐用于 Abaqus `paper_box` 与 CAE 网格。

**Q=1 当前状态（2026-06）**：仅 **OCP 单胞** 验收通过；**4×4×4 阵列尚未成功**。详见 [docs/单胞融合策略.md](docs/单胞融合策略.md)。

```bash
# Q=1 单胞（OCP，当前成功路线）
bash scripts/linux/run_ocp_glue_fuse_pilot.sh
# 或本地：py -3 scripts/_tmp_ocp_glue_fuse_pilot.py --strategy sequential_glue_shift
```

输出：`output/cad/_ocp_glue_pilot/unitcell_af2q1_L20_ocp_stub_sequential-glue-shift.step`

Q=0 / Q=0.5 / Q=1.5 仍用 gmsh：

```powershell
py -3 scripts/export_unitcell_paper_box_cut.py --Q 0.5
```

**各 Q 单胞融合策略**（pipe sweep + 虚拟 L³ 切割，无中心球）见 **[docs/单胞融合策略.md](docs/单胞融合策略.md)**：

| Q | 策略摘要 | 状态 |
|---|----------|------|
| 0 / 0.5 | pipe-first fuse → RVE L³ 相交 | gmsh 通常成功 |
| **1.0** | **8×octant 切杆 → OCP sequential_glue_shift** | **单胞 ✅；4×4×4 ❌** |
| 1.5 | 逐杆 full L³ box-cut → strut merge | gmsh |

Q=1 用 octant/OCP paper_box 种子，勿使用已禁用的 junction-sphere 路线。

**SolidWorks 验收（paper_box 单胞）**

| 检查项 | 期望 |
|--------|------|
| 杆件 | **8 根** SFBLS 曲杆，外边界 ±L/2 平切 |
| 节点球 | **无**（论文几何） |
| 实体 | **1** 个 `MANIFOLD_SOLID_BREP` |
| 窗口 | **只打开一个 STEP → 一个零件窗口** |

单杆 octant 切 QA：`py -3 scripts/export_single_strut_paper_box_cut.py --Q 1.0 --strut 1`

---

### 0b. paper_box 4×4×4 融合 STEP（Q=1 进行中）

先完成 **0. paper box-cut 单胞**（Q=1 须 OCP 路线，见上）。再尝试阵列融合：

```bash
# OCP 阵列（当前主攻）
bash scripts/linux/run_ocp_q1_4x4x4_array_fuse.sh
```

```powershell
# gmsh 阵列（对照）
py -3 scripts/run_hu_bai_paper_box_4x4x4_array_fuse.py --Q 1.0
```

目标输出：`output/cad/_paper_box_array_q1p0_ocp/hu_bai_sfbls_af2q1_L20_4x4x4_paper_box_array.step`（或 gmsh 目录 `_paper_box_array_q1p0/`）

**截至 2026-06：Q=1 的 4×4×4 尚未验收**（`vol=1`、`step_solidworks_safe=True`）。详见 [docs/单胞融合策略.md](docs/单胞融合策略.md#444-阵列融合paper_box--q1-进行中)。

### 1. 生成 4×4×4 融合 STEP（legacy BCC / solid_array）

```powershell
cd D:\HuBaiLab
$env:PYTHONPATH = (Get-Location).Path

py -3 scripts/run_hu_bai_bcc_unitcell_array_step_fuse.py --cells 4 --Q 0
py -3 scripts/validate_step_solidworks.py output/cad/*_array.step
```

输出示例：`output/cad/hu_bai_bcc_af2q0_L20_4x4x4_solid_array.step`

### 2. Abaqus 实体压缩 + 应力–应变曲线

```powershell
# 快速档（45% 应变，几小时量级）
py -3 scripts/run_hu_bai_bcc_solid_cad_export.py --cells 3 --profile fast
powershell -ExecutionPolicy Bypass -File scripts/submit_hu_bai_bcc_solid_cad_compression.ps1 -Cells 3 -Profile fast

# 论文满行程（70% 应变，数天量级）
py -3 scripts/run_hu_bai_bcc_solid_cad_export.py --cells 3 --profile paper
powershell -ExecutionPolicy Bypass -File scripts/submit_hu_bai_bcc_solid_cad_compression.ps1 -Cells 3 -Profile paper
```

### 3. 无实体 CAD：B31 梁单元（最快出曲线）

```powershell
py -3 scripts/run_hu_bai_bcc_export.py --cells 3
powershell -ExecutionPolicy Bypass -File scripts/submit_hu_bai_bcc_compression.ps1
```

> `run_hu_bai_bcc_export.py` 标注为 deprecated，但 B31 路径仍可用于快速对比。

### 4. SFBLS 线框预览

```powershell
py -3 scripts/preview_hu_bai_sfbls.py --all-q --cells 1
```

## 已验证成功案例

以下记录来自本地 `output/`（Abaqus 完成以 `{slug}.sta` 含 `COMPLETED SUCCESSFULLY` 为准）。每个算例的完整参数见 `output/export/{slug}/case_manifest.json`。

### 共用材料与接触（实体 C3D4 压缩）

| 项 | 取值 |
|----|------|
| 材料 | TPU：E = 25 MPa，ν = 0.47，屈服 4.69 MPa，ρ = 1135 kg/m³ |
| 单元 | gmsh 四面体 **C3D4**（`mesh.source = gmsh_step_volume`） |
| 求解器 | Abaqus **Explicit**，固定增量步 |
| 传力 | 顶/底 **刚体压板** + `contact_mode=pair`；点阵 **自接触** `ALL EXTERIOR` |
| 摩擦 | μ = 0.1 |
| 质量缩放 | ×50（`BELOW MIN, dt=…`） |
| 板位 | `plate_margin=10 mm`，`plate_embed≈0.4–0.6 mm` |

### `paper_box` + CAE C3D4：t=0 网格畸变（自接触过盈）

Hu & Bai 论文 Fig.2.6 几何为 **无节点球** 的 `paper_box` 杆件（pipe-first + RVE 盒切割），与带 **9 个节点球** 融合的 `solid_merged` / `solid_array` 不同。在 **点阵自接触 ON**、**Abaqus/CAE 自动 C3D4** 前提下，曾出现 **increment 0 即失败**（畸变单元、autodt ~10⁻⁸–10⁻⁹ s、`CHNG MASS` 激增），易被误判为“网格质量差”。

**根因（已用导出 INP 全扫描确认）**

| 对比项 | `solid_merged`（体素 C3D8R，可跑通） | `paper_box`（CAE C3D4，t=0 失败） |
|--------|--------------------------------------|-----------------------------------|
| 静态网格长宽比 p95 | ~2（正常） | ~2（正常，**不是**主因） |
| 初始自接触过盈对数 | 少；中位过盈 ~0.017 mm | **~1165–1423 对** |
| 过盈量级 | 仅极少数 >0.15 mm | 枢纽处 **~0.2–0.3 mm**（无节点球，杆件在节点处几何相交） |
| t=0 机制 | 过盈小，默认 nodal adjustment 可承受 | Explicit 默认 **无应变 nodal adjustment** 在 t=0 推节点 → **16–22 个畸变单元** |

**无效或不足的尝试**

- 仅调 CAE 网格（`lattice_contact` seed 0.6 mm；~94 万–131 万 C3D4）：预检通过，t=0 仍失败。
- `--contact-soft-clearance`（general contact `SCALE FACTOR` s0=0.08）：预检通过，t=0 仍失败。
- `INTERFERENCE FIT` 作用于 `ALL EXTERIOR` 自接触：预检失败（不支持）。
- 板–点阵 `INTERFERENCE FIT`：预检失败（曲面过复杂）。
- 仅 **ContactSettle** 两步（软接触 s0=0.02、μ=0）：预检通过，**t=0 仍失败**（仍触发 nodal adjustment）。
- 仅 **Virtual Topology**（`createVirtualTopology`）：过盈对数略降，t=0 仍失败。

**有效方案（当前 `paper_box` pipeline 默认）**

两步 Explicit + **STORE OFFSETS**，在 `src/export/abaqus_compression.py` 写出：

```inp
*Contact Controls Assignment, AUTOMATIC OVERCLOSURE RESOLUTION
, , STORE OFFSETS
```

- **STORE OFFSETS**：用接触偏移记录初始过盈，**避免** t=0 无应变 nodal adjustment 推畸变网格；increment 0 可通过，autodt 恢复 ~10⁻⁴ s 量级。
- **Step 1 `ContactSettle`**（115.2 s = 15%×768 s）：零位移 + 软自接触 `SETTLE-CONTACT`（`SCALE FACTOR` s0=**0.02**，μ=**0**）；步内再次声明 STORE OFFSETS。
- **Step 2 `Compression`**（768 s，80% 应变，5 mm/min）：切换 **HARD-CONTACT**（μ=0.1）+ 顶板位移加载。
- **辅助**：CAE `--cae-virtual-topology`（默认开）略减过盈对数；**不能**单独替代 STORE OFFSETS。

**Linux 服务器一键（BCC Q=0 / SFBLS Q=0.5 等同参）**

```bash
cd /path/to/HuBaiLab
export PATH="$HOME/APP/abaqus2022/Commands:$PATH"
export PYTHONPATH=.

# BCC paper_box（默认 Q=0）
bash scripts/linux/run_paperbox_cae_tet_pipeline.sh

# SFBLS Q=0.5
bash scripts/linux/run_paperbox_cae_tet_pipeline.sh --Q 0.5
```

算例 slug 形如：`hu_bai_{variant}_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox`。导出 CLI 开关：`--contact-store-offsets`、`--contact-settle`、`--contact-settle-fraction 0.15`、`--contact-settle-soft-s0 0.02`、`--cae-virtual-topology`。终端双算例监视：`scripts/watch_paperbox_jobs.ps1`。

**fast 加速档**（非论文原参）：工程应变 **45%**，gmsh **1.2 mm**，准静态加载 **10 mm/min**，Explicit **dt = 5×10⁻⁴ s**，幅值 hold **2%** step_time，`--profile fast`（4×4×4：36 mm / **216 s**）。

**fast80 档**（Fig. 3.3 对比用）：工程应变 **80%**，gmsh **0.8 mm**，加载与论文一致（**5 mm/min**，dt = **1×10⁻⁴ s**，hold **5%**），`--case-suffix fast80`（4×4×4：64 mm / **768 s**，约 **7.68×10⁶** 增量；8 核墙钟约 **25–40 h** 量级，视网格单元数与是否早停）。

### 端到端完成（STEP → 网格 → Abaqus → 应力–应变曲线）

| slug | 几何 | STEP 模型 | 网格划分 | 仿真设置 | 结果 |
|------|------|-----------|----------|----------|------|
| `hu_bai_bcc_af2q0_L20_3x3x3_solid_cad_f_fast80_lr25m12` | BCC Q=0，3×3×3 | `output/cad/hu_bai_bcc_af2q0_L20_3x3x3_solid_array.step`（单胞 OCC 阵列 `_solid_array`） | 目标尺寸 **1.2 mm**；**25 602** 节点，**66 217** C3D4 | fast80：80% 应变，压缩 **48 mm / 115.2 s**，dt = 5×10⁻⁴，**25 mm/min**，~230 400 增量 | `.sta` 成功（**已归档** `_lr25m12`） |
| `hu_bai_bcc_af2q0_L20_4x4x4_solid_cad_f_fast80_lr25m12` | BCC Q=0，4×4×4 | `output/cad/hu_bai_bcc_af2q0_L20_4x4x4_solid_array.step` | 目标尺寸 **1.2 mm**；**57 212** 节点，**147 895** C3D4 | fast80：80% 应变，压缩 **64 mm / 153.6 s**，dt = 5×10⁻⁴，**25 mm/min**，~307 200 增量 | `.sta` 成功（**已归档** `_lr25m12`） |

旧参算例已重命名归档（释放 canonical slug `*_fast80`）。归档命令：

```powershell
powershell -File scripts/archive_bcc_fast80_legacy.ps1
```

复现 BCC 4×4×4 fast80（**默认**：0.8 mm、5 mm/min、768 s、dt=1e-4）：

```powershell
py -3 scripts/run_hu_bai_bcc_unitcell_array_step_fuse.py --cells 4 --Q 0
powershell -File scripts/run_bcc_q1_4x4x4_fast80.ps1 -SkipQ1   # 仅 BCC fast80
```

### STEP 融合已验收（CAD 阶段成功，供网格/仿真使用）

| 变体 | STEP 路径 | 生成方式 | SW / gmsh 验收 |
|------|-----------|----------|----------------|
| SFBLS Q=0.5/1/1.5 单胞（paper_box） | `output/cad/_unitcell_paper_box_cut/unitcell_*_paper_box.step` | `export_unitcell_paper_box_cut.py` | 8 杆 L³ 平切，无节点球，单实体 |
| **SFBLS Q=1.0 单胞（paper_box，OCP）** | `output/cad/_ocp_glue_pilot/unitcell_af2q1_L20_ocp_stub_sequential-glue-shift.step` | `_tmp_ocp_glue_fuse_pilot.py` / `run_ocp_glue_fuse_pilot.sh`：octant 切杆 + **OCP GlueShift** | `vol=1`，无节点球，SW 单窗口 |
| SFBLS Q=1.0，4×4×4（paper_box） | `output/cad/_paper_box_array_q1p0_ocp/`（目标） | `run_ocp_q1_4x4x4_array_fuse.sh` 或 gmsh `run_hu_bai_paper_box_4x4x4_array_fuse.py` | **❌ 尚未验收** |
| SFBLS Q=1.0，4×4×4（legacy SW） | `output/cad/verified/hu_bai_sfbls_af2q1_L20_4x4x4_solid_merged.STEP` | `run_sfbls_sw_stepwise_4x4x4_pipeline.ps1`：16 体 compound → SW → Z 复制 → 4 体 SW 合并 | 已用于 fast80 网格导出（**非** paper_box 几何） |
| **BCC Q=0，4×4×4**（进行中） | `output/cad/_stepwise_q0/` → `verified/…_solid_merged.STEP` | **同上 SW 步进** `-Q 0`；16 体已生成，待 SW 合并 | OCC 自动融合暂停，见 `docs/CAD融合路线与已知问题.md` |

> **manual/ 旧文件已清理**：此前 `output/cad/manual/` 下的 z-slab / merged STEP 为 Frenet 圆片堆叠（错误扫掠），已全部删除。请用修复后的扫掠重新生成：
>
> ```powershell
> py -3 scripts/prepare_manual_zslabs.py --Q 0.5   # 或 1.0 / 1.5
> # SW 合并四层 → 另存 merged.step，再跑 solid_cad_export
> ```

### 网格已导出、仿真正在进行（尚未写入成功案例表）

| slug | STEP | 网格 | 仿真设置 | 状态 |
|------|------|------|----------|------|
| `hu_bai_sfbls_af2q0p5_L20_4x4x4_solid_cad_f_fast80` | `…/hu_bai_sfbls_af2q0p5_L20_4x4x4_solid_array.step` | **1.42 mm**（旧）；新默认 **0.8 mm** | fast80，256 s，15 mm/min | Abaqus 运行中 |
| `hu_bai_sfbls_af2q1_L20_4x4x4_solid_cad_f_fast80` | `cad/verified/…_solid_merged.STEP` | **0.8 mm**；121 525 节点，329 767 C3D4 | fast80，256 s，**15 mm/min** | Abaqus 运行中（已有部分 ODB 采样） |

Fig. 3.3 目标批量（3×3×3 SFBLS Q=0.5/1/1.5 fast80）见 `scripts/submit_hu_bai_fig33_sfbls_fast80.ps1`；4×4×4 SFBLS 流水线见 `scripts/run_hu_bai_sfbls_4x4x4_array_pipeline.ps1`。

## 脚本索引

| 脚本 | 用途 |
|------|------|
| `export_unitcell_paper_box_cut.py` | **单胞 paper_box STEP**（SW 目视 QA；无节点球） |
| `export_pair_fuse_check.py` | 2-cell 化合物（Y + X）；Q=1.0 勿用 STEP 种子 `--fuse`（SW 中为曲面实体） |
| `export_line_from_unitcell_seed.py` | 由单胞种子平移生成 N-cell 线阵列 |
| `export_zslab_layer_from_column.py` | 4×4 z 层化合物 / 行融合 |
| `run_hu_bai_bcc_unitcell_array_step_fuse.py` | 单胞 OCC 阵列融合 STEP（legacy；BCC 推荐 `run_hu_bai_array_auto_fuse.py`） |
| `run_hu_bai_array_auto_fuse.py` | BCC OCC 自动阵列融合（**暂停/门控禁用**；问题见 `docs/CAD融合路线与已知问题.md`） |
| `docs/单胞融合策略.md` | **单胞 paper box-cut 各 Q 融合策略**（Q=1：OCP 单胞 ✅，4×4×4 进行中） |
| `docs/CAD融合路线与已知问题.md` | CAD 融合路线、BCC OCC 已知问题与 SW 步进说明 |
| `export_unitcell_paper_box_cut.py` | **paper_box 单胞 STEP**（Q=0/0.5/1/1.5） |
| `export_single_strut_paper_box_cut.py` | Q=1 单杆 1/8 octant 切 QA |
| `run_hu_bai_paper_box_4x4x4_array_fuse.py` | **paper_box 4×4×4** gmsh 分层阵列（Q=1 尚未验收） |
| `run_hu_bai_bcc_layered_step_fuse.py` | z 层分层融合（4×4×4 备选，较慢） |
| `run_hu_bai_sfbls_step_fuse.py` | 一次性 monolithic fuse（≤3×3×3） |
| `run_hu_bai_bcc_sw_export.py` | STL / STEP / X_T 导出 |
| `run_hu_bai_bcc_solid_cad_export.py` | STEP → gmsh 网格 → Explicit INP |
| `run_hu_bai_bcc_solid_cad_cae_tet_export.py` | STEP → **Abaqus/CAE C3D4** 网格 → Explicit INP（`paper_box` + STORE OFFSETS） |
| `linux/run_paperbox_cae_tet_pipeline.sh` | 服务器：`paper_box` CAE 划分 + export + 提交（`--Q 0` / `0.5`） |
| `watch_paperbox_jobs.ps1` | 远程轮询 BCC / SFBLS `paper_box` 算例 `.sta` 进度 |
| `run_hu_bai_bcc_export.py` | B31 梁单元 INP |
| `submit_hu_bai_bcc_solid_cad_compression.ps1` | 实体压缩一键：导出 → 求解 → 曲线 |
| `submit_hu_bai_bcc_compression.ps1` | B31 压缩一键提交 |
| `submit_hu_bai_4x4x4_layered_fast80.ps1` | 4×4×4 分层 STEP + fast80 批量 |
| `run_hu_bai_sfbls_4x4x4_array_pipeline.ps1` | 4×4×4 SFBLS 阵列流水线（OCC 单胞阵列 fuse） |
| `run_sfbls_sw_stepwise_4x4x4_pipeline.ps1` | **4×4×4 已验证 SW 步进路线**（BCC Q=0 / SFBLS；16 体→SW→Z 复制→4 体→SW→fast80） |
| `validate_step_solidworks.py` | STEP 单实体校验（导入 SW 前） |
| `sw_step_to_xt.py` | STEP → Parasolid X_T |
| `extract_stress_strain_from_odb.py` | ODB → 应力–应变 CSV（需 `abaqus python`） |

## 几何参数

论文默认：单胞边长 **L = 20 mm**，杆径 **d = 2 mm**，幅值 **A_f = 2 mm**，块体 **4×4×4**。

命令行可调：

```powershell
py -3 scripts/run_hu_bai_bcc_unitcell_array_step_fuse.py --cells 4 --Q 0 --Af 2
py -3 scripts/run_hu_bai_bcc_unitcell_array_step_fuse.py --cells 3 --Q 1.5   # SFBLS
```

## 输出路径

| 类型 | 路径 |
|------|------|
| 融合 STEP | `output/cad/` |
| INP / manifest | `output/export/{slug}/` |
| Abaqus 作业 | `output/jobs/{slug}/` |
| 应力–应变曲线 | `output/post/{slug}/` |
| 线框预览 | `output/previews/` |
| 当前算例索引 | `output/active_case.json` |

## 命名规则

所有文件名由 **几何变体 + 尺寸 + 阵列规模 + 流程后缀** 拼接。脚本会自动生成，手动引用时请与下表一致。

### 1. 几何变体 `variant`（来自 `HuBaiLatticeGenerator.variant_name`）

| 参数 | 含义 | 命名示例 |
|------|------|----------|
| `Q = 0` | 直杆 BCC | `BCC_AF2Q0` → 小写 `bcc_af2q0` |
| `Q > 0` | 正弦屈曲 SFBLS | `SFBLS_AF2Q1P5`（Q=1.5 写作 `1p5`） |

- `AF`：幅值 A_f [mm]，默认 `2` → `af2`
- `Q`：周期因子；整数直接写（`Q0`），小数点改 `p`（`0.5` → `0p5`）

### 2. CAD 融合 STEP（`output/cad/`）

**单胞 OCC 阵列（推荐）**

```
hu_bai_{variant}_L{L}_{n}x{n}x{n}_solid_array.step
hu_bai_{variant}_L{L}_{n}x{n}x{n}_array_sw_manifest.json
```

示例：`hu_bai_bcc_af2q0_L20_4x4x4_solid_array.step`

**z 层分层融合（备选）**

```
hu_bai_{variant}_L{L}_{n}x{n}x{n}_solid_layered.step
hu_bai_{variant}_L{L}_{n}x{n}x{n}_layered_sw_manifest.json
hu_bai_{variant}_L{L}_{n}x{n}x{n}_solid_layered_layer{k}.step   # 可选中间层
```

**小块 monolithic fuse**

```
hu_bai_{variant}_L20_{n}x{n}x{n}_solid.step
```

**单胞 QA 种子（步进阵列前）**

```
output/cad/_unitcell_check/unitcell_{variant}_fused.step
output/cad/_unitcell_check/manifest.json
```

示例：`unitcell_sfbls_af2q1_fused.step`（Q=1.0，pipe-first，8 杆完整）

| 字段 | 含义 |
|------|------|
| `L{L}` | 单胞边长 [mm]，论文默认 `L20` |
| `{n}x{n}x{n}` | 阵列规模，如 `3x3x3`、`4x4x4` |
| `_solid_array` | 单胞平移阵列后布尔融合 |
| `_solid_layered` | 按 z 层分层融合 |

### 3. Abaqus 实体压缩算例 slug（`export` / `jobs` / `post` 共用文件夹名）

```
hu_bai_{variant}_L{L}_{nx}x{ny}x{nz}_solid_cad_{stroke}[_{suffix}]
```

| 字段 | 含义 | 取值 |
|------|------|------|
| `stroke` | 压缩行程档位 | `f` = full（默认 70% 应变）；`p` = pilot（15% QA） |
| `suffix` | 加速/对比标签 | `fast`、`fast70`、`fast80`、`paper`；或 `--case-suffix` 自定义；历史参可归档为 `_fast80_lr25m12` 等 |

示例：

| slug | 说明 |
|------|------|
| `hu_bai_bcc_af2q0_L20_3x3x3_solid_cad_f_fast` | 3×3×3 BCC，满行程，fast 加速档 |
| `hu_bai_bcc_af2q0_L20_3x3x3_solid_cad_f_fast80` | 同上，dt=5e-4、80% 应变等 fast80 参数 |
| `hu_bai_sfbls_af2q0p5_L20_3x3x3_solid_cad_f_fast80` | SFBLS Q=0.5 |
| `hu_bai_bcc_af2q0_L20_4x4x4_solid_cad_f_fast` | 4×4×4 BCC |

### 4. 每个 slug 目录内的文件

**`output/export/{slug}/`**

| 文件 | 说明 |
|------|------|
| `{slug}.inp` | Abaqus Explicit 压缩 INP |
| `{slug}_meta.json` | 参考面积、高度、加载参数 |
| `case_manifest.json` | 算例全路径索引（submit 脚本读取） |
| `{slug}_nodes.csv` / `{slug}_beams.csv` | 线框节点/杆件（可选） |

**`output/jobs/{slug}/`**

| 文件 | 说明 |
|------|------|
| `{slug}.inp` | 提交用 INP 副本 |
| `{slug}.odb` | 求解结果（Git LFS 跟踪） |

**`output/post/{slug}/`**

| 文件 | 说明 |
|------|------|
| `{slug}_stress_strain.csv` | 工程应力–应变曲线 |
| `{slug}_stress_strain_raw.csv` | 原始采样点 |
| `{slug}_stress_strain.png` | 曲线图 |
| `{slug}_yield.json` | 屈服/极限点分析 |

### 5. 线框预览（`output/previews/`）

```
{variant}_{nx}x{ny}x{nz}_seg{n}_iso.png
```

示例：`bcc_af2q0_1x1x1_seg16_iso.png`

### 6. `active_case.json`

`run_hu_bai_bcc_solid_cad_export.py` 每次导出后写入，记录最近一次算例的 `slug` 及各文件绝对路径。`submit_hu_bai_bcc_solid_cad_compression.ps1` 默认读取此文件；也可用 `-Slug` 指定 `output/export/{slug}/case_manifest.json`。

### 7. 算例数据与 Git

Git 仓库中**只保留 `output/` 目录骨架**（`output/README.md` + 各子目录 `.gitkeep`），不含 STEP、ODB、INP 等大文件。

组员获取已有算例的方式：

1. 克隆本仓库（得到代码 + 空 `output/` 结构）
2. 向维护者索取 `output.zip`（或网盘链接），解压覆盖到项目根目录
3. 或自行运行脚本生成（见「快速开始」）

打包分享示例（维护者本地执行）：

```powershell
Compress-Archive -Path D:\HuBaiLab\output\* -DestinationPath HuBaiLab_output.zip
```

## Web UI（Abaqus 仿真）

浏览器操作 paper_box 压缩全流程，详见 **[`docs/Abaqus_WebUI使用说明.md`](docs/Abaqus_WebUI使用说明.md)**（**§2 启动方式**、页面、工作流、API、排错）。

快速启动（开发模式，完整步骤见文档 §2）：

```powershell
# 终端 1 — API（仓库根 D:\HuBaiLab）
cd D:\HuBaiLab
$env:PYTHONPATH = "D:\HuBaiLab"
python -m uvicorn api.main:app --reload --port 8000

# 终端 2 — 前端
cd D:\HuBaiLab\frontend
npm run dev
```

浏览器打开 **http://localhost:5173**（须同时保持 API 与前端两个进程运行）。

## 更多说明

- **Abaqus Web UI 使用说明**：[`docs/Abaqus_WebUI使用说明.md`](docs/Abaqus_WebUI使用说明.md)
- Abaqus / SolidWorks 导入与排错：[`docs/Abaqus_CAD实体压缩说明.md`](docs/Abaqus_CAD实体压缩说明.md)
- 本仓库为 LatticeLab 的 Hu & Bai 子集；完整晶格工具见主仓库

## 许可

与 LatticeLab 主项目保持一致（请按组内约定添加 LICENSE）。
