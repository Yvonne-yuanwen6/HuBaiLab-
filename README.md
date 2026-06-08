# HuBaiLab

重庆大学 Hu & Bai (2024) **BCC / SFBLS** 点阵结构复现工具：几何生成、融合实体 STEP、Abaqus 压缩仿真与应力–应变曲线提取。

从 [LatticeLab](https://github.com/) 主仓库中提取的 **Hu & Bai 专用子集**，供课题组独立克隆使用。

## 功能

| 能力 | 说明 |
|------|------|
| 点阵生成 | BCC (Q=0) 与正弦屈曲杆 SFBLS (Q>0)，单胞 20 mm，杆径 2 mm |
| 融合 STEP | 单胞 OCC 阵列（**推荐**）、z 层分层、小块 monolithic fuse |
| SolidWorks | STL 预览、STEP → Parasolid X_T（需 Windows + SolidWorks） |
| Abaqus 实体压缩 | STEP → gmsh 四面体网格 → Explicit INP + 刚体压板 |
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
├── docs/hu_bai_abaqus_cad_import.md # Abaqus / SW 导入详解
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

### 1. 生成 4×4×4 融合 STEP（推荐）

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

## 脚本索引

| 脚本 | 用途 |
|------|------|
| `run_hu_bai_bcc_unitcell_array_step_fuse.py` | **推荐** 单胞 OCC 阵列融合 STEP |
| `run_hu_bai_bcc_layered_step_fuse.py` | z 层分层融合（4×4×4 备选，较慢） |
| `run_hu_bai_sfbls_step_fuse.py` | 一次性 monolithic fuse（≤3×3×3） |
| `run_hu_bai_bcc_sw_export.py` | STL / STEP / X_T 导出 |
| `run_hu_bai_bcc_solid_cad_export.py` | STEP → gmsh 网格 → Explicit INP |
| `run_hu_bai_bcc_export.py` | B31 梁单元 INP |
| `submit_hu_bai_bcc_solid_cad_compression.ps1` | 实体压缩一键：导出 → 求解 → 曲线 |
| `submit_hu_bai_bcc_compression.ps1` | B31 压缩一键提交 |
| `submit_hu_bai_4x4x4_layered_fast80.ps1` | 4×4×4 分层 STEP + fast80 批量 |
| `run_hu_bai_sfbls_4x4x4_array_pipeline.ps1` | 4×4×4 SFBLS 阵列流水线 |
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
| `suffix` | 加速/对比标签 | `fast`、`fast70`、`fast80`、`paper`；或 `--case-suffix` 自定义 |

示例：

| slug | 说明 |
|------|------|
| `hu_bai_bcc_af2q0_L20_3x3x3_solid_cad_f_fast` | 3×3×3 BCC，满行程，fast 加速档 |
| `hu_bai_bcc_af2q0_L20_3x3x3_solid_cad_f_fast80` | 同上，dt=8e-4 等 fast80 参数 |
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

## 更多说明

- Abaqus / SolidWorks 导入与排错：[`docs/hu_bai_abaqus_cad_import.md`](docs/hu_bai_abaqus_cad_import.md)
- 本仓库为 LatticeLab 的 Hu & Bai 子集；完整晶格工具见主仓库

## 许可

与 LatticeLab 主项目保持一致（请按组内约定添加 LICENSE）。
