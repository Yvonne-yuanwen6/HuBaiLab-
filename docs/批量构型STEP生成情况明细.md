# 批量构型 STEP 生成情况明细

- **同步时间**: `2026-07-28`（本机 `output/cad/批量构型/*_qc.json` + [`单胞核对清单.md`](./单胞核对清单.md)）
- **CAD 结论**: 清单仍 16 案；其中 **`af2q1_deq1p5_k1` 已 VOID**（单胞复检不合格，STEP 已删）；其余曾 `status=ok`。本机单胞目视合格现为 **10**（原 11 剔除细杆案）+ **5** 早期基线未目视
- **服务器路径**: `/media/art/file/XiangLang/Lattice/LWY/HuBaiLab/output/cad/批量构型/`
- **本机路径**: `output/cad/批量构型/`
- **清单案数**: 16（`_batch_index.json`）
- **关联**: [`单胞核对清单.md`](./单胞核对清单.md) · 策略说明 [`批量构型STEP生成说明.md`](./批量构型STEP生成说明.md) §3 · CAE [`批量构型CAE仿真情况明细.md`](./批量构型CAE仿真情况明细.md)

图例：

| 标记 | 含义 |
|------|------|
| **合格** | 单胞目视 OK（清单 `[x]`） |
| **未查** | 清单未勾；多为早期仿真基线案（QC 仍 ok） |
| **noclip** | `ocp_noclip_batch64`（现行主路径） |
| **早期** | 7/15 前后 gmsh / hierarchical / sequential，或整案复用 |

---

## 0. CAE 主对比仿真/网格进度

**完整明细** → [`批量构型CAE仿真情况明细.md`](./批量构型CAE仿真情况明细.md)（以该文档为准；此处不重复维护）。

---

## 1. CAD 总览

| 类别 | 数量 | 说明 |
|------|------|------|
| **QC = ok（可用 STEP）** | **15** | 除 void 案外均有 `_1x1` + `_444`（void 案 STEP 已删） |
| **单胞目视合格** | **10** | 见清单；原 11 剔除 `af2q1_deq1p5_k1` |
| **作废 VOID** | **1** | `af2q1_deq1p5_k1`（2026-07-28；单胞不合格） |
| **早期基线（未目视）** | **5** | `af2q0_deq2_k1` · `af2q0p5_deq2_k1` · `af2q1p5_deq2_k1` · `af2q0_deq2_k2` · `af2q1p5_deq2_k2` |

**策略归类（如何“成”的；void 案仍记历史路径，不可再用）**

| 成功类型 | 案数 | 案 |
|----------|------|-----|
| **`ocp_noclip_batch64`（现行主路径）** | **10 可用** | `af1q1_deq2_k1` · `af2q0_deq2_k1p5` · `af2q0p5_deq2_k1p5` · `af2q1p5_deq2_k1p5` · `af3q1_deq2_k1` · `af2q1_deq2_k1` · `af2q1_deq2_k1p5` · `af2q1_deq2_k2` · `af2q0p5_deq2_k2` · `af2q1_deq2p5_k1` |
| **曾 noclip、现 VOID** | 1 | `af2q1_deq1p5_k1`（细杆；2026-07-28 作废） |
| **gmsh 阵列** | 2 | `af2q0p5_deq2_k1` · `af2q1p5_deq2_k1` |
| **OCP 分层 / 行序（旧梯子）** | 2 | `af2q0_deq2_k2`（hierarchical）· `af2q1p5_deq2_k2`（sequential） |
| **整案复用** | 1 | `af2q0_deq2_k1`（1×1+444 均 skip，ratio≈64.000） |

历史：2026-07-17 曾清 11 合格案服上旧 `*_444.step`；**2026-07-19** 按 face-mate + `noclip_batch64` **全部重生并通过 QC**。

---

## 2. 逐案成功路径（权威 = `*_qc.json` + 清单）

来源：本机 `output/cad/批量构型/{id}/{id}_qc.json` 的 `unitcell_report` / `array_report` / `array_heal`；1×1 方法若 qc 记为 reuse，则以清单备注为准。

### 2.1 现行主路径（11）：face-mate 1×1 → `ocp_noclip_batch64`

| 案 | 1×1 成功方式 | 444 成功方式 | heal | 备注 |
|----|--------------|--------------|------|------|
| `af2q1_deq2_k1` | `ocp_centre_stub_corner_ext`（清单） | `ocp_noclip_batch64` | — | qc 重生 444 时 skip 已有 1×1 |
| `af2q1_deq2_k1p5` | 同上 | `ocp_noclip_batch64` | — | 同上 |
| `af2q1_deq2_k2` | 同上 | `ocp_noclip_batch64` | — | 同上 |
| `af2q1_deq2p5_k1` | face-mate **`ext=2.5`**（清单） | `noclip_batch64` glue=shift f=0.1 | **`ocp_shapefix_gmsh`**（m≈1.000） | 复用 1×1 后补 444+heal；整案≈7 min |
| `af2q1_deq1p5_k1` | ~~`centre_stub_corner_ext` + `ext=1.5`~~ | ~~`noclip_batch64`~~ | — | **VOID 2026-07-28**：单胞复检不合格；本机 STEP / verified / heal STEP 已删；勿入主对比 |
| `af2q0p5_deq2_k2` | **`both_end_extension` + ext=3**（≈24 s） | 同上 | **`tol0.05_fixsmall`**（m≈0.9999） | 椭圆 κ=2；ratio≈63.99 |
| `af1q1_deq2_k1` | 复用已有合格 1×1 | `ocp_noclip_batch64` | — | Af 扫参 |
| `af3q1_deq2_k1` | 同上 | `ocp_noclip_batch64` | — | Af 扫参 |
| `af2q0_deq2_k1p5` | 同上 | `ocp_noclip_batch64` | — | κ=1.5 |
| `af2q0p5_deq2_k1p5` | 同上 | `ocp_noclip_batch64` | — | κ=1.5 |
| `af2q1p5_deq2_k1p5` | （qc 未写 seed；1×1 已有） | `ocp_noclip_batch64` | — | Q=1.5 κ=1.5 |

### 2.2 早期路径（5）：仿真基线 / 旧梯子

| 案 | 1×1 成功方式 | 444 成功方式 | ratio | 备注 |
|----|--------------|--------------|-------|------|
| `af2q0_deq2_k1` | 复用已有 | **整案复用**（skip） | ≈64.000 | Q=0 圆杆；最易案 |
| `af2q0p5_deq2_k1` | **`gmsh_paper_box`** | **`gmsh`** | ≈63.999 | 早期 gmsh 全链路 |
| `af2q1p5_deq2_k1` | **`legacy_copy`** | **`gmsh`** | ≈63.988 | 旧种子拷贝 + gmsh 阵列 |
| `af2q0_deq2_k2` | OCP `sequential_glue_shift` f=0.05 | **`ocp_hierarchical_batch`** | ≈64.002 | 非 noclip |
| `af2q1p5_deq2_k2` | 同上 | **`ocp_sequential`** row/inter | ≈64.000 | 行序融合，非 noclip |

这 5 案 **未**走 7/19 锁定的 `noclip_batch64`；QC 通过，但策略更老。若重生成，默认会改走现行梯子。

### 2.3 目视核对状态

| 案 | 本机结论 | 1x1 | strut | 444 |
|----|----------|-----|-------|-----|
| §2.1 可用 10 案 | **合格** | 有 | 有 | QC ok（noclip） |
| `af2q1_deq1p5_k1` | **VOID** | 已删 | 已删 | 已删 |
| §2.2 共 5 案 | **未查**（清单） | 有（本机已拉回） | 有 | QC ok（早期路径） |

---

## 3. 耗时经验（顺路成功）

| 阶段 | 典型 | 难案 |
|------|------|------|
| 1×1 | 0.5–1 min | face-mate 硬参 ≈30–40 s |
| strut1 | 几秒 | — |
| 444 `noclip_batch64` | **3–5 min** | — |
| heal | ≈2 min | 细杆可达 ≈10 min |
| **整案** | **约 5–10 min** | 细杆 / 重试 **约 15–20 min** |

单档超时：1×1 默认 10 min；444 默认 90 min（超时 kill → 下一档）。细节见 [`批量构型STEP生成说明.md`](./批量构型STEP生成说明.md) §3。

---

## 4. 历史节点

| 时间 | 事项 | 结果 |
|------|------|------|
| 2026-07-15 前后 | 早期 5 案 CAD | gmsh / hierarchical / sequential / 复用 |
| 2026-07-17 | tip-sliver 锁；`centre_stub_corner_ext` 进梯子 | 硬案可融 + tip 平 |
| 2026-07-17 23:11 | 清 11 合格案服上旧 444 | 删 7 / 本无 4；防旧阵列混淆 |
| 2026-07-18～19 | face-mate + **优先 `noclip_batch64`** | 11 案重生 QC 全过 |
| 2026-07-19 | 写盘后 heal 默认开 | 3 案有成功 heal 记录（见 §2.1） |
| 2026-07-24 | 本表按 qc 汇总成功路径 | 16/16 CAD ok；策略归类见 §1 |
| 2026-07-28 | `af2q1_deq1p5_k1` 单胞复检不合格 | **作废**：删 CAD/verified/heal STEP；qc=`void`；仿真标 SKIP/void |

---

## 5. 建议下一步

1. **CAD**：除 void 案外 STEP 仍齐；新参量案默认走说明 §3 锁定梯子（勿改回分层优先）。  
2. **`af2q1_deq1p5_k1`**：需重做 1×1（目视 OK）→ 444 → 再入 verified / CAE；旧 mesh/半截求解作废勿续。  
3. **早期 5 案**：若要与主对比几何口径完全一致，可择机 `FORCE=1` 按 noclip 重生成；否则可继续用现 STEP。  
4. **仿真**：进度与 SKIP 见 [`批量构型CAE仿真情况明细.md`](./批量构型CAE仿真情况明细.md)。

---

*更新本表时：改文首同步时间；成功路径以各案 `*_qc.json` 为准，并与 `单胞核对清单.md` 勾选对齐。*
