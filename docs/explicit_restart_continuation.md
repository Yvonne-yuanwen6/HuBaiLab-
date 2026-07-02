# Abaqus/Explicit 续算（Restart Continue）

HuBaiLab 压缩算例默认在 Explicit 步末写入 `*Restart, write, overlay, number interval=8`（见 `src/export/abaqus_compression.py`）。  
在源算例**成功结束**且保留 `.res` 的前提下，可从**末步变形态**继续加载到更高应变，而无需从 0 重跑。

---

## 1. 方案评估（s45 → 75%）

### 1.1 与「同网格重跑 0→75%」对比

| | **续算** `s45 → s75_cont` | **重跑** `s75`（当前在跑） |
|--|---------------------------|----------------------------|
| 初始状态 | s45 末步变形 + 接触 offset | 零位移 |
| 额外加载 | **+30% 应变**（24 mm / **288 s**） | 0→75%（60 mm / 720 s） |
| 网格 | 同 s45 C3D10M | 同 s45 网格 |
| 墙钟（估） | **~7 h**（仅后 30%） | **~18 h**（全程） |
| snap-through | 经过真实 45% 构型继续 | 重新走一遍前段 |

### 1.2 可行性结论

**可行**，前提：

1. 源 job 含 `${SLUG}.res`（s45 已有 ~31 MB `.res`）
2. 续算 INP 使用 `*Restart, read, end step, step=Compression, overlay`（`oldjob=SOURCE` 在 abq 命令行指定，**不要**写 `file=`）
3. 新步用 `COMP-DISP-CONT` 幅值 + `op=MOD` 边界，施加**附加**位移（非从 0 开始）
4. `STORE OFFSETS` 自接触状态随 restart 带入（general contact 定义在模型段，不需重划网格）
5. 提交时 `abq job=NEW oldjob=SOURCE input=NEW.inp`

### 1.3 风险与限制

| 风险 | 说明 | 缓解 |
|------|------|------|
| 源 job 被覆盖 | `oldjob=delete` 或重跑同名 job | **先 `backup_case_slug.sh`** |
| `.res` 与步末不一致 | 源算例中断 | 仅对 `COMPLETED SUCCESSFULLY` 的 job 续算 |
| 曲线拼接 | 续算 CSV 应变从 0 起 | 用 `merge_stress_strain_csv_paths()` 加 source 应变偏移 |
| ContactSettle 两步 | 续算从 Compression 末步读 | 仅支持单步或从最后一步 continue |
| 磁盘 | 续算仍写 ODB | overlay restart，interval≤8 |

### 1.4 s45 备份（必做）

```bash
bash scripts/linux/backup_case_slug.sh q05_c10m_s06r3_el_s45 pre_restart_20260702
```

备份到 `output/archive/q05_c10m_s06r3_el_s45_pre_restart_20260702/`，**不改动**原 `output/jobs/s45`。

---

## 2. 管线用法

### 2.1 备份

```bash
bash scripts/linux/backup_case_slug.sh SLUG [TAG]
```

### 2.2 导出续算 INP

```bash
python3 scripts/export_explicit_continue.py \
  --from-slug q05_c10m_s06r3_el_s45 \
  --to-slug q05_c10m_s06r3_el_s75_cont \
  --to-strain 0.75 \
  --copy-restart-files
```

生成：

- `output/export/{to_slug}/{to_slug}.inp` — 仅含 `*Restart, read` + `CompressionContinue` 步
- `output/export/{to_slug}/{to_slug}_meta.json` — 含 `restart_continue` 字段

### 2.3 提交

```bash
bash scripts/linux/submit_job.sh \
  --slug q05_c10m_s06r3_el_s75_cont \
  --restart-from q05_c10m_s06r3_el_s45 \
  --cpus 48 --memory-mb 262144 \
  --skip-resource-check --background
```

### 2.4 一键（paperbox variant）

```bash
bash scripts/linux/run_paperbox_q05_c10m_s45to75_restart.sh
```

或通用：

```bash
bash scripts/linux/run_paperbox_variant.sh --Q 0.5 \
  --variant-suffix c10m_s06r3_el_s75_cont \
  --short-slug q05_c10m_s06r3_el_s75_cont \
  --restart-from-slug q05_c10m_s06r3_el_s45 \
  --continue-to-strain 0.75 \
  --cpus 48 --memory-mb 262144 \
  --submit-background
```

### 2.5 后处理：合并曲线

续算完成后分别提取 source + continue 的 history CSV，合并：

```python
from src.export.explicit_continue import merge_stress_strain_csv_paths
merge_stress_strain_csv_paths(
    "output/post/s45/s45_stress_strain.csv",
    "output/post/s75_cont/s75_cont_stress_strain.csv",
    "output/post/s75_cont/s75_cont_merged_stress_strain.csv",
    source_meta=..., continue_meta=...,
)
```

---

## 3. 新算例默认行为

| 场景 | 行为 |
|------|------|
| 默认 export | 仍写 `*Restart, write, overlay`（可 `--restart-interval N`） |
| 目标应变未达、源 job 已完成 | 用 `--restart-from-slug` + `--continue-to-strain` |
| 无可用 `.res` | 退化为同网格 `--cae-mesh-inp` 重跑（0→目标应变） |

导出脚本已有 `--restart-interval`；续算选项在 `run_paperbox_variant.sh` / `submit_job.sh`。

---

## 4. s45 → 75% 参数摘要

| 项 | s45（源） | s75_cont（续算段） |
|----|-----------|-------------------|
| 总应变 | 45% | **75%**（累计） |
| 本段应变 | — | **+30%** |
| 本段位移 | — | **24 mm** |
| 本段 step time | 432 s | **288 s** |
| 预计墙钟 | ~11 h（已完成） | **~7 h**（估） |

---

## 5. 相关文件

- `src/export/explicit_continue.py` — 续算段计算、INP 生成、CSV 合并
- `scripts/export_explicit_continue.py` — CLI
- `scripts/linux/backup_case_slug.sh` — 算例备份
- `scripts/linux/submit_job.sh` — `--restart-from`
- `scripts/linux/run_paperbox_variant.sh` — `--restart-from-slug` / `--continue-to-strain`
- `scripts/linux/run_paperbox_q05_c10m_s45to75_restart.sh` — s45→75 示例
