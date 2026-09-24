# param_batch STEP 生成情况明细

- **同步时间**: `2026-09-22`（CAD：本机 `*_qc.json` + `_444.step`；CAE 进度见关联明细，能量表 ≈09-21）
- **CAD 结论**: 清单 **26** 案均有 1×1 + 444 STEP。L=20 的 **22** 案 QC=ok；L10 中 2 案 qc 仍为 `unitcell_ok_pending_array`（但 444 已在盘）、2 案无 `*_qc.json`。本机单胞目视合格仍为 **11** + **5** 早期基线未目视；扩参 / L10 **未目视**
- **服务器路径（临时）**: `/home/art/HuBaiLab_ssd/output/cad/param_batch/`（旧机械盘 `/media/art/file/...` 已坏停用）
- **本机路径**: `output/cad/param_batch/`
- **清单案数**: 26（`_batch_index.json`）
- **关联**: [`单胞核对清单.md`](./单胞核对清单.md) · 策略说明 [`param_batch_STEP生成说明.md`](./param_batch_STEP生成说明.md) §3 · CAE [`param_batch_CAE仿真情况明细.md`](./param_batch_CAE仿真情况明细.md)

图例：

| 标记 | 含义 |
|------|------|
| **合格** | 单胞目视 OK（清单 `[x]`） |
| **未查** | 清单未勾；多为早期仿真基线案（QC 仍 ok） |
| **noclip** | `ocp_noclip_batch64`（现行主路径） |
| **早期** | 7/15 前后 gmsh / hierarchical / sequential，或整案复用 |

---

## 0. CAE 主对比仿真/网格进度

**完整明细** → [`param_batch_CAE仿真情况明细.md`](./param_batch_CAE仿真情况明细.md)（以该文档为准；此处只给摘要）。

| 类别 | 数量 | 说明 |
|------|------|------|
| L=20 可分析曲线 | **21/22** | 20 complete + 1 near_complete（`af2q1_deq2_k1p5`） |
| HOLD（协议 0 单元） | **1** | 仅 `af2q1_deq2_k2`（09-21 服务器仍无作业） |
| 原 HOLD 已补齐 | 3 | `af2q0p5_deq2_k1p5`（09-13）· `af2q1_deq2p5_k1`（09-09）· `af2q1p5_deq2_k1p5`（09-10） |
| Af 扩参 | 6/6 CAE 完成 | Q=1：`af0p5`/`af1p5`/`af2p5`；Q=1.5：`af0p5`/`af1`/`af1p5`（后者 09-21 抽出 CSV） |
| L=10（seed 0.3） | **3/4** | 缺 `af2q1_deq2_k2_L10` |

---

## 1. CAD 总览

| 类别 | 数量 | 说明 |
|------|------|------|
| **1×1 + 444 STEP 在盘** | **26** | 与 `_batch_index.json` 一致 |
| **L=20 QC = ok** | **22** | 含恢复的细杆案与 Af 扩参 |
| **单胞目视合格** | **11** | 见清单；扩参 / L10 未勾 |
| **作废 VOID** | **0** | 细杆案 2026-08-04 已恢复 |
| **早期基线（未目视）** | **5** | `af2q0_deq2_k1` · `af2q0p5_deq2_k1` · `af2q1p5_deq2_k1` · `af2q0_deq2_k2` · `af2q1p5_deq2_k2` |
| **L10 QC 未收口** | **4** | 2 案 `unitcell_ok_pending_array`（444 已有）；2 案无 qc |

**策略归类（如何“成”的）**

| 成功类型 | 案数 | 案 |
|----------|------|-----|
| **`ocp_noclip_batch64`（现行主路径）** | **11** | `af1q1_deq2_k1` · `af2q0_deq2_k1p5` · `af2q0p5_deq2_k1p5` · `af2q1p5_deq2_k1p5` · `af3q1_deq2_k1` · `af2q1_deq2_k1` · `af2q1_deq2_k1p5` · `af2q1_deq2_k2` · `af2q0p5_deq2_k2` · `af2q1_deq2p5_k1` · **`af2q1_deq1p5_k1`** |
| **gmsh 阵列** | 2 | `af2q0p5_deq2_k1` · `af2q1p5_deq2_k1` |
| **OCP 分层 / 行序（旧梯子）** | 2 | `af2q0_deq2_k2`（hierarchical）· `af2q1p5_deq2_k2`（sequential） |
| **整案复用** | 1 | `af2q0_deq2_k1`（1×1+444 均 skip，ratio≈64.000） |

历史：2026-07-17 曾清 11 合格案服上旧 `*_444.step`；**2026-07-19** 按 face-mate + `noclip_batch64` **全部重生并通过 QC**；**2026-08-04** 细杆案再次用 face-mate+noclip 恢复。

---

## 2. 逐案成功路径（权威 = `*_qc.json` + 清单）

来源：本机 `output/cad/param_batch/{id}/{id}_qc.json` 的 `unitcell_report` / `array_report` / `array_heal`；1×1 方法若 qc 记为 reuse，则以清单备注为准。

### 2.1 现行主路径（12）：face-mate 1×1 → `ocp_noclip_batch64`

| 案 | 1×1 成功方式 | 444 成功方式 | heal | 备注 |
|----|--------------|--------------|------|------|
| `af2q1_deq2_k1` | `ocp_centre_stub_corner_ext`（清单） | `ocp_noclip_batch64` | — | qc 重生 444 时 skip 已有 1×1 |
| `af2p5q1_deq2_k1` | `centre_stub_corner_ext`+ext=2.5 + **STEP hub-ball** | `noclip_batch64` g=shift f=0.1 | **`ocp_shapefix_noglmh`**（m=1.000） | **2026-09-15**：八分体安全首弦 + 条件 hub-ball；ratio=64.000 |
| `af2q1_deq2_k1p5` | 同上 | `ocp_noclip_batch64` | — | 同上 |
| `af2q1_deq2_k2` | 同上 | `ocp_noclip_batch64` | — | 同上 |
| `af2q1_deq2p5_k1` | face-mate **`ext=2.5`**（清单） | `noclip_batch64` glue=shift f=0.1 | **`ocp_shapefix_gmsh`**（m≈1.000） | 复用 1×1 后补 444+heal；整案≈7 min |
| `af2q1_deq1p5_k1` | face-mate **`centre_stub_corner_ext` + `ext=1.5`** | `noclip_batch64` glue=shift f=0.1 | **`tol0.05`**（m≈1.000） | **2026-08-04 恢复**；ratio≈63.99；both_end 1×1 备份 `_1x1_both_end_ok.step`（OCC 邻胞空融） |
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

### 2.3 扩参（09-13 起，L=20，未目视）

| 案 | 1×1 | 444 | heal | 备注 |
|----|-----|-----|------|------|
| `af0p5q1_deq2_k1` | `gmsh_octant_both_end` | `noclip_batch64` g=shift f=0.1 | `tol0.05` | Q=1 Af 扫参 |
| `af1p5q1_deq2_k1` | `centre_stub_corner_ext` | 同上 | `tol0.05` | 同上 |
| `af2p5q1_deq2_k1` | 复用 1×1 | 同上 | **`ocp_shapefix_noglmh`** | 09-15；条件 hub-ball |
| `af0p5q1p5_deq2_k1` | `both_end`+ext=2.5（qc skip 重生 1×1） | 盘上已有 444；qc 记 skip array | `tol0.05` | Q=1.5 |
| `af1q1p5_deq2_k1` | 复用 1×1 | `noclip_batch64` | `tol0.05` | Q=1.5 |
| `af1p5q1p5_deq2_k1` | `both_end`+ext=2.0 | **`sw_combine_manual`** | — | Q=1.5；阵列非 noclip |

### 2.4 L=10（相似缩放）

| 案 | 1×1 | 444 | qc | 备注 |
|----|-----|-----|----|------|
| `af2q0_deq2_k1_L10` | `gmsh_paper_box_both_end` | 有 | `unitcell_ok_pending_array` | 仿真已用 0.3 网格完成 |
| `af2q1_deq2_k1_L10` | `centre_stub_corner_ext`+ext=1.25 | 有 | 同上 | 同上 |
| `af2q1p5_deq2_k1_L10` | 有 | 有 | **无 qc** | 仿真已完成 |
| `af2q1_deq2_k2_L10` | 有 | 有 | **无 qc** | 未入队 CAE |

### 2.5 目视核对状态

| 案 | 本机结论 | 1x1 | strut | 444 |
|----|----------|-----|-------|-----|
| §2.1 共 11 案（原 noclip 目视集） | **合格** | 有 | 有 | QC ok |
| §2.2 共 5 案 | **未查**（清单） | 有 | 有 | QC ok（早期路径） |
| §2.3 扩参 6 案 | **未查** | 有 | 有 | QC ok |
| §2.4 L10 | **未查** | 有 | — | 444 有；qc 未收口 |

---

## 3. 耗时经验（顺路成功）

| 阶段 | 典型 | 难案 |
|------|------|------|
| 1×1 | 0.5–1 min | face-mate 硬参 ≈30–40 s |
| strut1 | 几秒 | — |
| 444 `noclip_batch64` | **3–5 min** | — |
| heal | ≈2 min | 细杆可达 ≈10 min |
| **整案** | **约 5–10 min** | 细杆 / 重试 **约 15–20 min** |

单档超时：1×1 默认 10 min；444 默认 90 min（超时 kill → 下一档）。细节见 [`param_batch_STEP生成说明.md`](./param_batch_STEP生成说明.md) §3。

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
| 2026-08-04 | 细杆案恢复 | face-mate `centre_stub_corner_ext`+`ext=1.5` → `noclip_batch64`；QC ok；both_end 仅作备份勿作默认 |
| 2026-09-07 | CAD 维护 | `_batch_status` / `_batch_run_summary` 更新（含 tip-clean / heal 等）；16/16 QC 仍 ok |
| 2026-09-08 | 文档对齐 | 当时 §0：12/16 可分析 + 4 HOLD |
| 2026-09-13～18 | Af 扩参 + L10 | 清单扩至 26；见 §2.3–§2.4 |
| 2026-09-22 | 文档对齐 | CAD 26 案 STEP 齐；L20 QC 22/22；CAE 见 §0 |

---

## 5. 建议下一步

1. **CAD**：L=20 STEP+QC 齐；L10 需补 qc / 确认 444 口径。新参量案默认走说明 §3 锁定梯子（细杆优先 face-mate，勿默认 both_end）。  
2. **HOLD**：仅 `af2q1_deq2_k2`（及附属 `…_k2_L10`）— 协议网格 0 单元，需 **CAD 重融合** → verified → 协议 CAE（禁止放大 seed 进主对比）。  
3. **早期 5 案**：若要与主对比几何口径完全一致，可择机 `FORCE=1` 按 noclip 重生成；否则可继续用现 STEP。  
4. **仿真 / 分析**：逐案状态与能量图册见 [`param_batch_CAE仿真情况明细.md`](./param_batch_CAE仿真情况明细.md) §4。

---

*更新本表时：改文首同步时间；成功路径以各案 `*_qc.json` 为准，并与 `单胞核对清单.md` 勾选对齐。*
