# Hu & Bai COMSOL — 隔振 / 动力学分析（§2.4.3）

COMSOL Multiphysics 5.6，结构力学固体力学场。用于点阵**隔振**，不做 Abaqus 准静态压缩（§2.4.1 / Fig.3.3）。

| 工具 | 用途 |
|------|------|
| **Abaqus** | 压缩 σ–ε、能量吸收 Fig.3.3 / 3.11 / 3.13 |
| **COMSOL** | 模态频率、谐响应、**传递率** |

## §2.4.3 默认建模（`HuBaiComsolSettings`）

| 组件 | 材料 | 网格（Fig. 2.8 分层，默认） |
|------|------|------|
| 点阵隔振结构 | TPU：**Fig.2.5 拉伸曲线 → Marlow 超弹性**；ρ=1135 kg/m³（§2.3.2） | **0.6 mm**（分域 FreeTet 第二步） |
| 振动台（方块） | **AISI 4340 钢**（COMSOL UNS G43400）：E=205 GPa, ν=0.29, ρ=7850 | **~40 mm** 体部；顶面脚印区 **~8 mm** + **hgrad 1.5–1.7** 渐变（40 mm 深） |
| 薄铝合金片（输出端） | **铝合金**（COMSOL 内置）：E=69 GPa, ν=0.33, ρ=2700 | **≤8 mm**（0.5 mm 薄板至少 2 层） |

**剖分策略**（`mph_builder._build_fig28_layered_mesh`）：

1. **Step 1**：只剖振动台 + 顶板（粗网格 + 顶面 Box 脚印区局部细化）
2. **Step 2**：再剖点阵域（细网格 0.6 mm）
3. 避免一次性剖全装配体，否则细网格会通过 Identity pair 渗入 400 mm 振动台

可选：`--physics-controlled-mesh` 改用 COMSOL `hauto` 预设（lattice=4 细化，fixture=5 常规）。

- 几何：振动台 400×400×400 mm + 点阵 + 顶板（Fig. 2.8）
- 激励：**振动台顶面**指定加速度 **0.98 m/s²**（频域正弦；COMSOL 5.6 用 `Displacement2`，u = A/ω²）
- 本征：振动台底面固定
- 接触：Form Assembly **Identity pairs**（自动粘结界面；非 Bonded Contact 对）
- 传递率探针：振动台顶面 → 铝合金板顶面

> **坐标说明**：论文 §2.4.3 为 Y 轴激励。本仓库 verified STEP 为 **Z 向堆叠**时，请加 `--excitation-axis z`。

简化模型（仅点阵）：`--no-fig28`

## 依赖

```bash
pip install mph "jpype1<1.6"
```

## 用法

```bash
cd /path/to/HuBaiLab
export PYTHONPATH=.

# §2.4.3 默认：振动台+压板+点阵，先只建模型
bash scripts/linux/run_comsol_hu_bai.sh --Q 0 --cells 1 --nz 1 --eigen-only --build-only \
  --cad output/cad/verified/hu_bai_bcc_af0q0_L20_1x1x1_uc_circ.step

# Z 向 STEP + 本征求解
bash scripts/linux/run_comsol_hu_bai.sh --Q 0 --cells 4 --eigen-only \
  --excitation-axis z --background --np 8

# 仅点阵（与早期试点相同）
bash scripts/linux/run_comsol_hu_bai.sh --Q 0 --cells 4 --no-fig28 --eigen-only --np 8
```

## 输出

| 文件 | 说明 |
|------|------|
| `output/comsol_jobs/{slug}/{slug}.mph` | 模型 |
| `output/comsol_jobs/{slug}/{slug}_solved.mph` | 求解结果 |
| `output/comsol_jobs/{slug}/{slug}_eigenfrequencies.csv` | 模态频率 |
| `output/comsol_jobs/{slug}/{slug}_transmissibility.csv` | 传递率 |

```bash
python3 scripts/comsol_extract_isolation.py output/comsol_jobs/{slug}/{slug}_solved.mph
```

## Table 3.3 后处理（本征 vs 谐响应共振峰）

论文 Table 3.3 报的是 **固有频率 f_n**，§2.4.3 只写了 **频域谐响应**。后处理会同时对比两种来源：

| 来源 | 含义 |
|------|------|
| **eigen** | 本征分析前三阶物理模态（mEff 排序） |
| **harmonic** | 传递率 T(f) 局部峰值 → **共振频率** |

```bash
# 单个频响 job（需 *_transmissibility.csv）
python3 scripts/comsol_postprocess_thesis.py output/comsol_jobs/{slug}/

# 并排对比 eigen job + freq job vs 论文 Table 3.3
python3 scripts/compare_table33_vs_paper.py --key bcc
python3 scripts/compare_table33_vs_paper.py --batch   # 四个 Fig.3.21 算例
```

输出：

| 文件 | 说明 |
|------|------|
| `{slug}_table33_compare.json` / `.csv` | 单 job：本征 + 谐响应峰值 vs 论文 |
| `fig321_composite/table33_eigen_vs_harmonic_vs_paper.json` | 批量对比 |
| `{slug}_fig322_transmissibility.png` | 传递率曲线（标注共振峰 + 论文 fn 虚线） |

## 代码入口

- `src/comsol/hu_bai_settings.py` — §2.4.3 参数常量
- `src/comsol/mph_builder.py` — MPh 建模
- `scripts/comsol_run_hu_bai.py` — CLI

频率扫频范围、阻尼等若原文后续章节有专门取值，请在 settings 中更新（当前为仓库默认 10–2000 Hz）。

---

## 附录：COMSOL 设置与结果核对清单

依据 Hu & Bai (2024) 论文 **§2.4.3 / §3.4**，用于逐项核对 COMSOL 模型设置与仿真结果是否与论文一致。括号内标注与本仓库 `HuBaiComsolSettings` 的常见差异。

**适用范围**：点阵隔振振动/隔振分析（**非** Abaqus 准静态压缩）  
**软件**：COMSOL Multiphysics **5.6**，固体力学

### A. 仿真任务范围

| ☐ | 核对项 | 论文要求 | 备注 |
|---|--------|----------|------|
| A1 | 求解器分工 | 隔振/振动 → **COMSOL**；压缩/吸能 → **Abaqus** | 勿混用 |
| A2 | 研究类型 | ① 频域谐响应（VLD）② 模态/本征频率 | Fig.3.20 + 表3.3 + Fig.3.21 |
| A3 | 算例构型 | BCC(Q=0)、AF2Q05、AF2Q1、AF2Q15 | 4×4×4，L=20 mm，杆径 2 mm |
| A4 | 参数化扫参 | 杆径变化、幅值因子 Af 变化 | Fig.3.22 |

### B. 几何与装配（Fig. 2.8）

| ☐ | 核对项 | 论文要求 | 本仓库默认 |
|---|--------|----------|------------|
| B1 | 整体布局 | 振动台（输入）— 点阵 — 铝合金片（输出） | `include_shaker_fixture=True` |
| B2 | 点阵尺寸 | 4×4×4 单胞，单胞边长 **20 mm** | `nx=ny=nz=4`, `cell_size_mm=20` |
| B3 | 杆径 | **2 mm** 圆截面 | `rod_diameter_mm=2.0` |
| B4 | 周期因子 Q | 0 / 0.5 / 1.0 / 1.5 | `Q` 对应四构型 |
| B5 | 幅值因子 Af | **2 mm**（命名 AF2Q*） | `amplitude_mm=2.0` |
| B6 | 顶板厚度 | **0.5 mm** 薄铝合金片 | `top_plate_thickness_mm=0.5` |
| B7 | 振动台材料 | AISI 4340 钢（方块） | E=205 GPa, ν=0.29, ρ=7850 |
| B8 | 顶板材料 | COMSOL 内置铝合金 | E=69 GPa, ν=0.33, ρ=2700 |
| B9 | 负载（VLD 主对比） | **300 g** 加在输出端上方 | `top_payload_mass_kg=0.3` |
| B10 | 负载扫参（实验） | 0 / 100 / 300 / 500 g | 需手动切换 payload |

### C. 材料参数（TPU 点阵）

| ☐ | 核对项 | 论文要求 | 本仓库默认 |
|---|--------|----------|------------|
| C1 | 密度 ρ | 实测 TPU：**1.135 g/cm³**（1135 kg/m³） | `density_kg_m3=1135` |
| C2 | 弹性模量 E | 拉伸试验线性段：**25 MPa** | 线性参考 25 MPa；默认 **Marlow 超弹性**（Fig.2.5 曲线） |
| C3 | 泊松比 ν | **0.47** | `poisson=0.47` |
| C4 | 本构模型 | 论文 §2.4.3 写线性 E=25 MPa | 仓库默认 Marlow；对齐 Table 3.3 时可改用 `linear_elastic` |

> **关键差异**：论文用线性弹性；仓库默认 Marlow。若严格对齐论文 Table 3.3，建议同时跑一版 `lattice_material_model=linear_elastic` 做对照。

### D. 边界条件与激励

| ☐ | 核对项 | 论文要求 | 本仓库默认 |
|---|--------|----------|------------|
| D1 | 物理场 | **固体力学** | Solid Mechanics |
| D2 | 激励类型 | **指定加速度**（正弦） | `excitation_type=acceleration` |
| D3 | 激励幅值 | **0.98 m/s²** | `base_acceleration_m_s2=0.98` |
| D4 | 激励方向 | 论文：**Y 轴** | STEP 常为 **Z 轴**（`--excitation-axis z`） |
| D5 | 激励施加位置 | 振动台顶面（输入端） | PrescribedAcceleration / Displacement2 等效 |
| D6 | 固定约束 | 振动台底面固定（模态分析） | 本征研究底面 Fixed |
| D7 | 界面连接 | 各部件粘结/装配 | Form Assembly + Identity pairs |
| D8 | 探针位置 | 输入：振动台；输出：铝合金片顶面 | base → top 传递率探针 |

> **坐标核对**：论文 Y 向激励 vs 仓库 Z 向堆叠 STEP——确认轴向映射后再比 VLD/模态。

### E. 网格划分（Fig. 2.8）

| ☐ | 核对项 | 论文要求 | 本仓库默认 |
|---|--------|----------|------------|
| E1 | 点阵网格 | **细化**（physics-controlled Fine） | 分域 FreeTet **hmax=0.6 mm** |
| E2 | 振动台网格 | **常规**（Normal） | hmax≈40 mm + 顶面脚印区 ~8 mm 渐变 |
| E3 | 顶板网格 | **常规** | hmax≤8 mm（0.5 mm 薄板至少 2 层） |
| E4 | 网格质量 | 满足精度与效率 | 检查 skewness / 最小单元 |
| E5 | 分域策略 | 论文未写细节 | 先剖 fixture，再剖 lattice（避免细网格渗入 400 mm 台体） |

### F. 研究步与扫频设置

**F1 模态/本征（Table 3.3 / Fig. 3.21）**

| ☐ | 核对项 | 要求 |
|---|--------|------|
| F1.1 | 提取阶数 | 至少前 **3 阶**固有频率与振型 |
| F1.2 | 对比对象 | 仿真 vs 实验（表 3.3） |
| F1.3 | 接受准则 | 前三阶误差 **≤ 14.4%**（论文报告 0.4%–14.4%） |
| F1.4 | 模态特征 | 1 阶：沿激励向整体拉压；2/3 阶：XY 面内扭曲 |

**F2 频域谐响应（Fig. 3.20 / 3.22）**

| ☐ | 核对项 | 论文实验 | 本仓库默认 |
|---|--------|----------|------------|
| F2.1 | 频率范围 | 实验扫频 **5–2000 Hz** | `freq_min=10`, `freq_max=2000` |
| F2.2 | 扫频速率 | **5 oct/min**（实验） | 频域步进需自行换算/近似 |
| F2.3 | 频率步长 | 论文未给仿真步长 | 默认 **10 Hz** 步进 |
| F2.4 | 负载条件 | 300 g（Fig.3.16 主对比） | `top_payload_mass_kg=0.3` |
| F2.5 | 输出量 | **VLD–频率曲线** | 由传递率 T 换算：VLD=20·log10(T) |

### G. 后处理与评价指标

| ☐ | 核对项 | 公式/定义 |
|---|--------|-----------|
| G1 | 振动水平差 VLD | VLD = 20·log10(A₁/A₂) |
| G2 | 隔振判据 | VLD **< 0 dB** 表示有效隔振 |
| G3 | 共振识别 | VLD 峰值对应一阶共振频率 |
| G4 | 传递率（仓库） | T = a_out / a_in；VLD = 20·log10(T) |
| G5 | 图件对应 | Fig.3.20：仿真 vs 实验 VLD 曲线趋势一致 |

### H. 基准结果 — 表 3.3（前三阶固有频率，Hz）

论文仿真基准值（`src/comsol/table33_reference.py`）：

| 构型 | 论文仿真 f₁ | f₂ | f₃ | 论文实验 f₁ | f₂ | f₃ |
|------|------------|-----|-----|------------|-----|-----|
| BCC | 14.8 | 49.8 | 68.4 | 14.0 | 46.8 | 68.1 |
| AF2Q05 | 15.4 | 53.9 | 94.3 | 18.0 | 53.1 | 90.1 |
| AF2Q1 | 29.1 | 44.4 | 94.2 | 30.0 | 47.6 | 90.9 |
| AF2Q15 | 15.4 | 40.6 | 67.8 | 16.0 | 44.3 | 63.6 |

逐项核对表（每个构型填写「本次本征 (Hz)」与「误差 vs 论文仿真 (%)」）：

| 阶次 | 论文仿真 (Hz) | 本次本征 (Hz) | 误差 (%) | ☐ 通过 |
|------|--------------|--------------|---------|--------|
| 1 | | | | |
| 2 | | | | |
| 3 | | | | |

**通过标准**：与论文**仿真列**误差 ≤ **15%**；趋势一致（如 AF2Q1 的 f₁ 明显高于 BCC/AF2Q15）。

批量对比命令：

```bash
python3 scripts/compare_table33_vs_paper.py --key bcc
python3 scripts/compare_table33_vs_paper.py --batch
```

### I. 隔振性能核对

**I1 300 g 负载 VLD 曲线（Fig. 3.16 / 3.20）**

| ☐ | 核对项 | 论文结论 |
|---|--------|----------|
| I1.1 | SFBLS 低频隔振带 | 宽于 BCC |
| I1.2 | 最优构型（低频） | **AF2Q15** VLD 最高 |
| I1.3 | BCC 失效频段 | ~15 Hz、~272 Hz 附近 VLD>0 |
| I1.4 | 500–2000 Hz | SFBLS 与 BCC 差异较小 |
| I1.5 | 仿真 vs 实验 | 趋势一致；超低频仿真略高于实验 |

**I2 一阶共振频率 vs 负载（表 3.2，实验基准）**

| 构型 | 无负载 | 100g | 300g | 500g | 趋势：负载↑→f₁↓ |
|------|--------|------|------|------|----------------|
| BCC | 35 | 21 | 14 | 11 | ☐ |
| AF2Q05 | 51 | 28 | 18 | 14 | ☐ |
| AF2Q1 | 62 | 42 | 30 | 25 | ☐ |
| AF2Q15 | 39 | 25 | 16 | 14 | ☐ |

| ☐ | 核对项 | 要求 |
|---|--------|------|
| I2.1 | 负载增加 | 一阶共振频率**左移**（降低） |
| I2.2 | AF2Q15 | 除一阶共振外，各负载下**全频隔振**（VLD≤0） |

**I3 参数化隔振（Fig. 3.22，COMSOL 仿真）**

| ☐ | 参数 | 论文趋势 |
|---|------|----------|
| I3.1 | 杆径减小 | VLD 曲线下移，隔振频段扩大；AF2Q1-D05 峰值约 **-110 dB**，96–2000 Hz 有效隔振 |
| I3.2 | 幅值因子减小 | 200–2000 Hz 隔振增强；AF05Q1 峰值约 **-73 dB** |
| I3.3 | 0–200 Hz | Af 增大先增强后减弱；AF15Q1 最优 |

### J. 模态振型核对（Fig. 3.21）

| ☐ | 阶次 | 论文描述 |
|---|------|----------|
| J1 | 第 1 阶 | 沿激励方向整体拉伸/压缩 |
| J2 | 第 2 阶 | XY 平面局部扭曲（四角区域） |
| J3 | 第 3 阶 | 同第 2 阶类扭曲，更高阶 |
| J4 | BCC vs SFBLS | 模态特征相似（同 BCC 拓扑） |

### K. 图件产出核对

| ☐ | 图号 | 内容 | 仓库对应输出 |
|---|------|------|-------------|
| K1 | Fig. 2.8 | 三维模型 + 网格 | `{slug}.mph` |
| K2 | Fig. 3.16 | VLD–f（300g，实验为主） | — |
| K3 | Fig. 3.18 | 不同负载 VLD–f | — |
| K4 | Fig. 3.20 | 仿真 vs 实验 VLD | `{slug}_transmissibility.csv` + 后处理图 |
| K5 | Fig. 3.21 | 前三阶谐响应共振云图（GUI） | `{slug}_solved.mph` 内绘图组 + `{slug}_harmonic_plotgroups.json` |
| K5e | Fig. 3.21 (eigen) | 前三阶本征模态 | `{slug}_eigenfrequencies.csv` |
| K6 | Fig. 3.22 | 杆径/幅值因子参数化 VLD | `{slug}_fig322_transmissibility.png` |

后处理命令：

```bash
# 标准后处理（默认：VLD 曲线 + Table 3.3 对比 + 谐响应云图嵌入 mph）
bash scripts/linux/_remote_postprocess_slug.sh {slug}

# 或分步：
python3 scripts/comsol_extract_isolation.py output/comsol_jobs/{slug}/{slug}_solved.mph
python3 scripts/comsol_postprocess_thesis.py output/comsol_jobs/{slug}/
```

**谐响应云图默认格式**（写入 `*_solved.mph`，COMSOL GUI 直接打开）：

- 频率：传递率 CSV 前三共振峰（T 峰值）
- 几何：仅点阵边界面
- 表达式：相对位移 `sqrt(u²+v²+(w-pb_base)²)`（Z 向激励）
- 色表 AuroraBorealis，变形自动比例，不绘制数据集边框
- 元数据：`{slug}_harmonic_plotgroups.json`（`format_version=2`）

GUI 路径：**结果 → 绘图组 → `fn=XX Hz 相对位移大小` → 绘制**

跳过云图嵌入：`SKIP_FREQ_PLOTGROUPS=1 bash scripts/linux/_remote_postprocess_slug.sh {slug}`

### L. 常见不一致项排查

| ☐ | 若结果偏差大，优先检查 |
|---|------------------------|
| L1 | 激励轴：论文 Y vs 模型 Z |
| L2 | 材料：线性 E=25 MPa vs Marlow 曲线 |
| L3 | 是否包含 300 g 顶载 |
| L4 | 顶板 0.5 mm 是否建模 |
| L5 | 频率范围：5 Hz 起点 vs 10 Hz 起点 |
| L6 | 探针是否在正确界面（台顶 in / 板顶 out） |
| L7 | 网格：点阵是否 0.6 mm 细化 |
| L8 | VLD 符号：20·log10(A_out/A_in)，<0 表示隔振 |

### M. 最终签收

| 项目 | 核对人 | 日期 | 结论 |
|------|--------|------|------|
| 模型设置（B–E） | | | ☐ 通过 / ☐ 待改 |
| 模态频率（H，Table 3.3） | | | ☐ 通过 / ☐ 待改 |
| VLD 曲线（I，Fig. 3.20） | | | ☐ 通过 / ☐ 待改 |
| 参数化趋势（I3，Fig. 3.22） | | | ☐ 通过 / ☐ 待改 |
| 图件齐全（K） | | | ☐ 通过 / ☐ 待改 |
