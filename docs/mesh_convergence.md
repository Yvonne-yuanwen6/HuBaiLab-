# 网格收敛性研究（CAE C3D4）

Hu & Bai Fig.3.3 复现中，SFBLS 正弦杆**曲线段**在默认 `lattice_contact` + seed=0.6 mm 下，杆径方向仅 ~3 单元/直径，且当 `d/N ≈ global seed` 时**不会触发**沿杆加密。本目录流程用于系统扫 mesh 并对比实验曲线。

## 新增：`lattice_curve` 网格策略

在 `scripts/abaqus_cae_hex_mesh_pilot.py` 中新增 preset **`lattice_curve`**：

| 项 | `lattice_contact`（默认） | `lattice_curve`（曲线加密） |
|----|---------------------------|-----------------------------|
| 杆边 seed | 仅当 `d/N < 0.95×seed` 时细化 | **`force_rod_edge_seeds`**：所有边按 **d/N** 强制 seed |
| 外表面 | 可选 | **surface refine**（factor 0.60） |
| 过渡 | 无 | **minTransition** + sizeGrowth 1.08 |

用法：

```bash
bash scripts/linux/run_abaqus_cae_mesh.sh \
  --step output/cad/verified/hu_bai_sfbls_af2q0p5_L20_4x4x4_paper_box_array.step \
  --out output/export/_mesh_test/sfbls_curve.inp \
  --seed 0.6 --mesh-quality lattice_curve --rods-per-diameter 4 \
  --virtual-topology
```

导出压缩 INP：

```powershell
py -3 scripts/run_hu_bai_bcc_solid_cad_cae_tet_export.py --Q 0.5 --cells 4 `
  --cae-seed 0.6 --cae-mesh-quality lattice_curve --cae-rods-per-diameter 4 `
  --force-remesh ...
```

（`--force-remesh` 通过 variant 脚本的 `--cae-mesh-inp` 省略或 `--force-remesh` 实现。）

每次 CAE 剖分后会写 **`{slug}_cae_mesh_manifest.json`**（节点/单元数、seed、quality、log 路径）。

## Q0.5 收敛扫参级别

定义见 `src/mesh/mesh_convergence.py`：

| id | seed [mm] | rods/d | quality |
|----|-----------|--------|---------|
| m0_baseline | 0.6 | 3 | lattice_contact |
| m1_rods4 | 0.6 | 4 | lattice_contact |
| m2_curve_r4 | 0.6 | 4 | **lattice_curve** |
| m3_seed05_r4 | 0.5 | 4 | lattice_curve |
| m4_seed04_r5 | 0.4 | 5 | lattice_curve |

## 运行流程

### 1. 仅剖分（服务器，不提交 Abaqus）

```bash
bash scripts/linux/run_paperbox_q05_mesh_convergence.sh --mesh-only
```

或本机/远程 mesh batch：

```powershell
py -3 scripts/run_mesh_convergence_mesh_batch.py --mesh-locally
# 或服务器：
py -3 scripts/run_mesh_convergence_mesh_batch.py --remote-host art@172.20.200.93 --remote-root /media/art/file/...
```

### 2. 剖分 + 求解（串行，耗时大）

```bash
nohup bash scripts/linux/run_paperbox_q05_mesh_convergence.sh --submit \
  >> output/logs/paperbox_q05_mesh_convergence.log 2>&1 &
```

材料/接触与 fig33 基线一致：`elastic` + `--contact-store-offsets`，便于**只隔离网格**影响。

### 3. 评估与作图

```bash
py -3 scripts/evaluate_mesh_convergence.py
py -3 scripts/plot_mesh_convergence.py
```

输出：

- `output/reports/mesh_convergence/q05_mesh_convergence.json`
- `output/reports/mesh_convergence/q05_mesh_convergence.png`

## 收敛判据（建议）

对相邻级别比较：

- **RMSE** vs Fig.3.3 Q0.5 实验（ε=0.025–0.80）变化 < **5–10%**
- **峰值应力**、**εd**、**snap-through** 是否稳定
- **单元数**不再随 h 细化显著增加而曲线变化

若 `m2_curve_r4` 已收敛而 `m0_baseline` 未收敛，说明问题主要在**曲线段网格**而非材料。

## 相关文件

| 文件 | 用途 |
|------|------|
| `src/mesh/mesh_convergence.py` | 扫参级别定义 |
| `scripts/abaqus_cae_hex_mesh_pilot.py` | `lattice_curve` preset |
| `scripts/linux/run_paperbox_q05_mesh_convergence.sh` | 服务器批跑 |
| `scripts/evaluate_mesh_convergence.py` | RMSE / 峰值 / snap 评分 |
| `scripts/plot_mesh_convergence.py` | 收敛曲线图 |
