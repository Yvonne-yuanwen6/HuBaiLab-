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
├── output/                          # 运行结果（git 忽略，本地生成）
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
cd D:\HuBaiLab
py -3 -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
```

## 快速开始

### 1. 生成 4×4×4 融合 STEP（推荐）

```powershell
cd D:\HuBaiLab
$env:PYTHONPATH = (Get-Location).Path

py -3 scripts/run_hu_bai_bcc_unitcell_array_step_fuse.py --cells 4 --Q 0
py -3 scripts/validate_step_solidworks.py output/cad/solidworks/hu_bai/*_array.step
```

输出示例：`output/cad/solidworks/hu_bai/hu_bai_bcc_af2q0_L20_4x4x4_solid_array.step`

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
| 融合 STEP | `output/cad/solidworks/hu_bai/` |
| INP / manifest | `output/export/hu_bai/{slug}/` |
| Abaqus 作业 | `output/abaqus/jobs/hu_bai/{slug}/` |
| 应力–应变曲线 | `output/abaqus/post/hu_bai/{slug}/` |

## 更多说明

- Abaqus / SolidWorks 导入与排错：[`docs/hu_bai_abaqus_cad_import.md`](docs/hu_bai_abaqus_cad_import.md)
- 本仓库为 LatticeLab 的 Hu & Bai 子集；完整晶格工具见主仓库

## 许可

与 LatticeLab 主项目保持一致（请按组内约定添加 LICENSE）。
