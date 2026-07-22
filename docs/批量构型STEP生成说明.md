# 批量构型 STEP 生成说明

> **进度明细（含同步时间）**：见 [`批量构型STEP生成情况明细.md`](./批量构型STEP生成情况明细.md) — 服务器/本机各案 1x1·strut·444 盘点。

本批任务：**参数化批量生成 paper_box 单胞 + 4×4×4 阵列 STEP**；CAD QC 通过后并行两条仿真线——**Abaqus/Explicit 实体压缩**（`export/jobs/post/批量构型/`）与 **COMSOL 隔振频响**（`comsol_jobs/批量构型/`）。
目录与清单以服务器仓库为准，本机同步后结构一致。

| 项目 | 路径 / 值 |
|------|-----------|
| 本机仓库 | `D:\HuBaiLab` |
| 服务器 | `art@172.20.200.93` |
| 服务器仓库 | `/media/art/file/XiangLang/Lattice/LWY/HuBaiLab` |
| CAD 输出根目录 | `output/cad/批量构型/` |
| 参数清单 | `output/cad/批量构型/_batch_index.json` |
| Abaqus 仿真根 | `output/{export,jobs,post}/批量构型/{case_id}/` |
| Abaqus 清单 / 状态 | `output/export/批量构型/_batch_sim_index.json`、`_batch_sim_status.json` |
| COMSOL 仿真根 | `output/comsol_jobs/批量构型/{case_id}/` |
| COMSOL 清单 / 状态 | `output/comsol_jobs/批量构型/_batch_comsol_index.json`、`_batch_comsol_status.json` |

相关文档：[`CAD融合路线与已知问题.md`](CAD融合路线与已知问题.md)、[`Abaqus_CAD实体压缩说明.md`](Abaqus_CAD实体压缩说明.md)、[`COMSOL隔振工作流.md`](COMSOL隔振工作流.md)、[`本机开发服务器求解工作流.md`](本机开发服务器求解工作流.md)。

Abaqus 批量**主对比统一标准**见下文 **§7.2**（`BATCH_SIM_MESH_PROTOCOL=1`：heal → seed0.6/`fast`/vtopo → 80%·5 mm/min·Neo-Hooke）。

---

## 1. 控制参数与本批取值

| 参数 | 含义 | 本批取值 |
|------|------|----------|
| **Q** | 周期因子 | `0, 0.5, 1.0, 1.5` |
| **Af** | 杆中心线幅值 (mm) | 中心 `2`；扫参 `1, 3`（仅 Q=1 圆杆） |
| **deq** | 等面积等效圆径 (mm) | 中心 `2`；扫参 `1.5, 2.5`（仅 Q=1 圆杆） |
| **κ (k)** | 截面长径/短径；`k1`=圆杆 | `1, 1.5, 2`；`k>1` 默认 **ellmin**（短径∥压缩） |
| **L / 阵列** | 单胞边长 / 阵列 | `L=20 mm`，`4×4×4`（不写进文件名） |

椭圆与圆在同一 `deq` 下保持截面积相等。

**组合策略（共 16 案，非全因子）**

- **组 A**：`Af=2, deq=2`，`Q∈{0,0.5,1,1.5}` × `k∈{1,1.5,2}`
- **组 B**（围着 AF2Q1 圆杆）：`Af∈{1,3}`，`deq∈{1.5,2.5}`

生成顺序见 `_batch_index.json` → `generation_order`（先圆后椭圆 κ=2 / κ=1.5，再 Af/截面积扫参）。

---

## 2. 命名与目录

**case_id / 文件名**

```text
af{Af}q{Q}_deq{D}_k{κ}
af{Af}q{Q}_deq{D}_k{κ}_1x1.step         # 单胞
af{Af}q{Q}_deq{D}_k{κ}_strut1_raw.step  # 单杆切前（双端延长后的完整 pipe，未盒切）
af{Af}q{Q}_deq{D}_k{κ}_strut1.step      # 单杆切后（1 根代表性 paper-box octant 切杆）
af{Af}q{Q}_deq{D}_k{κ}_444.step         # 4×4×4
af{Af}q{Q}_deq{D}_k{κ}_qc.json          # 体积比等 QC
```

数字格式：整数不加小数点；小数用 `p`（例：`0.5→0p5`，`1.5→1p5` / `deq1p5`）。

**目录**

```text
output/cad/批量构型/
  _batch_index.json
  _batch_run_summary.json          # 批跑汇总（有则）
  af2q0_deq2_k1/
    af2q0_deq2_k1_1x1.step
    af2q0_deq2_k1_strut1_raw.step  # 盒切前
    af2q0_deq2_k1_strut1.step      # 盒切后
    af2q0_deq2_k1_444.step
    af2q0_deq2_k1_qc.json
    .work/                         # 融合中间件（zslab 等）
  …
```

每人案：**你目视检查 `_1x1.step`（及可选 `_strut1_raw.step` / `_strut1.step`）；脚本检查 `V_444 / V_1x1 ≈ 64`（默认相对容差 ±3%）。**

---

## 3. 脚本入口

| 用途 | 脚本 |
|------|------|
| **批处理主程序**（含超时 + `--repair` / `--strut-only`） | `scripts/run_param_batch_step_generate.py` |
| 服务器全量启动 / 续跑 | `scripts/linux/run_param_batch_step_generate.sh` |
| **只补单杆 strut1** | `scripts/linux/run_param_batch_strut_only.sh` |
| **自动检查并修正失败案** | `scripts/linux/run_param_batch_auto_repair.sh` |
| 仪表盘（一帧） | `scripts/linux/_tmp_param_batch_dashboard.py` |
| **监控循环** | `scripts/linux/_tmp_monitor_param_batch.sh` |
| 卡住检查 | `scripts/linux/_tmp_stuck_check.sh` |
| 同步代码（本机） | `scripts/sync_to_server.ps1`（`scripts` + `src`） |

### 3.1 策略超时（防卡死）

单胞 / 阵列的**每一档策略**都在独立子进程里跑，超过预算就 **kill → 试下一档**：

| 参数 | 默认 | 含义 |
|------|------|------|
| `--unitcell-attempt-timeout` | `600` s（10 min） | 每一档 1×1 策略上限 |
| `--array-attempt-timeout` | `5400` s（90 min） | 每一档 444 策略上限 |

日志会出现：`TIMEOUT <label>: exceeded … — kill and try next`。

### 3.2 自动检查 / 修正（推荐日常用法）

在服务器仓库根目录：

```bash
# 只扫描状态，写 output/cad/批量构型/_batch_status.json
CHECK_ONLY=1 bash scripts/linux/run_param_batch_auto_repair.sh

# 扫描后仅 FORCE 重跑 needs_repair 的案（默认含超时保护）
nohup bash scripts/linux/run_param_batch_auto_repair.sh \
  >> output/logs/param_batch_auto_repair.log 2>&1 &

# 只修某一案
ONLY=af2q1_deq1p5_k1 bash scripts/linux/run_param_batch_auto_repair.sh

# 已有合格 1×1、只重做 444（细杆阵列失败常用）
ONLY=af2q1_deq1p5_k1 ARRAY_ONLY=1 bash scripts/linux/run_param_batch_auto_repair.sh

# 只补生成单杆 strut1（保留 1×1 / 444；命名见 `_batch_index.json` → naming.strut / strut_raw）
py -3 scripts/run_param_batch_step_generate.py --strut-only
# 或指定案：
py -3 scripts/run_param_batch_step_generate.py --strut-only --only af2q0_deq2_k1 af2q0_deq2_k2
# 服务器一键补全（跳过已有单实体 strut1）：
# bash scripts/linux/run_param_batch_strut_only.sh
# FORCE=1 ONLY="af2q0_deq2_k2" bash scripts/linux/run_param_batch_strut_only.sh

# 案级并行（Abaqus 还在跑时建议 2；纯 CAD 空闲可试 3）
py -3 scripts/run_param_batch_step_generate.py --force --jobs 2 --only af2q1_deq2_k1 af2q0_deq2_k1p5
```

**细杆 444（`deq<1.75` 且 `k=1`）梯子优先序**：

1. **`ocp_noclip_batch64`**（2026-07-19：face-mate 种子 `corner_ext=1.5` 验证 `af2q1_deq1p5_k1`）→ 再 **`ocp_scale*_batch64`**
2. **`ocp_deep_pad`**：按层重建 octant 杆 + 大周期 pad（默认 2 mm）→ 行/层间融合，质量门控 + 单实体 remelt（禁止只靠 STEP 体积当成功）
3. **`ocp_seed_scale_zcopy`**：单胞微膨胀（≈1.005–1.02）→ **只融 iz=0 的 4×4** → **+Z 复制平移** 得 iz=1..3 → 四层 `444z` 融合（glue=off, fuzzy≈0.1）
4. seed-translate OCP：扩大 `periodic_overlap_mm` → `hierarchical_batch`
5. `gmsh_fallback`

**椭圆 / 普通圆杆 OCP 444 梯子优先序**：

1. **优先 `ocp_noclip_batch64`**（pitch=L、不 clip，一次性 OCP batch 融全部 64 胞，`glue=shift`, `fuzzy=0.1`，约 3–5 min，QC≈64）：
   - Q=1 / 1.5 非细杆（验证 `af2q1_deq2_k1` / `…_k1p5` / `…_k2` / `af2q1_deq2p5_k1`）
   - 椭圆含 Q≠1（验证 `af2q0p5_deq2_k2`：`both_end+ext=3` 种子）
2. **`ocp_scale*_batch64`**（验证 `af2q1p5_deq2_k1p5`）：单胞微膨胀后再一次性 batch（**无 zcopy**）；用于裸 noclip 空融、但 2-cell scale 能 HIT 的案。
3. **`ocp_seed_scale_zcopy`**：`scale=1.005` + iz0 融 + Z 复制（易案仍有效；硬案常卡在 444z）。
4. 常规 OCP hierarchical / glue 组合
5. 必要时 gmsh

行内融合仍会自动 climb（`row_glue`: full→shift→off；fuzzy≤0.8）。接受 444 前要求 **gmsh** `volume_count==1`（不得只信 OCP 实体数）。

**1×1 face-mate 锁（2026-07-19，后续批量必走）**：

| 项 | 行为 |
|----|------|
| 问题 | 默认 `corner≈0.75·deq` 可得到 **单实体 1×1**，但 pitch=L 邻胞 fuse 仍空（BOP empty）→ noclip 必然失败 |
| 优先 tip 伸出 | Q=1 圆杆：`deq=2.5→ext=2.5`、`deq=1.5→ext=1.5`（`centre_stub_corner_ext`）；椭圆 `κ≥2`：`both_end_extension` + `ext=3.0` / `2.5`（先于默认 hybrid） |
| ACCEPT 门控 | `_seed_face_mate_ok`：对 Q≈1 / 1.5 / 椭圆，须 X/Y/Z 邻胞 fuse 均为 `n=1` 且 `r∈[0.9,1.1]`；否则 **REJECT** 试下一档（不得只信 `volume_count==1`） |
| 入口 | `scripts/run_param_batch_step_generate.py` → `_export_unitcell` / `_seed_face_mate_ok` |

仿真导入要求交付 **单实体** `volume_count==1`；多体 compound / 仅靠 CAE tie 不作为最终 `_444.step`。

**444 写盘后结构保持预处理（默认开）**：`heal_step_for_cae`（Gmsh OCC）。仅当 **单实体且 mass_ratio∈[0.95, 1.05]** 时用 healed 覆盖 `{id}_444.step`；否则保留原文件。不改 Af/Q/deq/κ 设计，只缝合/清理小特征。**首个成功预设即停**；总/单预设超时默认 2400 s / 900 s。报告：`{id}_444_heal.json`（并写入 `qc.json`→`array_heal`）。关闭：`--no-post-heal` 或 `BATCH_STEP_POST_HEAL=0`。  
说明：门控失败（0 体积等）≠改结构，而是拒绝坏 heal；真正改设计需重融合，不是此步。CAE 队列见 `*_444_heal.json` 后默认 **不再重复 heal**（`BATCH_SIM_FORCE_HEAL=1` 可强制）。

环境变量：`FORCE=1` 强制重做；`ONLY="af2q0_deq2_k1 …"` 只跑指定案；`JOBS=2` 案级并行；`TOL_REL=0.03`；`STOP_ON_FAIL=1`；`BATCH_STEP_POST_HEAL=0`；`INTERVAL=8`（监控刷新秒）。

### 3.1 锁定方案与防回归（必读）

后续批量生成**默认**走下列已验证路径，勿改回「每层重新阵列」或「OCP solids=1 即 ACCEPT」：

| 项 | 锁定行为 | 曾出现的问题 |
|---|---|---|
| 1×1 tip / face-mate | 硬参优先显式 `corner_ext`；ACCEPT 前 **pitch=L 三轴邻胞 fuse** | 单实体种子不可贴合 → noclip 空融（`af2q1_deq2p5_k1`） |
| 444 优先策略 | Q≈1/1.5、椭圆、细杆均优先 **`ocp_noclip_batch64`**；再 scale_batch / deep_pad / zcopy | 分层/zcopy 破坏正交接触；四层各融极慢 |
| 接受门控 | 写 STEP 后 **gmsh 测实体数==1**（`gmsh_verified`）；QC 同口径 | OCP 报 1、gmsh 见 2 仍被 ACCEPT |
| 写盘后 heal | **默认** `step_heal_for_cae`；仅 mass_ratio∈[0.95,1.05] 才覆盖 `_444.step` | 无门控会“修没”结构；失败须 KEEP 原 STEP |
| `--jobs>1` | `measure_step_occ_stats` 在非主线程自动进子进程 | `gmsh.initialize` → `signal` 崩，误标 error |
| `--force` 启动扫描 | **light**（只看 qc.json + 文件大小） | 启动前 gmsh 测大 444，卡住数分钟无 `Cases:` |

常量入口：`scripts/run_param_batch_step_generate.py` 中 face-mate 优先档、`SEED_SCALE_ZCOPY_SPECS_*`、`DEEP_PAD_SPECS_THIN_ROD`；实现：`src/export/ocp_deep_pad_array_fuse.py` → `export_ocp_noclip_batch_array_fuse` / `export_seed_scale_inflate_array_fuse`。

---

## 4. 服务器：同步 → 启动批处理 → 监控

### 4.1 本机同步代码

```powershell
cd D:\HuBaiLab
.\scripts\sync_to_server.ps1
# 若只改了个别文件，也可 scp：
# . .\scripts\remote_config.ps1
# scp .\scripts\run_param_batch_step_generate.py "${HuBaiRemoteHost}:${HuBaiRemoteRoot}/scripts/"
# scp -r .\scripts\linux\. "${HuBaiRemoteHost}:${HuBaiRemoteRoot}/scripts/linux/"
# scp -r .\output\cad\批量构型\. "${HuBaiRemoteHost}:${HuBaiRemoteRoot}/output/cad/批量构型/"
```

### 4.2 启动 / 重启批处理（服务器 SSH）

```bash
ssh art@172.20.200.93
cd /media/art/file/XiangLang/Lattice/LWY/HuBaiLab

# 前台看启动日志，或用 nohup：
bash scripts/linux/run_param_batch_step_generate.sh

# 推荐后台：
JOBS=2 nohup bash scripts/linux/run_param_batch_step_generate.sh \
  >> output/logs/param_batch_step.log 2>&1 &

# 仅重跑若干案：
ONLY="af2q0_deq2_k2 af2q1p5_deq2_k2" FORCE=1 JOBS=2 \
  bash scripts/linux/run_param_batch_step_generate.sh
```

已有且通过的 `_1x1` / `_444` 默认 **skip**（无需 FORCE）。

### 4.3 监控启动方式（重点）

**方式 A — 服务器上全屏仪表盘（推荐）**

```bash
cd /media/art/file/XiangLang/Lattice/LWY/HuBaiLab
INTERVAL=8 bash scripts/linux/_tmp_monitor_param_batch.sh
# Ctrl+C 退出
```

**方式 B — 本机 PowerShell 经 SSH 挂监控**

```powershell
cd D:\HuBaiLab
. .\scripts\remote_config.ps1
ssh -t $HuBaiRemoteHost "INTERVAL=8 bash $HuBaiRemoteRoot/scripts/linux/_tmp_monitor_param_batch.sh"
```

**方式 C — 只打一帧（不循环）**

```bash
cd /media/art/file/XiangLang/Lattice/LWY/HuBaiLab
.venv/bin/python3 scripts/linux/_tmp_param_batch_dashboard.py
```

**方式 D — 是否卡住**

```bash
bash scripts/linux/_tmp_stuck_check.sh
# CPU 高 + 日志/阶段在变 → 正常偏慢；进程无 / 日志长时间不动 → 再查
```

### 4.4 监控图例

| 符号 | 含义 |
|------|------|
| ✓ | 完成（`qc.ok`，显示 1x1/444 大小与体积比） |
| ▶ | 正在生成（进度条 + 阶段，如 `OCP iz0 行2 单元 3/4`） |
| ✗ | 失败（`status=error` / `qc_fail`） |
| … | 部分完成（有文件待 QC） |
| ○ | 排队 |

日志：`output/logs/param_batch_step.log`  
进度戳：`output/logs/param_batch_step.progress`

---

## 5. 本机拉回已成功模型

```powershell
cd D:\HuBaiLab
. .\scripts\remote_config.ps1
$id = "af2q0_deq2_k1"   # 换成目标 case_id
$Local = ".\output\cad\批量构型\$id"
New-Item -ItemType Directory -Force -Path $Local | Out-Null
scp "${HuBaiRemoteHost}:${HuBaiRemoteRoot}/output/cad/批量构型/${id}/${id}_1x1.step" $Local\
scp "${HuBaiRemoteHost}:${HuBaiRemoteRoot}/output/cad/批量构型/${id}/${id}_444.step" $Local\
scp "${HuBaiRemoteHost}:${HuBaiRemoteRoot}/output/cad/批量构型/${id}/${id}_qc.json"  $Local\
```

---

## 6. QC 与后端策略（摘要）

- **体积比**：`mass_mm3(444) / mass_mm3(1x1)`，目标 **64**，相对容差默认 **3%**；两边实体数均为 1（**gmsh OCC**）。
- **444 交付**：必须 **单实体**；多体 compound 不 ACCEPT。
- **阵列优先**：Q≈1/1.5、椭圆、细杆均优先 **`ocp_noclip_batch64`**，再 `scale*_batch64` / deep_pad / `seed_scale_zcopy` / 常规 OCP / gmsh。
- **单胞**：优先 **OCP `centre_stub_corner_ext`**（角端 path 延长 → 平端面；胞心 chord stub → 可融）；硬参先试显式 `corner_ext`（见 §3 face-mate 表）；椭圆 `κ≥2` 优先 `both_end_extension+ext`。再 gmsh `*_both_end` / 其余 OCP。**禁止** ACCEPT：`gmsh_paper_box`（无 both_end）、裸 `gmsh_octant`、裸 OCP `centre_stub`（无 corner_ext → 杆端尖楔）、以及 **pitch=L 不可贴合** 的单实体种子。写出后 **bbox/COM 归零**（idempotent）。
- **监控易误判**：`--only` 时仪表盘只显示本批案；`seed_scale` / noclip batch 单次可数分钟无新日志，worker CPU≈100% 表示在算而非空转。`.work` 新鲜度用于标 ▶进行中。
- **并行**：`JOBS=2`（或 `--jobs 2`）可用；QC/ACCEPT 测体积不得在 worker 线程直接 `gmsh.initialize`。

**单胞策略梯子**（批处理 `_export_unitcell`）：  
face-mate 优先档（显式 ext）→ 默认 `centre_stub_corner_ext` → gmsh `*_both_end` → OCP `both_end_extension`；每档 ACCEPT 前过 tip-sliver + face-mate 门控。  
失败案重跑示例：

```bash
ONLY="af2q0_deq2_k2 af2q1p5_deq2_k2 af2q1_deq1p5_k1" FORCE=1 \
  bash scripts/linux/run_param_batch_step_generate.sh
# 或：bash scripts/linux/_tmp_rerun_failed_then_rest.sh
```

---

## 7. Abaqus 批量仿真（CAD QC 之后）

CAD 案 **`qc.ok` 且存在合格 `_444.step`** 后，由队列脚本拷入 `output/cad/verified/batch_{case_id}_paper_box_array.step`，再 **CAE 自动四面体网格 → 压缩 INP → 最多 2 路并行求解**。层级与 CAD 的 `case_id` 一一对应。

### 7.1 目录层级

```text
output/export/批量构型/
  _batch_sim_index.json          # 入队案 + 参数快照
  _batch_sim_status.json         # 运行状态（脚本刷新）
  _batch_sim_skipped.json        # 协议失败 / 梯子耗尽 / 求解崩溃后跳过的案
  af2q0_deq2_k1/
    cae_tet0p6mm80_5mmin_paperbox/
      *.inp  case_manifest.json  *_cae_mesh.inp  …
output/jobs/批量构型/
  af2q0_deq2_k1/cae_tet0p6mm80_5mmin_paperbox/   # .odb .sta .lck …
output/post/批量构型/
  af2q0_deq2_k1/cae_tet0p6mm80_5mmin_paperbox/   # 应力–应变等（postpull 后）
```

`run_slug` 固定为 **`cae_tet0p6mm80_5mmin_paperbox`**（短 slug；真实路径靠 `HU_BAI_{EXPORT,JOBS,POST}_ROOT` 指到各 `case_id` 下）。

### 7.2 统一仿真标准（主对比协议）

跨算例应力–应变主对比**只认**本协议产物。实现开关：`BATCH_SIM_MESH_PROTOCOL=1`（`scripts/linux/run_param_batch_cae_sim_queue.sh`）。日志关键字：`HEAL STEP` / `HEAL OK` / `CAE PROTOCOL`。

#### 7.2.1 目标与边界

| 原则 | 说明 |
|------|------|
| **可比优先** | 所有主对比案共用同一网格档位与同一求解设置；不为“能跑通”而静默换 seed / quality |
| **几何先修** | 网格失败优先修 STEP（heal / 重融合），不靠加粗网格混进主图 |
| **失败即 SKIP** | 协议一档失败 → 写入 `_batch_sim_skipped.json`，不进主对比；救援梯子仅诊断 |
| **体网格仅 CAE** | 四面体 **C3D4** 只由 Abaqus/CAE 生成；**禁止** gmsh 体网格进主线（Gmsh 仅用于 STEP heal） |

#### 7.2.2 网格协议（固定一档）

流程：**verified STEP → Gmsh OCC heal → CAE 单档 tet**。

| 步骤 | 标准 | 细节 |
|------|------|------|
| 1. CAD 源 | `output/cad/verified/batch_{case_id}_paper_box_array.step` | 由合格 `_444.step` 拷入 |
| 2. STEP heal（结构保持） | 必做；仅当前 `repair_version` 成功报告可跳过 | **合验一致**：mass∈[0.98,1.02]、face∈[0.92,1.08]、bbox_z∈[0.995,1.005]；优先轻量 sew / ShapeFix（默认不开 UnifySameDomain）；不通过则 **KEEP 合验 raw**。超时默认 2400/900 s。产物：`verified/heal_{case_id}/` |
| 3. heal 失败 | 回退用 raw verified STEP 仍走同一 CAE 档 | 不换 quality；CAE 仍失败则 SKIP |
| 4. CAE 剖分 | **唯一**主对比档 | seed **0.6 mm**；`--mesh-quality fast`；`--virtual-topology`；`--element-type C3D4`；`--rods-per-diameter 3.0`；`--rod-diameter` = 该案 `deq` |
| 5. 禁止（主对比） | 自动放大 seed（0.8/1.0）、换 `lattice_contact`/`lattice`/`lattice_curve`、关 vtopo 的“凑合成功” | 此类结果标为非可比 / 仅诊断 |

依据简述：Abaqus Virtual Topology 用于忽略小边/小面以提高可划分性（不永久改 CAD）；Gmsh OCC heal 用于缝合与小特征修复，并以体积比防止“修没了”。

#### 7.2.3 求解与接触（本批统一）

| 项 | 值 |
|----|-----|
| 几何 | 各案 `Af / Q / deq / k`；阵列 4×4×4，L=20 mm |
| 工程应变 | **80%**（压下 64 mm / 块高 80 mm） |
| 加载速率 | **5 mm/min**（压缩步长 768 s） |
| Explicit | dt 上限 5×10⁻⁴ s，`automatic`；质量缩放 `below_min`×50 |
| 材料 | Neo-Hooke（CLI `paper`）：E=25 MPa，ν=0.47，ρ=1135 kg/m³ |
| 自接触 | STORE OFFSETS + ContactSettle（15% 步长，s0=0.02）；μ=0.1 |
| 资源 | 每案 **48 核 / 256 GB**；求解最多 **2 路并行**；CAE 网格 **串行**；压缩 INP **后台导出**（不堵下一案网格） |

#### 7.2.4 失败、跳过与重提

| 情形 | 处理 |
|------|------|
| heal 无可用预设 / CAE 0 单元 | **SKIP**（`_batch_sim_skipped.json`）；修几何后重入队 |
| 求解已异常退出（如 `Excessive distortion`） | 默认 **不再重提** → SKIP；强制重提才设 `BATCH_SIM_ALLOW_SOLVE_RETRY=1` |
| 双提交 / `.lck` 误报 | 脚本侧 `LAUNCHED` 守卫 + 等锁；真冲突记 `job_lock_collision` |
| 存在 `_batch_sim_paused.json` | 拒绝启动（除非 `BATCH_SIM_IGNORE_PAUSE=1`） |

#### 7.2.5 诊断梯子（非主对比）

仅当 **未** 设 `BATCH_SIM_MESH_PROTOCOL=1` 时启用。仍只用 CAE：**优先保持 seed 0.6**（换 quality / vtopo / `seed-part-only` / `ignore-invalid`），**仅当 0.6 全部失败**才放大到 0.8 / 1.0。梯子结果**不得**与协议案混画主对比图。  
历史说明：`lattice_contact`+vtopo 在部分 Q≈1 上会久跑后 0 单元，故协议档改用 `fast`+vtopo。

协议档 / 诊断梯子 / 队列求解的 **Mermaid 流程图**见 [`批量构型CAE仿真情况明细.md`](批量构型CAE仿真情况明细.md) §1–§2。  
**本机与服务器对齐**（heal→CAE→压缩 INP）见同文档 **§6**；入口：`scripts/run_param_batch_cae_mesh_local.ps1`（默认锁定协议档，禁止静默改 seed/quality）。

#### 7.2.6 启用示例

```bash
cd /media/art/file/XiangLang/Lattice/LWY/HuBaiLab
export PATH="$HOME/APP/abaqus2022/Commands:$PATH"
BATCH_SIM_MESH_PROTOCOL=1 BATCH_SIM_SKIP_BASELINE=1 BATCH_SIM_MAX_PARALLEL=2 \
BATCH_SIM_ONLY="af2q0_deq2_k1p5 af2q0p5_deq2_k1p5 …" \
  bash scripts/linux/run_param_batch_cae_sim_queue.sh
```

对照清单（主对比入库前）：

1. 日志出现 `CAE PROTOCOL SUCCESS`（或等价：mesh 由协议档写出）。  
2. 有 `heal_{case_id}/heal_report.json` 且 mass_ratio 在门控内（或明确记录“heal 回退 raw”）。  
3. 求解 `.sta` 为 COMPLETED；无协议外 seed/quality。  
4. 未出现在 `_batch_sim_skipped.json`。

### 7.3 脚本入口

| 用途 | 脚本 |
|------|------|
| **仿真队列主程序**（提交已导出 + 续网格 + 梯子 + 跳过） | `scripts/linux/run_param_batch_cae_sim_queue.sh` |
| tmux 一键启动 | `scripts/linux/_launch_param_batch_cae_sim_tmux.sh` |
| 解除暂停并续跑 | `scripts/linux/_tmp_resume_param_batch_cae_sim.sh` |
| 仪表盘（一帧） | `scripts/linux/_tmp_param_batch_cae_sim_dashboard.py` |
| **监控循环**（同 STEP 监控风格） | `scripts/linux/_tmp_monitor_param_batch_cae_sim.sh` |
| 本机 SSH 挂监控 | `scripts/watch_param_batch_cae_sim.ps1` |

环境变量：`BATCH_SIM_CPUS=48`、`BATCH_SIM_MEMORY_MB=262144`、`BATCH_SIM_MAX_PARALLEL=2`、`BATCH_SIM_ONLY="af2q0_deq2_k1 …"`、`BATCH_SIM_FORCE_REMESH=1`、`BATCH_SIM_EXPORT_ONLY=1`、`BATCH_SIM_SUBMIT_ONLY=1`、`BATCH_SIM_ALLOW_SOLVE_RETRY=1`、`BATCH_SIM_SKIP_BASELINE=1`、`BATCH_SIM_MESH_PROTOCOL=1`、`BATCH_SIM_FORCE_HEAL=1`、`BATCH_HEAL_TIMEOUT_S=2400`、`BATCH_HEAL_PRESET_TIMEOUT_S=900`、`BATCH_SIM_IGNORE_PAUSE=1`。

### 7.4 启动 / 续跑（服务器）

```bash
ssh art@172.20.200.93
cd /media/art/file/XiangLang/Lattice/LWY/HuBaiLab
export PATH="$HOME/APP/abaqus2022/Commands:$PATH"

# 推荐：独立 tmux（已存在则提示，不重复开）
bash scripts/linux/_launch_param_batch_cae_sim_tmux.sh
# attach: tmux attach -t param_batch_cae_sim

# 或直接跑（前台 / nohup）
bash scripts/linux/run_param_batch_cae_sim_queue.sh
# nohup bash scripts/linux/run_param_batch_cae_sim_queue.sh \
#   >> output/logs/param_batch_cae_sim_queue.log 2>&1 &
```

流程要点：

1. 读 `_batch_status.json`，只入队 **`qc.ok` + 大体积 `_444.step`** 的案。  
2. **先提交**已有压缩 INP（最多 2 路后台求解）。  
3. **串行**其余案：`MESH_PROTOCOL=1` 时走 §7.2 heal→单档 CAE；否则走诊断梯子。失败则 SKIP。  
4. 每导出一案立即填补空闲求解槽。

### 7.5 监控（与 §4.3 同风格）

仪表盘 **固定显示主对比 FOCUS_8 + NEW3**（共 11 案）+ **BASELINE_5**。侧队列改写 `_batch_sim_index.json` **不会**缩表。

表头额外显示：

- **会话**：主队列 / `submit_only` / `skip_v3网格` / `new3等CAE` 等并发会话摘要  
- **求解中**：由 `eliT_DriverLM` 进程识别（最多 2 路 Explicit）+ STA 步时  
- **网格中**：当前 heal / CAE 剖分案（`ABQcaeK` 已跑时长 / CPU；低 CPU 久跑需警惕卡住）

实现注意：`jobs/` 下大 ODB 会使 NFS `ls`/`stat` 长时间无响应甚至 D 状态；仪表盘**不读** `jobs/*.sta`/ODB，求解态以 `eliT_DriverLM` 为准。监控脚本优先跑 `/tmp/_dash.py` + `/usr/bin/python3`（NFS 上 `scripts/` 可能写不进）。勿对 `output/jobs/批量构型` 做通配列举。

**NEW3 入队**（已有合格 `*_444.step`，不打断正在跑的求解）：

```bash
bash scripts/linux/_tmp_start_3_new_444_sim.sh
# tmux: param_batch_new3
# ONLY= af2q0p5_deq2_k2 af2q1_deq1p5_k1 af2q1_deq2p5_k1
# MESH_PROTOCOL=1；启动时若 ABQcae 占用则等待空闲再 mesh
```

**方式 A — 服务器全屏仪表盘（推荐）**

```bash
cd /media/art/file/XiangLang/Lattice/LWY/HuBaiLab
INTERVAL=8 bash scripts/linux/_tmp_monitor_param_batch_cae_sim.sh
# Ctrl+C 退出
```

**方式 B — 本机 PowerShell 经 SSH**

```powershell
cd D:\HuBaiLab
powershell -File scripts/watch_param_batch_cae_sim.ps1
# 或：
. .\scripts\remote_config.ps1
ssh -t $HuBaiRemoteHost "INTERVAL=8 bash $HuBaiRemoteRoot/scripts/linux/_tmp_monitor_param_batch_cae_sim.sh"
```

**方式 C — 只打一帧**

```bash
.venv/bin/python3 scripts/linux/_tmp_param_batch_cae_sim_dashboard.py
```

| 符号 | 含义 |
|------|------|
| ✓ | 求解完成（`.sta` COMPLETED） |
| ▶ | 求解中（进度条：步时 / settle+压缩≈883 s） |
| ▣ | 正在 CAE 网格 / heal（协议单档，非梯子） |
| ■ | 已导出 INP，等待求解核位 |
| ✗ | 跳过或失败（见 `_batch_sim_skipped.json`） |
| … | 网格完成、待写压缩 INP |
| ○ | 排队 |

日志：`output/logs/param_batch_cae_sim_queue.log`

**主对比案快照（2026-07-19 ≈17:12）**

| 案 | 状态 |
|----|------|
| `af2q0_deq2_k1p5` / `af3q1_deq2_k1` | ✓ 完成 |
| `af2q1_deq2_k1` / `af2q1_deq2_k1p5` | ▶ 求解中（Explicit 仍在） |
| `af1q1_deq2_k1` / `af2q0p5_deq2_k1p5` | ✗ SKIP（0 单元；需 CAD 重融合） |
| `af2q1_deq2_k2` / `af2q1p5_deq2_k1p5` | ○ 待重网格 |
| NEW3×3 | ○ 待网格（已修 ABQcae 自匹配） |

旧基线 5 案仍 ✓，**勿重网格**。逐案进度与网格/求解设置核对见 [`批量构型CAE仿真情况明细.md`](批量构型CAE仿真情况明细.md)；CAD 侧见 [`批量构型STEP生成情况明细.md`](批量构型STEP生成情况明细.md) §0。

### 7.6 本机拉回仿真结果（单案）

```powershell
cd D:\HuBaiLab
. .\scripts\remote_config.ps1
$id = "af2q0_deq2_k1"
$slug = "cae_tet0p6mm80_5mmin_paperbox"
$Local = ".\output\jobs\批量构型\$id\$slug"
New-Item -ItemType Directory -Force -Path $Local | Out-Null
scp "${HuBaiRemoteHost}:${HuBaiRemoteRoot}/output/jobs/批量构型/${id}/${slug}/${slug}.sta" $Local\
scp "${HuBaiRemoteHost}:${HuBaiRemoteRoot}/output/jobs/批量构型/${id}/${slug}/${slug}.odb" $Local\
```

更完整的提交 / 资源预检 / 续算见 [`本机开发服务器求解工作流.md`](本机开发服务器求解工作流.md)；单案 CAE 基线细节见 [`Abaqus_CAD实体压缩说明.md`](Abaqus_CAD实体压缩说明.md)。

---

## 8. COMSOL 批量仿真（隔振频响，CAD QC 之后）

CAD 案 **`qc.json` 通过（`status`/`qc.ok`）且存在合格 `_444.step`** 后，串行入队 **Fig.2.8 装配 + 频域谐响应**（**本征关闭**）。层级与 CAD 的 `case_id` 一一对应；与 Abaqus 压缩队列可并行，但注意机器负载（COMSOL 默认 `np=8`）。

单案建模/扫频细节见 [`COMSOL隔振工作流.md`](COMSOL隔振工作流.md)。

### 8.1 目录层级

```text
output/comsol_jobs/批量构型/
  _batch_comsol_index.json       # 入队案 + 默认工况
  _batch_comsol_status.json      # 运行状态（脚本刷新）
  af2q0_deq2_k1/
    fig28_p1_300g/               # run_slug
      case_manifest.json
      fig28_p1_300g.mph          # 建模后
      fig28_p1_300g_solved.mph   # 扫频后
      fig28_p1_300g_batch.log    # comsol batch 日志（含 参数 freq = …）
      fig28_p1_300g_transmissibility.csv
      …（可选 VLD/png）
  …
```

每案通过 `HU_BAI_COMSOL_JOBS_ROOT=output/comsol_jobs/批量构型/{case_id}` 把 job 指到案内；`--slug` 仍用短名 **`fig28_p1_300g`**。全局 fixture 模板固定为 `output/comsol_jobs/comsol_fixture_444/comsol_fixture_444.mph`（**不要**跟 per-case `COMSOL_JOBS_ROOT` 走偏）。

### 8.2 仿真参数（本批统一）

| 项 | 值 |
|----|-----|
| 几何 | 各案 `Af / Q / deq`；阵列 4×4×4，L=20 mm；STEP = `{case_id}_444.step` |
| 装配 | §2.4.3 / Fig.2.8：振动台 + 点阵 + 铝顶板；`p1_continuity`；顶载 **300 g** |
| 本征 | **关闭**（`--freq-only`） |
| 激励 | Z 向指定加速度 **0.98 m/s²**（仓库 Z-up STEP） |
| 扫频 | **10–2000 Hz**，步长 **10**（**200 点/案**） |
| 网格 | **physics-controlled** hauto（lattice=4 细化，fixture=5 常规）；与 Fig.3.21 `mesh_p1` 成功路径一致 |
| 材料 | 点阵 Fig.2.5 Marlow；振动台 AISI 4340；顶板铝合金 |
| 资源 | **串行**一案接一案；默认 **`np=8`**（`np=16` 易段错误） |

> **勿用**默认分层网格 + inline fixture **Mesh Copy**：会报「无法复制到任何目标实体」。必须加 `--physics-controlled-mesh`。

入队规则：读 `output/cad/批量构型/_batch_index.json` 的 `generation_order`，对每案检查 `{id}_qc.json` 与大体积 `{id}_444.step`（**不依赖**可能过期的 `_batch_status.json`）。

### 8.3 脚本入口

| 用途 | 脚本 |
|------|------|
| **仿真队列主程序**（建模 + 扫频 + 提取传递率） | `scripts/linux/run_param_batch_comsol_queue.sh` |
| tmux 一键启动 | `scripts/linux/_launch_param_batch_comsol_tmux.sh` |
| FORCE 清空错误标记后重开 | `scripts/linux/_tmp_relaunch_comsol_batch_force.sh` |
| 单案试点（build-only） | `scripts/linux/_tmp_pilot_comsol_batch_pcm.sh` |
| 仪表盘（一帧） | `scripts/linux/_tmp_param_batch_comsol_dashboard.py` |
| **监控循环**（同 STEP 监控风格） | `scripts/linux/_tmp_monitor_param_batch_comsol.sh` |
| 本机 SSH 挂监控 | `scripts/watch_param_batch_comsol.ps1` |

环境变量：`BATCH_COMSOL_NP=8`、`BATCH_COMSOL_FORCE=1`、`BATCH_COMSOL_ONLY="af2q0_deq2_k1 …"`、`BATCH_COMSOL_FREQ_MIN/MAX/STEP`、`BATCH_COMSOL_PYTHON=/home/art/conda/bin/python3`、`BATCH_COMSOL_RUN_SLUG=fig28_p1_300g`。

Python 须带 **MPh + jpype**（服务器用 conda `/home/art/conda/bin/python3`；项目 `.venv` 隔离 site-packages，**不能**直接跑 COMSOL）。

### 8.4 启动 / 续跑（服务器）

```bash
ssh art@172.20.200.93
cd /media/art/file/XiangLang/Lattice/LWY/HuBaiLab

# 推荐：独立 tmux（已存在则提示，不重复开）
BATCH_COMSOL_NP=8 bash scripts/linux/_launch_param_batch_comsol_tmux.sh
# attach: tmux attach -t param_batch_comsol

# 失败后强制重跑全队（清 _error.txt + 截断队列日志）
bash scripts/linux/_tmp_relaunch_comsol_batch_force.sh

# 只跑若干案
BATCH_COMSOL_ONLY="af2q0_deq2_k1 af2q0p5_deq2_k1" BATCH_COMSOL_FORCE=1 \
  bash scripts/linux/_launch_param_batch_comsol_tmux.sh
```

流程要点：

1. 按 `generation_order` 筛 QC 通过案，写 `_batch_comsol_index.json`。  
2. 每案**拆成两进程**：`--build-only`（MPh 建模后进程退出）→ `--solve-only`（仅 `comsol batch`，无 ClientWebSocket）→ `comsol_extract_isolation.py`。  
3. 若包装层曾 SIGSEGV（exit 139）但已有合格 `_solved.mph`（status=`Done` / 日志 100%），则 **RECOVER extract-only**，不重算。  
4. 失败写 `{job}/_error.txt`，默认 **CONTINUE** 下一案（不中断整队）。  
5. 已有合格 `*_transmissibility.csv`（非 FORMAT SAMPLE）则 **skip**（除非 `BATCH_COMSOL_FORCE=1`）。

> **假失败说明**：曾出现 MPh 的 `ClientWebSocket` 在等待 `comsol batch` 时长崩，队列误判失败，但子进程仍写完 `_solved.mph`。拆进程 + recover 即针对此。

日志：`output/logs/param_batch_comsol_queue.log`；单案：`output/logs/param_batch_comsol_{case_id}.log`。

### 8.5 监控（与 §4.3 / §7.5 同风格）

**方式 A — 服务器全屏仪表盘（推荐）**

```bash
cd /media/art/file/XiangLang/Lattice/LWY/HuBaiLab
INTERVAL=8 bash scripts/linux/_tmp_monitor_param_batch_comsol.sh
# Ctrl+C 退出
```

**方式 B — 本机 PowerShell 经 SSH**

```powershell
cd D:\HuBaiLab
powershell -File scripts/watch_param_batch_comsol.ps1
# 或：
. .\scripts\remote_config.ps1
ssh -t $HuBaiRemoteHost "INTERVAL=8 bash $HuBaiRemoteRoot/scripts/linux/_tmp_monitor_param_batch_comsol.sh"
```

**方式 C — 只打一帧**

```bash
/home/art/conda/bin/python3 scripts/linux/_tmp_param_batch_comsol_dashboard.py
```

| 符号 | 含义 |
|------|------|
| ✓ | 完成（有传递率 CSV） |
| ▶ | 建模中 / 扫频中（进度条：当前 freq / 200 点） |
| ▣ | 已建 `.mph`，正启动 batch |
| ◇ | 已求解，正在提取 |
| ✗ | 失败（见 `{job}/_error.txt`） |
| ○ | 排队 |

### 8.6 本机拉回仿真结果（单案）

```powershell
cd D:\HuBaiLab
. .\scripts\remote_config.ps1
$id = "af2q0_deq2_k1"
$slug = "fig28_p1_300g"
$Local = ".\output\comsol_jobs\批量构型\$id\$slug"
New-Item -ItemType Directory -Force -Path $Local | Out-Null
scp "${HuBaiRemoteHost}:${HuBaiRemoteRoot}/output/comsol_jobs/批量构型/${id}/${slug}/${slug}_transmissibility.csv" $Local\
scp "${HuBaiRemoteHost}:${HuBaiRemoteRoot}/output/comsol_jobs/批量构型/${id}/${slug}/case_manifest.json" $Local\
# 可选大文件：
# scp "${HuBaiRemoteHost}:${HuBaiRemoteRoot}/output/comsol_jobs/批量构型/${id}/${slug}/${slug}_solved.mph" $Local\
```

---

*文档对应 CAD 批处理、Abaqus 压缩队列与 COMSOL 隔振队列；CAD 清单以 `output/cad/批量构型/_batch_index.json` 为准。*
