# Hu & Bai 点阵：Abaqus CAD 实体压缩说明

实体压缩复现论文 §2.4：从 **已验收 STEP** 出发，划分体网格，写出 Abaqus/Explicit 压缩 INP（刚体压板 + 自接触），求解后提取工程应力–应变曲线。

**当前主路径（2026-07）**

| 环节 | 采用方案 |
|------|----------|
| 几何 | **`paper_box`**：扫掠管 + 虚拟 L³ 盒切割，**无节点球**（对齐 Fig.2.6） |
| STEP 位置 | `output/cad/verified/*_paper_box_array.step` |
| 网格 | **Abaqus/CAE** 四面体 **C3D4**（或收敛研究用 **C3D10M**） |
| 导出脚本 | `scripts/run_hu_bai_bcc_solid_cad_cae_tet_export.py` |
| 服务器一键 | `scripts/linux/run_paperbox_cae_tet_pipeline.sh` |
| 自接触 | **STORE OFFSETS** + **ContactSettle** 两步（`paper_box` 必需） |

Gmsh 体素 / 旧版 `_solid_merged` 路线仍可用，但已不作为 Fig.3.3 主基准，见文末附录。

---

## 1. STEP 几何：当前认哪些文件

### 1.1 仿真只读 `verified/`

所有压缩 export **必须**使用 `output/cad/verified/` 下的 STEP（`src/export/cad_solid_paths.py` 强制校验）。工作目录里生成的中间体须人工验收后再复制进 `verified/`。

### 1.2 文件名与自动查找顺序

阵列 slug 形如 `hu_bai_{variant}_L20_4x4x4`。省略 `--cad` 时，按下列优先级查找：

1. `{slug}_paper_box_array.step` ← **当前默认**
2. `{slug}_solid_array.step`
3. `{slug}_solid_merged.step` / `.STEP`
4. `{slug}_solid_layered.step`
5. `{slug}_solid.step`

**当前四结构 4×4×4 基准 STEP（paper_box）**

| Q | variant | verified 文件名 |
|---|---------|-----------------|
| 0 | `bcc_af2q0` | `hu_bai_bcc_af2q0_L20_4x4x4_paper_box_array.step` |
| 0.5 | `sfbls_af2q0p5` | `hu_bai_sfbls_af2q0p5_L20_4x4x4_paper_box_array.step` |
| 1.0 | `sfbls_af2q1` | `hu_bai_sfbls_af2q1_L20_4x4x4_paper_box_array.step` |
| 1.5 | `sfbls_af2q1p5` | `hu_bai_sfbls_af2q1p5_L20_4x4x4_paper_box_array.step` |

### 1.3 `paper_box` 几何含义

- 8 根扫掠管，RVE 边界为 **L³ 平面切割**（杆端为平面，非球头）。
- **无胞心/节点结点球**；杆在枢纽处几何相交，CAE 网格后自接触过盈显著（见 §3）。
- 单胞导出：`scripts/export_unitcell_paper_box_cut.py` → `output/cad/_unitcell_paper_box_cut/`。
- 4×4×4 阵列：`scripts/run_hu_bai_paper_box_4x4x4_array_fuse.py` 等；Q=1 单胞/阵列特殊路线见 [`单胞融合策略.md`](单胞融合策略.md)、[`CAD融合路线与已知问题.md`](CAD融合路线与已知问题.md)。

### 1.4 与旧几何的区别

| | **`paper_box_array`（当前）** | **`solid_merged` / `solid_array`（历史）** |
|--|------------------------------|-------------------------------------------|
| 节点连接 | 平面切割，无球 | 常含 **9 节点结点球** 或 OCC 硬交 |
| 论文对齐 | Fig.2.6 | 早期 OCC / SW 步进产物 |
| 典型网格器 | Abaqus CAE 四面体 | 曾用 gmsh C3D4 或体素 C3D8R |
| 自接触 t=0 | 需 STORE OFFSETS | 过盈较小，部分算例可直接跑 |

---

## 2. 主流程：CAE 剖分 → 压缩 INP → 求解

### 2.1 分工

```
本机 Windows                          Linux 服务器
────────────────                      ────────────────
改代码 / 准备 verified STEP            CAE 剖分（需许可证）
可选：本机 --mesh-locally 调试         export INP + submit Abaqus
scp 同步代码与 verified/               output/jobs/{slug}/*.sta / *.odb
watch_job_progress.ps1 监控
```

日常服务器操作详见 [`本机开发服务器求解工作流.md`](本机开发服务器求解工作流.md)。

### 2.2 基线一键（BCC Q=0 / SFBLS Q=0.5）

```bash
cd /path/to/HuBaiLab
export PATH="$HOME/APP/abaqus2022/Commands:$PATH"
export PYTHONPATH=.

# BCC Q=0
bash scripts/linux/run_paperbox_cae_tet_pipeline.sh

# SFBLS Q=0.5
bash scripts/linux/run_paperbox_cae_tet_pipeline.sh --Q 0.5
```

**基线 slug**：`hu_bai_{variant}_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox`

| 参数 | 基线值 |
|------|--------|
| 阵列 | 4×4×4，L = 20 mm |
| CAE 全局 seed | **0.6 mm** |
| 网格 preset | `lattice_contact` |
| Virtual Topology | 默认 **开**（`--cae-virtual-topology`） |
| 单元 | C3D4 |
| 工程应变 | **80%**（64 mm / 80 mm 块高） |
| 加载速率 | **5 mm/min**（步长 ≈ 768 s） |
| Explicit dt | 上限 **5×10⁻⁴ s**，`automatic` |
| 材料 | `paper`（Neo-Hooke TPU，仓库默认） |
| 自接触 | `--contact-store-offsets` + `--contact-settle`（15% 步长，s0=0.02） |
| 提交资源 | 48 核 / 256 GB（脚本默认，可按机时调整） |

监视：`scripts/watch_paperbox_jobs.ps1`（本机远程轮询 `.sta`）。

### 2.3 参数变体（网格收敛、材料对比、续算）

统一入口：`scripts/linux/run_paperbox_variant.sh`。

**Fig.3.3 网格收敛示例**（Q=0.5，C3D10M，杆向 4 单元/直径）：

```bash
bash scripts/linux/run_paperbox_q05_c10m_s05r4_el_s78.sh
# 等价于 variant 脚本 + --short-slug q05_c10m_s05r4_el_s78
```

| 项 | 值 |
|----|-----|
| CAD | `…_paper_box_array.step` |
| seed | 0.5 mm |
| quality | `lattice_curve`（强制 d/N 杆边加密，见 [`网格收敛性研究.md`](网格收敛性研究.md)） |
| 单元 | C3D10M |
| 材料 | `elastic`（隔离网格影响） |
| 应变 | 78% |

**本机直接 export（服务器剖分）**：

```powershell
cd D:\HuBaiLab
$env:PYTHONPATH = (Get-Location).Path

py -3 scripts/run_hu_bai_bcc_solid_cad_cae_tet_export.py `
  --cells 4 --Q 0.5 `
  --cad output\cad\verified\hu_bai_sfbls_af2q0p5_L20_4x4x4_paper_box_array.step `
  --cae-seed 0.6 --cae-mesh-quality lattice_contact `
  --strain 0.80 --load-rate-mm-min 5 `
  --contact-store-offsets --contact-settle `
  --case-suffix cae_tet0p6mm80_5mmin_paperbox `
  --mesh-locally
```

续算（s45→75% 等）见 [`Abaqus显式续算.md`](Abaqus显式续算.md)。

### 2.4 CAE 网格 preset 速查

| preset | 用途 |
|--------|------|
| `lattice_contact` | 默认；杆径方向约 3 单元/直径（seed=0.6, d=2 mm） |
| `lattice_curve` | 曲线杆强制按 **d/N** 加密；Fig.3.3 收敛主用 |
| `paper` | 更保守的全局尺寸过渡 |
| `fast` | 粗网格快测 |

`--cae-rods-per-diameter 4` 与 `lattice_curve` 联用可目标 **4 单元/杆径**。剖分日志与单元数写入 `{slug}_cae_mesh_manifest.json`。

---

## 3. `paper_box` 自接触：为何必须 STORE OFFSETS

无节点球时，枢纽处初始自接触过盈可达 **~10³ 对 / 0.2–0.3 mm**，Explicit 默认在 **increment 0** 做无应变 nodal adjustment 会推畸变单元，表现为 autodt 暴跌、job 秒停。

**当前有效方案**（`src/export/abaqus_compression.py` 写出）：

1. **`*Contact Controls … STORE OFFSETS`**：记录初始过盈偏移，避免 t=0 硬推节点。
2. **Step `ContactSettle`**（默认 15%×总步长）：零位移 + 软自接触（s0=0.02，μ=0）。
3. **Step `Compression`**：硬接触（μ=0.1）+ 顶板位移加载。

仅调网格密度、Virtual Topology 或软间隙 **不能**单独替代 STORE OFFSETS。板–点阵仍为 **刚体压板 + `pair` 硬接触**（非运动学耦合）。

---

## 4. INP 边界条件与材料（各路线共用）

| 项 | 取值 |
|----|------|
| 求解器 | Abaqus **Explicit** |
| 顶/底板 | 刚体；`LATTICE_TOP`↔`PLATE_BOT`、`LATTICE_BOTTOM`↔`PLATE_FIXED_TOP` |
| 点阵自接触 | `ALL EXTERIOR`（可用 `--no-lattice-self-contact` 关闭以省内存） |
| 摩擦 | μ = **0.1** |
| 材料（论文档） | TPU：E = 25 MPa，ν = 0.47，ρ = 1135 kg/m³；本构默认 Neo-Hooke |
| 板尺寸 | XY 比点阵大 `plate_margin`（默认 0.1L）；`plate_embed` 控制贴合 |
| 质量缩放 | 基线 pipeline 常用 automatic；变体可 `--no-mass-scaling` |

**算例 slug**（`output/export/`、`output/jobs/`、`output/post/` 同名）：

```
hu_bai_{variant}_L{L}_{nx}x{ny}x{nz}_solid_cad_f[_{suffix}]
```

`case_manifest.json` 记录 STEP 路径、网格来源、加载与接触开关；`submit_hu_bai_bcc_solid_cad_compression.ps1` 或 `scripts/linux/submit_job.sh` 读取后提交。

**后处理**：

```bash
abaqus python scripts/extract_stress_strain_from_odb.py --slug SLUG
```

曲线输出至 `output/post/{slug}/`。

---

## 5. 常见问题

### 5.1 `No verified CAD STEP`

将验收后的 STEP 放入 `output/cad/verified/`，文件名与 §1.2 一致；或显式 `--cad output/cad/verified/….step`（路径必须在 `verified/` 下）。

### 5.2 CAE 剖分失败

- 确认 STEP 在 SW 中为 **单实体、单窗口**（`validate_step_solidworks.py`）。
- 试 `--heal-step-before-cae` 或 `--heal-step-on-mesh-fail`（Gmsh OCC heal 后再剖分）。
- Q=1 阵列 STEP 若未验收，勿直接用于生产算例。

### 5.3 increment 0 失败（paper_box）

检查 INP 是否含 **STORE OFFSETS** 与 **ContactSettle** 步；对照 `run_paperbox_cae_tet_pipeline.sh` 参数。

### 5.4 SolidWorks「窗口资源极低」

GDI 句柄耗尽：关闭多余零件窗口，或 **绕过 SW** 直接用 verified STEP 进 CAE/Abaqus。不要同时打开多个大阵列 STEP 对比。

### 5.5 Parasolid `.x_t` 无法导入 Abaqus

仅当 SW 中为真实 **MANIFOLD_SOLID_BREP** 且 Parasolid 版本 ≤ Abaqus 内核时才可用。网格化后的 `MESH4` / `GUISE=transmit_mesh` 小文件无效。**推荐始终用 STEP**，经 `verified/` 进流水线。

---

## 附录：历史路线与已尝试方案（简记）

以下为开发过程中用过或评估过的路径，**非当前主基准**；细节见 README 成功案例表与各专题文档。

| 路线 | 说明 |
|------|------|
| **`_solid_merged.STEP` + SW 步进** | `run_sfbls_sw_stepwise_4x4x4_pipeline.ps1`：16 体→SW→Z 复制→4 体→SW；含结点球，曾跑通 fast80 gmsh，几何与 Fig.2.6 不一致 |
| **`_solid_array.step` OCC 融合** | `run_hu_bai_bcc_unitcell_array_step_fuse.py`；BCC 3×3/4×4 fast80 有成功记录，4×4 OCC 自动融合已暂停（见 CAD 融合路线文档） |
| **Gmsh C3D4 主路径** | `run_hu_bai_bcc_solid_cad_export.py --mesh-method tet`；`fast`（45%/1.2 mm/10 mm/min）、`fast80`（80%/0.8 mm）档位；paper_box 上不如 CAE 可控 |
| **体素 C3D8R** | 同上脚本 `--mesh-method voxel`；轴对齐六面体，曾用于四结构 75% 对比算例 |
| **`coupling_nodes` 顶板** | 顶面节点运动学同步，CAE 里板悬空；仅调试，`contact_mode=pair` 为正式方案 |
| **B31 梁单元 INP** | `run_hu_bai_bcc_export.py`；无线框实体网格，快速对照曲线 |
| **CAE 六面体 C3D8R 试点** | `run_abaqus_cae_hex_mesh_pilot.ps1`；对 `_solid_merged` 批处理 `openStep` 曾得 `Parts: []`，未接入压缩流水线 |
| **结点球 + pipe-first 单胞** | `export_unitcell_seed_check.py`；SW 单胞 QA 用，非 paper_box |
| **Q=1 OCP GlueShift 单胞** | 已验收 vol=1；4×4×4 阵列仍在攻关 |
| **无效的自接触缓解尝试** | 仅 `SCALE FACTOR` 软间隙、仅 ContactSettle、板/自接触 `INTERFERENCE FIT`、只加密网格——paper_box t=0 均不足，最终靠 STORE OFFSETS |
