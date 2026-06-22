# 本机开发 + 服务器求解工作流

在**本机 Windows**改代码、导出 INP，在**Linux 服务器**跑 Abaqus，在本机监控进度。

适用环境示例：

| 项目 | 值 |
|------|-----|
| 本机 | Windows，`D:\HuBaiLab` |
| 服务器 | `art@172.20.200.93` |
| 服务器仓库 | `/home/art/Documents/Lattice/LWY/HuBaiLab` |
| Abaqus | `/home/art/APP/abaqus2022/Commands/abq` |
| 连接方式 | SSH（日常）；VNC 仅看桌面时用 |

---

## 1. 分工一览

```
本机 Windows                         服务器 Linux
─────────────────                    ─────────────────
改 src / scripts                     接收 scp 同步
export INP（Python + gmsh/体素）      abaqus 求解
plot / 分析                          output/jobs/*.sta / *.odb
本机 watch_job_progress.ps1 监控进度
```

| 步骤 | 在哪跑 | 用什么窗口 |
|------|--------|------------|
| export INP | 本机 | `PS D:\HuBaiLab>` |
| scp 传 INP | 本机 | `PS D:\HuBaiLab>` |
| submit 求解 | 服务器 | SSH → `art@ART:...$` |
| 监控进度 | 本机 | `PS D:\HuBaiLab>` |

**不要**把 PowerShell 命令粘到 SSH 里；**不要**在服务器上跑 export（除非服务器 Python 环境已配好）。

---

## 2. 一次性准备

### 2.1 本机

```powershell
cd D:\HuBaiLab
py -3 -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
```

### 2.2 服务器（SSH 登录后做一次）

```bash
ssh art@172.20.200.93

# 确认 Abaqus
export PATH="/home/art/APP/abaqus2022/Commands:$PATH"
abq information=release

# 长期生效（可选）
cd /home/art/Documents/Lattice/LWY/HuBaiLab
bash scripts/linux/setup_abaqus_env.sh
source ~/.bashrc
```

### 2.3 SSH 密钥（可选，免密登录）

```powershell
ssh-keygen -t ed25519
type $env:USERPROFILE\.ssh\id_ed25519.pub | ssh art@172.20.200.93 "mkdir -p ~/.ssh && cat >> ~/.ssh/authorized_keys"
```

### 2.4 CAD 文件（export 必需）

export 只认 **`output/cad/verified/`** 下已确认的 STEP，例如：

- `hu_bai_bcc_af2q0_L20_4x4x4_solid_merged.STEP`
- `hu_bai_sfbls_af2q0p5_L20_4x4x4_solid_merged.STEP`
- `hu_bai_sfbls_af2q1_L20_4x4x4_solid_merged.STEP`
- `hu_bai_sfbls_af2q1p5_L20_4x4x4_solid_merged.STEP`

注意文件名是 **`_solid_merged.STEP`**，不是 `_solid_array.step`。

---

## 3. 算例参数示例：体素 0.8 mm / 75% 应变 / 15 mm/min / 四结构

| 参数 | export 选项 | 值 |
|------|-------------|-----|
| 网格 | `--mesh-method voxel --voxel-pitch 0.8` | 体素 C3D8R，边长 0.8 mm |
| 应变 | `--strain 0.75` | 75% 工程应变 |
| 加载 | `--load-rate-mm-min 15` | 15 mm/min |
| 后缀 | `--case-suffix voxel0p8mm75_15mmin` | slug 命名用 |
| 阵列 | `--cells 4` | 4×4×4 |

四个 slug：

```
hu_bai_bcc_af2q0_L20_4x4x4_solid_cad_f_voxel0p8mm75_15mmin
hu_bai_sfbls_af2q0p5_L20_4x4x4_solid_cad_f_voxel0p8mm75_15mmin
hu_bai_sfbls_af2q1_L20_4x4x4_solid_cad_f_voxel0p8mm75_15mmin
hu_bai_sfbls_af2q1p5_L20_4x4x4_solid_cad_f_voxel0p8mm75_15mmin
```

4×4×4、75% 应变 → 压缩 60 mm；15 mm/min → 步长约 **240 s**。

### 3.1 服务器推荐资源（EPYC 9654 / 1.1 TiB 内存）

| 参数 | 推荐值 | 说明 |
|------|--------|------|
| `--cpus` | **32**（可试 48） | **每次 submit 必须显式传入** |
| `--memory-mb` | **131072**（128 GB） | Abaqus `memory=` 参数，单位 MB |

**重要：** `scripts/linux/submit_job.sh` 的默认值是 **8 核 / 8192 MB（8 GB）**。只写 `bash scripts/linux/submit_job.sh --slug SLUG` 会落到 8 核，不会自动用 32 核。

核数和内存**只能在提交时设定**，job 跑起来之后无法修改。改核数需要停 job、清 `.lck`、重新 submit（或 `--recover`）。

---

## 4. 日常完整流程（逐步说明）

下面按 **A → B → C → D → E** 顺序执行。标了窗口类型：**本机 PS** = `PS D:\HuBaiLab>`；**服务器 SSH** = `art@ART:...$`。

```
A 本机 export INP
    ↓
B 本机 scp 传到服务器
    ↓
C 服务器 tmux → submit（--cpus 32 --memory-mb 131072）→ 验证 ps → Ctrl+B D
    ↓
D 本机 watch_job_progress.ps1（必须 -RemoteHost）
    ↓
E 完成后 scp 拉回 ODB / CSV
```

---

### 步骤 A：本机 export INP

**窗口：** 本机 PS，`PS D:\HuBaiLab>`

```powershell
cd D:\HuBaiLab
$env:PYTHONPATH = (Get-Location).Path

$Suffix = "voxel0p8mm75_15mmin"
$Pitch  = 0.8
$Rate   = 15
$Strain = 0.75

foreach ($Q in @(0, 0.5, 1.0, 1.5)) {
  Write-Host "=== Export Q=$Q ===" -ForegroundColor Cyan
  py -3 scripts/run_hu_bai_bcc_solid_cad_export.py `
    --cells 4 --Q $Q --profile fast `
    --case-suffix $Suffix `
    --mesh-method voxel --voxel-pitch $Pitch `
    --strain $Strain --load-rate-mm-min $Rate
  if ($LASTEXITCODE -ne 0) { throw "Export failed Q=$Q" }
}
```

verified 里已有 `_solid_merged.STEP` 时可**省略** `--cad`（脚本自动查找）。

检查：

```powershell
dir output\export\*voxel0p8mm75_15mmin*
```

每个目录应有 `.inp` 和 `*_meta.json`。

若需指定 CAD 路径（扩展名、文件名要完全一致）：

```powershell
$cases = @(
  @{ Q = 0;   Cad = "output\cad\verified\hu_bai_bcc_af2q0_L20_4x4x4_solid_merged.STEP" },
  @{ Q = 0.5; Cad = "output\cad\verified\hu_bai_sfbls_af2q0p5_L20_4x4x4_solid_merged.STEP" },
  @{ Q = 1.0; Cad = "output\cad\verified\hu_bai_sfbls_af2q1_L20_4x4x4_solid_merged.STEP" },
  @{ Q = 1.5; Cad = "output\cad\verified\hu_bai_sfbls_af2q1p5_L20_4x4x4_solid_merged.STEP" }
)
# 在 export 命令中加 --cad $c.Cad
```

---

### 步骤 B：本机 scp 传到服务器

**窗口：** 本机 PS（**不要**先 ssh 进服务器）

```powershell
$Server = "art@172.20.200.93"
$Remote = "/home/art/Documents/Lattice/LWY/HuBaiLab"
$Local  = "D:\HuBaiLab"
$Suffix = "voxel0p8mm75_15mmin"

$Slugs = @(
  "hu_bai_bcc_af2q0_L20_4x4x4_solid_cad_f_$Suffix",
  "hu_bai_sfbls_af2q0p5_L20_4x4x4_solid_cad_f_$Suffix",
  "hu_bai_sfbls_af2q1_L20_4x4x4_solid_cad_f_$Suffix",
  "hu_bai_sfbls_af2q1p5_L20_4x4x4_solid_cad_f_$Suffix"
)

# 同步 Linux 提交脚本（改过代码时）
scp -r "$Local\scripts\linux" "${Server}:${Remote}/scripts/"

foreach ($s in $Slugs) {
  ssh $Server "mkdir -p ${Remote}/output/export/${s}"
  scp -r "$Local\output\export\$s\*" "${Server}:${Remote}/output/export/${s}/"
  Write-Host "pushed $s" -ForegroundColor Green
}
```

服务器上确认：

```bash
ls /home/art/Documents/Lattice/LWY/HuBaiLab/output/export/*voxel0p8mm75_15mmin*/*.inp
```

---

### 步骤 C：服务器提交求解

**窗口：** 服务器 SSH → **必须先进入 tmux**，再在 tmux 里 submit。

#### C.1 本机打开 SSH

```powershell
ssh art@172.20.200.93
```

#### C.2 进入 tmux（在 submit **之前**）

tmux 的作用：SSH 断开、本机 PowerShell 关闭后，job 仍在服务器上跑。

```bash
# 已有会话
tmux attach -t abq

# 没有会话则新建（底部应出现绿色状态条 [abq] 0:bash*）
tmux new -s abq
```

| 操作 | 按键 / 命令 | 说明 |
|------|-------------|------|
| 挂到后台（可关 SSH） | `Ctrl+B`，松手，再按 `D` | **detach**，job 继续跑 |
| 重新连回 | `ssh ...` 后 `tmux attach -t abq` | |
| 列出会话 | `tmux ls` | |

**注意：**

- job 已经在当前 shell 前台跑起来之后，**无法再“搬进”tmux**。只能守着窗口跑完，或停掉重提。
- Abaqus 刷屏时 **不要按 `Ctrl+C`**（会发 SIGINT，job 中断）。要挂后台用 `Ctrl+B` `D`。
- 每个 case 预计 15–30+ 分钟，**串行四个 case 务必全程在 tmux 里**。

#### C.3 停掉旧任务 / 清理僵尸进程（重跑或中断后）

仅在需要重跑、或 job 已失败但进程还在时执行：

```bash
cd /home/art/Documents/Lattice/LWY/HuBaiLab
export PATH="/home/art/APP/abaqus2022/Commands:$PATH"

SLUG=hu_bai_bcc_af2q0_L20_4x4x4_solid_cad_f_voxel0p8mm75_15mmin

# 1) 杀掉 explicit MPI 进程（比 pkill job= 更可靠）
pkill -9 -f "explicit.*${SLUG}" || true

# 2) 若有卡住的 submit_job.sh / SMAPython（状态 T）
pkill -9 -f "submit_job.sh.*${SLUG}" || true
pkill -9 -f "SMAPython.*${SLUG}" || true

sleep 2

# 3) 确认无残留
ps aux | grep "${SLUG}" | grep -E 'explicit|SMAPython' | grep -v grep
# 应无输出

# 4) 删锁文件（否则新 submit 会挂起）
rm -f output/jobs/${SLUG}/${SLUG}.lck
```

#### C.4 提交求解（必须带 `--cpus` 和 `--memory-mb`）

在 **tmux 内**执行：

```bash
cd /home/art/Documents/Lattice/LWY/HuBaiLab
export PATH="/home/art/APP/abaqus2022/Commands:$PATH"

CPUS=32
MEM=131072    # 128 GB

SLUGS=(
  hu_bai_bcc_af2q0_L20_4x4x4_solid_cad_f_voxel0p8mm75_15mmin
  hu_bai_sfbls_af2q0p5_L20_4x4x4_solid_cad_f_voxel0p8mm75_15mmin
  hu_bai_sfbls_af2q1_L20_4x4x4_solid_cad_f_voxel0p8mm75_15mmin
  hu_bai_sfbls_af2q1p5_L20_4x4x4_solid_cad_f_voxel0p8mm75_15mmin
)

for s in "${SLUGS[@]}"; do
  echo "========== $s cpus=$CPUS mem=${MEM}MB =========="
  bash scripts/linux/submit_job.sh --slug "$s" --cpus "$CPUS" --memory-mb "$MEM"
done
```

`for` 循环会**串行**：前一个 `COMPLETED` 后才会提交下一个。若只想跑一个：

```bash
bash scripts/linux/submit_job.sh \
  --slug hu_bai_bcc_af2q0_L20_4x4x4_solid_cad_f_voxel0p8mm75_15mmin \
  --cpus 32 --memory-mb 131072
```

**等当前 job 跑完后自动串行多个 case**（例如 BCC 快结束时挂上后面三个 SFBLS）：

```bash
bash scripts/linux/submit_queue.sh \
  --wait-for hu_bai_bcc_af2q0_L20_4x4x4_solid_cad_f_voxel0p8mm75_15mmin \
  --cpus 32 --memory-mb 131072 \
  --slugs-csv "hu_bai_sfbls_af2q0p5_L20_4x4x4_solid_cad_f_voxel0p8mm75_15mmin,hu_bai_sfbls_af2q1_L20_4x4x4_solid_cad_f_voxel0p8mm75_15mmin,hu_bai_sfbls_af2q1p5_L20_4x4x4_solid_cad_f_voxel0p8mm75_15mmin"
```

`--wait-for` 会每 30 s 检查 `.lck`，当前 job 结束后自动按顺序 submit 列表中的 slug。在 tmux 里跑完后 `Ctrl+B` `D` 即可关 SSH。

#### C.5 提交后立刻验证核数（约 1 分钟后，必做）

```bash
SLUG=hu_bai_bcc_af2q0_L20_4x4x4_solid_cad_f_voxel0p8mm75_15mmin

# 进程命令行应含 -cpus 32 -ppn 32，而不是 8
ps aux | grep explicit | grep "$SLUG" | grep -v grep | head -1

# .sta 里应出现 32 processors（预处理完成后）
grep parallel output/jobs/${SLUG}/${SLUG}.sta | tail -2
```

若仍是 `-cpus 8`：说明没传参或旧进程未清干净 → `Ctrl+C` 停掉错误 submit → 回到 C.3 清理 → 重新 C.4。

**不要只看 `.com` 文件：** 若 job 已在跑时再次 submit，`.com` 可能被覆盖成 32 核，但实际跑的仍是旧 8 核进程。以 `ps aux` 为准。

#### C.6 挂 tmux 到后台

Abaqus 开始刷屏后：

1. `Ctrl+B` → `D`（detach）
2. 可关闭 SSH / PowerShell
3. 需要看输出时：`ssh ...` → `tmux attach -t abq`

#### C.7 中断后续跑（`--recover`）

若 job 在中途被打断（`.sta` 出现 `SIGTERM` / `SIGINT`），且已有 restart 文件，可续算：

```bash
bash scripts/linux/submit_job.sh \
  --slug hu_bai_bcc_af2q0_L20_4x4x4_solid_cad_f_voxel0p8mm75_15mmin \
  --cpus 32 --memory-mb 131072 --recover
```

先完成 C.3 清理，再在 tmux 里 recover。续算同样用 C.5 验证 `-cpus 32`。

---

### 步骤 D：本机监控进度（进度条 + ETA）

**窗口：** 本机 PowerShell #2，`PS D:\HuBaiLab>`。

**监控服务器上的 job 时，必须加 `-RemoteHost` 和 `-RemoteRoot`**。脚本会每 30 s 经 SSH 拉取服务器 `.sta`，否则会读本机 `output/jobs/` 里的旧文件，进度会**卡住不动**。

```powershell
cd D:\HuBaiLab
.\scripts\watch_job_progress.ps1 `
  -RemoteHost "art@172.20.200.93" `
  -RemoteRoot "/home/art/Documents/Lattice/LWY/HuBaiLab" `
  -SlugQueueCsv "hu_bai_bcc_af2q0_L20_4x4x4_solid_cad_f_voxel0p8mm75_15mmin,hu_bai_sfbls_af2q0p5_L20_4x4x4_solid_cad_f_voxel0p8mm75_15mmin,hu_bai_sfbls_af2q1_L20_4x4x4_solid_cad_f_voxel0p8mm75_15mmin,hu_bai_sfbls_af2q1p5_L20_4x4x4_solid_cad_f_voxel0p8mm75_15mmin" `
  -UseMeta -PollSeconds 30
```

只监控**一个** slug 时：

```powershell
.\scripts\watch_job_progress.ps1 `
  -RemoteHost "art@172.20.200.93" `
  -RemoteRoot "/home/art/Documents/Lattice/LWY/HuBaiLab" `
  -Slug hu_bai_bcc_af2q0_L20_4x4x4_solid_cad_f_voxel0p8mm75_15mmin `
  -UseMeta -PollSeconds 30
```

输出示例：

```
[##########------------------------------]  25.0%  sim  60.0/240 s  strain ~18.8%  wall 00:05:12  ETA~14:32
  frame 12/50
  explicit_procs=32
```

- 某个 slug `COMPLETED` 后自动看队列中下一个
- 四个都结束后显示 `Queue watch finished`
- **仅当 job 在本机 Windows 上跑 Abaqus 时**才省略 `-RemoteHost` / `-RemoteRoot`

---

### 步骤 E：完成后拉回结果

**窗口：** 本机 PS

```powershell
$Server = "art@172.20.200.93"
$Remote = "/home/art/Documents/Lattice/LWY/HuBaiLab"
$Local  = "D:\HuBaiLab"
$Slug   = "hu_bai_bcc_af2q0_L20_4x4x4_solid_cad_f_voxel0p8mm75_15mmin"

# 轻量：只拉 .sta
New-Item -ItemType Directory -Force -Path "$Local\output\jobs\$Slug" | Out-Null
scp "${Server}:${Remote}/output/jobs/${Slug}/${Slug}.sta" "$Local\output\jobs\$Slug\"

# 完整 ODB（很大，按需）
scp "${Server}:${Remote}/output/jobs/${Slug}/${Slug}.odb" "$Local\output\jobs\$Slug\"
```

本机有 Abaqus 2025、服务器为 2022 时：先 `scp` ODB，再在本机 **upgrade** 后 extract：

```powershell
cd D:\HuBaiLab\output\jobs\SLUG
abaqus upgrade job=up odb=SLUG.odb   # 生成 up.odb

cd D:\HuBaiLab
abaqus python scripts\extract_stress_strain_from_odb.py `
  --odb output\jobs\SLUG\up.odb `
  --meta output\export\SLUG\SLUG_meta.json `
  --csv output\post\SLUG\SLUG_stress_strain.csv `
  --raw-csv output\post\SLUG\SLUG_stress_strain_raw.csv `
  --yield-json output\post\SLUG\SLUG_yield.json `
  --force-mode paper --curve-method paper

py -3 scripts\plot_stress_strain.py `
  --csv output\post\SLUG\SLUG_stress_strain.csv `
  --png output\post\SLUG\SLUG_stress_strain.png
```

或在服务器用 `scripts/linux/extract_post.sh`（需 Abaqus Python 3；2022 默认 Python 2 会语法错误，优先本机 upgrade + extract）。

---

## 5. 窗口对照表

| 窗口 | 怎么开 | 提示符 | 做什么 |
|------|--------|--------|--------|
| 本机 PowerShell #1 | Cursor 终端 / Win PowerShell | `PS D:\HuBaiLab>` | export、scp |
| 本机 PowerShell #2 | 再开一个 | `PS D:\HuBaiLab>` | `watch_job_progress.ps1`（进度条 + ETA） |
| 服务器 SSH | `ssh art@172.20.200.93` | `art@ART:...$` | tmux + submit |
| VNC | `ssh -N -L 6666:localhost:5903 art@...` + RealVNC | — | 仅看 Linux 桌面 |

---

## 6. SSH 粘贴技巧

| 问题 | 处理 |
|------|------|
| `Ctrl+V` 无效 | 用 **右键粘贴** 或 **Ctrl+Shift+V** |
| 出现 `[200~`、`^M` | Windows 换行/bracketed paste 冲突；改右键粘贴，或一次粘少量 |
| tmux 里粘不上 | 先 `printf '\e[?2004l'`，再粘贴 |
| 完全粘不上 | 本机 PowerShell 用 `ssh art@... "bash -s" @' ... '@` 远程执行 |

---

## 7. 状态判断

| 现象 | 含义 | 处理 |
|------|------|------|
| 存在 `*.lck` | job 占用中（正在跑或异常未清） | 等完成，或 C.3 清理后重提 |
| `.sta` 里 STEP TIME / frame 增加 | 正常推进 | 继续等 |
| `.sta` 含 `COMPLETED SUCCESSFULLY` | 成功完成 | 进入步骤 E |
| `.sta` 含 `NOT BEEN COMPLETED` | 失败 | 查 `.msg` / `.dat`，修复后重提 |
| `.sta` 含 `SIGTERM` / `SIGINT` | 被 Ctrl+C 或 kill 打断 | C.3 清理 → C.7 recover 或重跑 |
| `ps` 有 explicit 但 `.sta` 不再更新 | 僵尸 MPI 进程 | C.3 `pkill -9` 后删 `.lck` |
| 本机监控百分比长时间不变 | 多半未加 `-RemoteHost` | 步骤 D 加上远程参数 |
| `ps` 显示 `-cpus 8` | 用了默认 8 核 | 停掉 → C.3 → C.4 带 `--cpus 32` |
| job 在跑时又 submit 一次 | 新 submit 挂起（状态 `T`） | 不要重复 submit；清僵尸进程 |
| Abaqus 刷屏里的 `DeepPenet` WARNING | 压缩后期接触穿透警告 | 通常可忽略，只要还在出 frame |

服务器上快速看进度：

```bash
tail -5 output/jobs/SLUG/SLUG.sta
ps aux | grep explicit | grep SLUG | grep -v grep | wc -l   # MPI 进程数
```

---

## 8. 常见问题

### Q：export 报 `FileNotFoundError` verified CAD？

`output/cad/verified/` 下缺少 STEP，或 `--cad` 写成了不存在的 `_solid_array.step`。改用 `_solid_merged.STEP` 或省略 `--cad`。

### Q：服务器 pip 装不上依赖？

**只做求解不需要 pip**。export 在本机完成，服务器只需 Abaqus + INP。

### Q：如何改 cpus / memory？

**只能在 submit 时指定**，跑起来后改不了；**不用改 INP**：

```bash
bash scripts/linux/submit_job.sh --slug SLUG --cpus 32 --memory-mb 131072
```

显式 **自动时间步**（去掉 `direct user control`，`--explicit-dt` 作上限）：

```powershell
# 本机 export 示例：Q=0.5, 80% 应变, 15 mm/min, 0.8 mm 体素
py -3 scripts/run_hu_bai_bcc_solid_cad_export.py `
  --cells 4 --Q 0.5 --profile fast `
  --case-suffix voxel0p8mm80_15mmin_autodt `
  --mesh-method voxel --voxel-pitch 0.8 `
  --strain 0.80 --load-rate-mm-min 15 `
  --explicit-dt 0.0005 --explicit-dt-mode automatic
```

当前 job 跑完后自动提交下一个：

```bash
bash scripts/linux/submit_after_wait.sh \
  --wait-for hu_bai_sfbls_af2q1p5_L20_4x4x4_solid_cad_f_voxel0p8mm75_15mmin \
  --cpus 32 --memory-mb 131072 \
  --slug hu_bai_sfbls_af2q0p5_L20_4x4x4_solid_cad_f_voxel0p8mm80_15mmin_autodt
```

提交后用 `ps aux | grep explicit | grep SLUG` 确认命令行里是 `-cpus 32 -ppn 32`。

### Q：忘了开 tmux，job 已经在前台跑了，还能开 tmux 吗？

不能。已绑在当前 shell 的进程无法事后迁入 tmux。若只剩几个 frame，可守着窗口跑完；否则停掉（C.3）后在 tmux 里 `--recover` 或重提。

### Q：本机监控一直卡在同一个百分比？

检查是否省略了 `-RemoteHost` / `-RemoteRoot`。服务器 job 必须用步骤 D 的远程监控命令。

### Q：为什么 `.com` 写 32 核但 `ps` 是 8 核？

job 已在跑时再次 submit 会覆盖 `.com` 但不会替换正在跑的进程。以 `ps aux` 为准。

### Q：如何同步代码到服务器？

```powershell
scp -r D:\HuBaiLab\src D:\HuBaiLab\scripts art@172.20.200.93:/home/art/Documents/Lattice/LWY/HuBaiLab/
```

（LAN UNC 共享可用 `scripts/sync_to_server.ps1`；SSH 环境用 scp。）

### Q：VNC 隧道（可选）

```powershell
ssh -N -L 6666:localhost:5903 art@172.20.200.93
```

RealVNC 连接 `localhost:6666`。日常传文件、跑仿真用 SSH 即可，不必开 VNC。

---

## 9. 相关脚本

| 脚本 | 用途 |
|------|------|
| `scripts/run_hu_bai_bcc_solid_cad_export.py` | 本机 export INP |
| `scripts/linux/submit_job.sh` | 服务器提交单 job |
| `scripts/linux/submit_queue.sh` | 服务器串行多 job（可选 `--wait-for` 等前一个结束） |
| `scripts/watch_job_progress.ps1` | 本机进度条 + ETA（加 `-RemoteHost` / `-RemoteRoot` 监控服务器） |
| `scripts/sync_to_server.ps1` | LAN UNC 同步代码（非 SSH） |
| `scripts/run_voxel1mm80_25mmin_queue_bcc_q05_q15.ps1` | 本机全自动队列（含本机 submit，SSH 工作流勿用） |

---

## 10. 快速检查清单

**准备**

- [ ] 本机 `output/cad/verified/` 有四个 `_solid_merged.STEP`
- [ ] 本机 export 完成，`output/export/*voxel0p8mm75_15mmin/` 有 `.inp` 和 `*_meta.json`
- [ ] scp 到服务器，`ls output/export/.../*.inp` 有文件
- [ ] 服务器 `abq information=release` 正常

**提交（服务器 tmux 内）**

- [ ] 已 `tmux attach -t abq` 或 `tmux new -s abq`（在 submit **之前**）
- [ ] `submit_job.sh` 带了 **`--cpus 32 --memory-mb 131072`**（不是默认 8 核）
- [ ] `ps aux | grep explicit` 显示 **`-cpus 32 -ppn 32`**
- [ ] `grep parallel .../*.sta` 显示 **32 processors**
- [ ] 已 `Ctrl+B` `D` detach，SSH 可关

**监控（本机 PowerShell）**

- [ ] `watch_job_progress.ps1` 带了 **`-RemoteHost` 和 `-RemoteRoot`**
- [ ] 进度百分比 / frame 在更新（不是长时间冻结）

**收尾**

- [ ] 四个 slug 的 `.sta` 均为 `COMPLETED SUCCESSFULLY`
- [ ] 拉 ODB / CSV（步骤 E），本机后处理或画图
