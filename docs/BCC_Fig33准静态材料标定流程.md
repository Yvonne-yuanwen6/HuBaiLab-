# BCC Fig.3.3 准静态 / 材料标定流程（可复现）

本文记录 **BCC Q=0、`paper_box`、C3D4** 对齐论文 Fig.3.3 时，在「几何已锁定」之后做的前期分析决策与可重复操作。后续若更换材料曲线、质量缩放策略或目标实验数据，按同一流程走即可。

几何与导出总览见 [`Abaqus_CAD实体压缩说明.md`](Abaqus_CAD实体压缩说明.md)；本文只写 **保真度排查顺序** 与 **当前基线**。

---

## 0. 锁定前提（不要先动这些）

| 项 | 锁定值 | 说明 |
|----|--------|------|
| 几何 | `output/cad/verified/hu_bai_bcc_af2q0_L20_4x4x4_paper_box_array.step` | 已验收；几何问题单独走 CAD 流程 |
| 单元 | **C3D4**（论文同型） | 原文用 C3D4；网格类型不是第一嫌疑 |
| 网格 | CAE seed **0.6 mm**，`lattice_contact`，复用 baseline mesh INP | ~94 万单元；勿与材料混改 |
| 接触 | **STORE OFFSETS** + **ContactSettle** + 点阵自接触，μ=0.1 | `paper_box` 必需 |
| 加载 | 5 mm/min，刚体压板 | 冒烟 ε=0.12；全行程 ε=0.80 |
| 实验参考 | `data/hu_bai_fig33_experiment_traced.json` → series `bcc` | 叠图 / RMSE 基准 |

**原则：一次只动一个旋钮。** 先准静态能量，再本构，再材料标定；不要同时改网格与材料。

---

## 1. 排查顺序（决策树）

```text
几何 OK？
  └─ 否 → CAD / verified 流程（本文不覆盖）
  └─ 是 → 冒烟 ε=0.12（固定网格+接触）
           ├─ KE/IE（去前 5%）≥ 5%  → 先修质量缩放 / 显式步长（§2）
           ├─ 曲线相对 Fig.3.3 系统性偏刚/偏软
           │     ├─ Neo-Hooke vs Marlow（§3）→ 选更贴近 Fig.2.5 的本构
           │     └─ 仍整体偏刚/偏软 → Fig.2.5 应力缩放标定（§4）
           └─ 早期贴合 → 全行程 ε=0.80，看平台与密实化（§5）
```

已否定、勿再优先尝试：

| 尝试 | 结论 |
|------|------|
| Neo-Hooke + 强质量缩放（×50 / BELOW MIN dt=5e-4） | 早期曲线可「看起来像」，但 KE/IE 常失败（~20%+） |
| 均匀质量缩放 ×10（无 BELOW MIN） | 过慢或失真，不作为主路径 |
| 无质量缩放 + 固定小 dt | 过慢 / 接触不稳，仅作对照 |
| 先换 C3D10M / 加密网格「救曲线」 | 原文 C3D4 可复现；网格不是第一刀 |

---

## 2. 准静态：质量缩放怎么选

目标：**接触稳定 + 墙钟可接受 + KE/IE 合格**。

推荐（当前胜出）：

```text
*Fixed Mass Scaling, type=BELOW MIN, dt=0.0001   （不设 factor 上限）
Explicit: automatic，目标 dt=1e-4
```

仓库 CLI：

```bash
--mass-scaling-mode below_min --mass-scaling-dt 0.0001 \
--explicit-dt 0.0001 --explicit-dt-mode automatic
```

验收（冒烟或全行程 post 后）：

1. 提取能量：`abq python scripts/extract_odb_energy_py2.py <odb> <energy.csv>`
2. 评估：`python3 scripts/evaluate_bcc_qs_material_probe.py --mode smoke --slugs <slug...>`
3. **KE/IE（去掉历史前 5%）&lt; 5%** → 准静态通过

对照命名（`scripts/linux/run_bcc_qs_material_probe.sh`）：

| id | 含义 |
|----|------|
| `*_msb1e4` | BELOW MIN → dt=1e-4（推荐） |
| `*_ms50` | 旧 BELOW MIN 大 dt + factor×50（快但不 QS） |
| `*_msu10` | 均匀 ×10 |
| `*_noms` | 无质量缩放 |

---

## 3. 本构：Neo-Hooke vs Marlow（Fig.2.5）

| 模型 | 数据源 | 相对 Fig.3.3 BCC（早期） |
|------|--------|-------------------------|
| Neo-Hooke（E=25 MPa 等） | 仓库常量 | 偏硬、噪声大 |
| **Marlow** | `data/hu_bai_tpu_fig25_tensile_traced.json` | 形状明显更好，仍可能整体偏刚 |

导出：

```bash
--material-model marlow
# 可选：--tpu-fig25-json path/to/curve.json
```

单胞/单元素材料探针（换本构前可先筛）：`scripts/export_tpu_uniaxial_material_probe.py`。

---

## 4. 材料标定：Fig.2.5 工程应力缩放

当 **Marlow + msb1e4** 已 QS 合格，但点阵 σ–ε 相对 Fig.3.3 **近似成比例偏刚** 时，对 Fig.2.5 单轴曲线做 **应力缩放**（应变不变）：

```bash
--material-model marlow --tpu-stress-scale 0.77
```

实现：`src/material/tpu_fig25.py` → `load_tpu_fig25_uniaxial(..., stress_scale=...)`；export 写入 manifest `material.fig25_stress_scale`。

### 4.1 如何估 scale（可复现）

1. 跑一版 **scale=1.0** 的冒烟（ε≤0.12），得到 `*_stress_strain.csv`。
2. 在 ε∈[0.02, 0.12] 上，对实验曲线做最小二乘：
   \[
   s^\* = \arg\min_s \|\, s\cdot\sigma_\mathrm{sim}(\varepsilon) - \sigma_\mathrm{exp}(\varepsilon)\,\|
   \]
3. BCC×Fig.3.3 当前拟合：**s\*≈0.77**（RMSE 从 ~2.5×10⁻⁴ 降到 ~5×10⁻⁵ MPa）。
4. 用 `s*` 再跑冒烟 → 验 KE/IE + 叠图 → 再开全行程。

换实验数据或换 Fig.2.5 描点后：**重做 §4.1，不要沿用 0.77。**

### 4.2 冒烟验收（材料）

| 指标 | 期望（BCC 当前经验） |
|------|----------------------|
| KE/IE after 5% | &lt; 5% |
| ε=0.05 / 0.10 应力比 sim/exp | ≈ 0.95–1.10 |
| early RMSE（ε 0.02–0.12） | 明显低于 scale=1 |

叠图脚本可参考：`scripts/plot_bcc_qs_msb1e4_overlay.py`；scale 变体可仿其写 live CSV 对比。

---

## 5. 全行程与中途判读

1. 冒烟通过后再开 ε=0.80（同网格、同接触、同 scale、同 msb1e4）。
2. 运行中可用只读提取（不必停作业）：

```bash
abq python scripts/extract_live_odb_history_py2.py \
  output/jobs/<slug>/<slug>.odb \
  output/export/<slug>/<slug>_meta.json \
  output/post/<slug>/<slug>_stress_strain_partial.csv
```

3. 中途叠 Fig.3.3：早期应与冒烟重合；中后期允许 ~10–15% 偏刚，但若形状（平台 / 密实化抬头）明显偏离，再改材料策略，而不是先改网格。
4. 完成后提取正式曲线 + 能量，全轴对比实验密实化段。

---

## 6. 作业命名：短 slug（必读）

Abaqus/Explicit 对**过长 job 名**会在 `OpenODBFile` 阶段找截断的 `*.od.`，报：

```text
exception 10: rfm_FileNoSuchFile
```

经验阈值：描述性长 slug ~96 字符失败；**短 slug（如 `bcc_marlow_ss077_sm12`）正常**。

提交时用：

```bash
bash scripts/linux/run_paperbox_variant.sh \
  --Q 0 \
  --variant-suffix qs_sm12_marlow_msb1e4_ss077 \
  --short-slug bcc_marlow_ss077_sm12 \
  --cae-mesh-inp output/export/.../hu_bai_bcc_..._cae_mesh.inp \
  ...
```

`--short-slug` 时务必显式传入 `--cae-mesh-inp` 复用 baseline，避免误触发重划网格。

---

## 7. 一键脚本（服务器）

在仓库根目录（Linux 服务器），`PATH` 含 Abaqus Commands。

**材料 / QS 探针（多变体）：**

```bash
bash scripts/linux/run_bcc_qs_material_probe.sh --smoke --only marlow_msb1e4 --submit --cpus 32
bash scripts/linux/run_bcc_qs_material_probe.sh --smoke --post-only --only marlow_msb1e4
```

**当前标定基线（Marlow×0.77 + msb1e4）：**

```bash
# 冒烟 ε=0.12
BCC_QS_PROBE_CPUS=32 bash scripts/linux/launch_bcc_qs_marlow_ss077_smoke.sh

# 全行程 ε=0.80
BCC_QS_PROBE_CPUS=32 bash scripts/linux/launch_bcc_qs_marlow_ss077_full.sh
```

| 用途 | 短 slug | 日志 |
|------|---------|------|
| 冒烟 | `bcc_marlow_ss077_sm12` | `output/logs/bcc_qs_material_probe_ss077_smoke.log` |
| 全行程 | `bcc_marlow_ss077_s80` | `output/logs/bcc_qs_material_probe_ss077_full.log` / `*_pipeline.log` |

本机同步代码：`powershell -File scripts/sync_to_server.ps1`（见 [`本机开发服务器求解工作流.md`](本机开发服务器求解工作流.md)）。

---

## 8. 换材料 / 换实验数据时怎么复现

| 变更 | 动作 |
|------|------|
| 新 Fig.2.5 / 单轴 JSON | 放到 `data/`，`--tpu-fig25-json`；**scale 清零重估（§4.1）** |
| 新 Fig.3.3 描点 | 更新 `data/hu_bai_fig33_experiment_traced.json`；重估 scale、重叠图 |
| 只换本构族（Ogden / Poly…） | 先单元素探针 → 冒烟 msb1e4 → 再决定是否还要 stress-scale |
| 换点阵构型（Q≠0） | **不要直接抄 0.77**；同一流程从 scale=1 冒烟重拟合 |
| 怀疑网格 | 仅在材料已贴合、密实化仍系统性偏差时，再开 C3D10M / seed 对照 |

推荐目录约定：

```text
output/export/<slug>/          # INP + meta（含 fig25_stress_scale）
output/jobs/<slug>/            # ODB / STA
output/post/<slug>/            # stress_strain*.csv, energy.csv
output/reports/mesh_convergence/   # 叠图 PNG / 评估 JSON
```

---

## 9. 当前基线快照（2026-07）

| 项 | 值 |
|----|-----|
| 几何 / 网格 | BCC Q=0 `paper_box`，C3D4 seed 0.6，复用 baseline |
| 接触 / 加载 | STORE OFFSETS + ContactSettle，5 mm/min |
| 材料 | Marlow，Fig.2.5，**stress_scale=0.77** |
| 质量缩放 | BELOW MIN dt=1e-4（msb1e4） |
| 冒烟 | `bcc_marlow_ss077_sm12`：KE/IE≈1%，early 接近 Fig.3.3 |
| 全行程 | `bcc_marlow_ss077_s80`：中期 ε~0.5 约 1.1× 实验，形状可用，密实化待跑完确认 |
| 报告图 | `output/reports/mesh_convergence/bcc_qs_marlow_ss077_vs_fig33.png` 等 |

---

## 10. 相关代码入口

| 文件 | 作用 |
|------|------|
| `scripts/run_hu_bai_bcc_solid_cad_cae_tet_export.py` | `--material-model` / `--tpu-stress-scale` / `--mass-scaling-*` |
| `scripts/linux/run_paperbox_variant.sh` | 变体导出 + 提交；`--short-slug` |
| `scripts/linux/run_bcc_qs_material_probe.sh` | QS/材料多变体探针 |
| `scripts/linux/launch_bcc_qs_marlow_ss077_*.sh` | ×0.77 冒烟 / 全行程 |
| `scripts/evaluate_bcc_qs_material_probe.py` | KE/IE + early RMSE |
| `scripts/extract_live_odb_history_py2.py` | 运行中只读提曲线 |
| `src/material/tpu_fig25.py` | Fig.2.5 加载与 stress_scale |
| `src/export/export_inp.py` | Marlow `*Hyperelastic` + 单轴试验数据写出 |
