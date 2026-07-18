# HuBaiLab Abaqus Web UI 使用说明

浏览器端操作 **paper_box CAE C3D4 → Explicit 压缩** 工作流：浏览算例、导出 INP、远程提交/监控/终止、后处理应力–应变曲线。

> **维护者**：修改 `frontend/`、`api/` 或 `src/abaqus/` 中与 UI 相关的功能时，请同步更新本文档对应章节。文末 [§9 文档维护清单](#9-文档维护清单) 列出需对照的源文件。

相关 CLI 工作流见 [`本机开发服务器求解工作流.md`](本机开发服务器求解工作流.md)、[`Abaqus_CAD实体压缩说明.md`](Abaqus_CAD实体压缩说明.md)。

---

## 1. 环境准备

| 组件 | 要求 |
|------|------|
| Python | 3.11+，`pip install -r requirements.txt`（含 `fastapi`、`uvicorn`、`pydantic`） |
| Node.js | 18+（本仓库推荐安装于 `D:\nodejs`，见 README） |
| 远程服务器 | 可选；提交/监控/终止/远程删除需 SSH + scp 可达 |
| Abaqus | 导出 INP 若走 `--mesh-on-server` 需在服务器有 CAE 许可证；本机仅浏览可不装 |

**远程连接**（默认读 `src/paths.py`）：

| 变量 / 配置 | 默认值 |
|-------------|--------|
| 主机 | `art@172.20.200.93`（`HUBAI_REMOTE_HOST`） |
| 仓库根 | `/media/art/file/XiangLang/Lattice/LWY/HuBaiLab`（`HUBAI_REMOTE_ROOT`） |
| SSH 私钥 | 环境变量 `HU_BAI_SSH_KEY`（可选） |

---

## 2. 启动方式

### 2.0 首次安装（只需一次）

在 **PowerShell** 中进入仓库根目录（示例路径 `D:\HuBaiLab`，下文均以此为例）：

```powershell
cd D:\HuBaiLab
```

**Python 依赖**（仓库根目录执行）：

```powershell
pip install -r requirements.txt
```

**Node.js**：需 18+。本机若安装在 `D:\nodejs`，新开终端前可先加入 PATH：

```powershell
$env:Path = "D:\nodejs;$env:Path"
node -v    # 应显示 v18+ 
npm -v
```

**前端依赖**（只需在 `frontend/` 首次或 `package.json` 变更后执行）：

```powershell
cd D:\HuBaiLab\frontend
npm install
cd D:\HuBaiLab
```

---

### 2.1 开发模式（日常推荐）

开发模式需要 **两个终端**，后端与前端分别运行；浏览器访问 Vite 开发服务器，API 经代理转发。

| 进程 | 端口 | 作用 |
|------|------|------|
| FastAPI（uvicorn） | **8000** | 算例/任务 API |
| Vite（npm run dev） | **5173** | 页面 + 将 `/api/*` 代理到 8000 |

**终端 1 — 启动 API（必须在仓库根目录）**

```powershell
cd D:\HuBaiLab
$env:PYTHONPATH = "D:\HuBaiLab"
python -m uvicorn api.main:app --reload --port 8000
```

看到 `Uvicorn running on http://127.0.0.1:8000` 即表示 API 就绪。

**终端 2 — 启动前端**

```powershell
cd D:\HuBaiLab\frontend
$env:Path = "D:\nodejs;$env:Path"   # 若 node 不在 PATH
npm run dev
```

看到 `Local: http://localhost:5173/` 后，浏览器打开：

**http://localhost:5173**

> **注意**
> - 两个进程都要保持运行；只开前端会出现算例列表加载失败（无法连 API）。
> - 必须在 **仓库根** 启动 uvicorn，并设置 `PYTHONPATH`，否则找不到 `api/`、`src/` 模块。
> - 开发模式请访问 **5173**，不要只开 8000（8000 在未构建时没有 Vite 热更新页面；若已 `npm run build` 则 8000 也可直接打开静态页，见 §2.2）。

**停止**：在两个终端分别按 `Ctrl+C`。

---

### 2.2 生产 / 单进程（仅 API + 静态页）

适合不需要热更新、只开一个端口的场景：先构建前端，再由 FastAPI 托管 `frontend/dist/`。

```powershell
cd D:\HuBaiLab\frontend
npm run build

cd D:\HuBaiLab
$env:PYTHONPATH = "D:\HuBaiLab"
python -m uvicorn api.main:app --host 0.0.0.0 --port 8000
```

浏览器打开：**http://localhost:8000**（同一端口同时提供页面与 `/api/*`）。

局域网其他机器访问时使用本机 IP，例如 `http://192.168.x.x:8000`（需防火墙放行 8000）。

修改前端代码后须重新 `npm run build` 并重启 uvicorn 才会生效。

---

### 2.3 启动自检

按顺序确认：

1. **API 健康检查**  
   浏览器或 PowerShell：`GET http://localhost:8000/api/health`  
   应返回：`{"status":"ok","api_version":"0.1.0","features":["sync-output",...]}`  
   若只有 `{"status":"ok"}`，说明仍是**旧 API 进程**，请执行 §2.4 重启。

2. **OpenAPI 文档**（可选）  
   http://localhost:8000/docs

3. **前端**  
   - 开发模式：http://localhost:5173 能打开左侧导航（仪表盘、算例、导出 INP…）  
   - 单进程模式：http://localhost:8000 同上  

4. **算例列表**  
   打开「算例」页；若本机 `output/export/` 无历史数据，列表为空属正常，可先走「导出 INP」。

**常见启动问题**

| 现象 | 处理 |
|------|------|
| `ModuleNotFoundError: api` 或 `src` | 在仓库根启动 uvicorn，并设置 `$env:PYTHONPATH = "D:\HuBaiLab"` |
| 前端能开但接口报错 / 列表一直 loading | 确认终端 1 的 API 在 8000 端口运行；开发模式勿只访问 8000 而未 build |
| `node` / `npm` 不是内部命令 | `$env:Path = "D:\nodejs;$env:Path"` 或把 Node 安装目录加入系统 PATH |
| 5173 端口被占用 | 关闭占用进程，或在 `frontend/vite.config.ts` 修改 `server.port` |
| `[WinError 10013]` 端口无法绑定 | 8000 已被占用，见 §2.4 重启 API，不要重复启动第二个 uvicorn |
| 算例列表空白但 API 有数据 | 多为旧 API 进程未重启；执行 §2.4 后刷新浏览器 |

---

### 2.4 重启 API（更新代码后必做）

**推荐一键启动**（自动清理 8000 端口并启动）：

```powershell
powershell -ExecutionPolicy Bypass -File D:\HuBaiLab\scripts\start_webui_api.ps1
```

或手动执行（`<PID>` 是占位符，**不要原样粘贴**）：

```powershell
cd D:\HuBaiLab

Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue |
  Select-Object -ExpandProperty OwningProcess -Unique |
  ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }

$env:PYTHONPATH = "D:\HuBaiLab"
python -m uvicorn api.main:app --reload --port 8000
```

**验证是否为新 API**（必须成功且含 `features`）：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/health
```

- 正常：`status=ok`，`features` 含 `sync-output`
- **404 Not Found**：8000 上仍是旧/僵尸进程 → 关闭所有 uvicorn 终端后重跑 `start_webui_api.ps1`
- 只有 `{"status":"ok"}` 无 `features`：同样是旧 API

看到 `Uvicorn running on http://127.0.0.1:8000` 后，打开 http://localhost:8000/docs ，搜索 `sync-output` 应能看到 `POST /api/abaqus/sync-output`。

---

## 3. 界面概览

左侧导航：

| 页面 | 路径 | 功能 |
|------|------|------|
| 仪表盘 | `/` | 运行中/完成/失败统计、**同步服务器 output** 勾选、活动算例、最近算例 |
| 算例 | `/cases` | 列表、状态/参数标签筛选、多选加入仿真队列 |
| CAD / STEP | `/cad` | 结构/尺寸参数 → 生成 paper_box 阵列 STEP → verified 列表 |
| 导出 INP | `/export` | 分步向导（结构/尺寸/网格）+ 预设；网格步可独立启动任务 |
| 仿真队列 | `/queue` | 串行排队、上移/下移/置顶/置底、开始/暂停 |
| 作业监控 | `/monitor` | 轮询进度、远程同步、远程终止 |
| 回收站 | `/trash` | 已删除算例还原 / 永久清除 |
| COMSOL | — | 占位，尚未实现 |

---

## 4. 典型工作流

```
STEP 生成 → 导出 INP（含网格）→ 加入仿真队列 → 监控 .sta → 同步远程 → 提取曲线 → 查看 σ–ε 图
```

也可跳过队列，在算例详情直接 **提交求解**。

### 4.0 生成 STEP（可选）

1. 打开 **CAD / STEP**
2. 选择结构（BCC / SFBLS）、Q、单胞边长 L、cells、OCP/Gmsh 后端
3. 点击 **开始生成 STEP** → 后台调用 `scripts/run_hu_bai_paper_box_4x4x4_array_fuse.py`
4. 完成后刷新 verified 列表；再到 **导出 INP** 选用

### 4.1 新建算例（导出 INP）

1. 打开 **导出 INP**
2. 左侧点击预设（如 `bcc_q0_baseline`、`sfbls_q05_baseline`、`fast_test`）或逐步填写：
   - **几何**：结构（BCC/SFBLS）、Q、单胞边长 L、杆径、Af、cells、verified STEP
   - **网格**：cae-seed、mesh-quality、单元类型、Virtual Topology、服务器/本机剖分；可点「仅启动网格/导出任务」
   - **载荷**：应变、加载速率、材料、STORE OFFSETS / ContactSettle
   - **计算**：提交目标、CPU/内存
   - **确认**：查看预计 slug / variant
3. 点击 **开始导出 INP** → 后台调用 `scripts/run_hu_bai_bcc_solid_cad_cae_tet_export.py`
4. 完成后自动跳转 **作业监控**

输出目录（与 CLI 一致）：

- `output/export/{slug}/` — INP、`case_manifest.json`、`*_meta.json`
- `output/active_case.json` — 最后一次导出

### 4.2 提交求解 / 仿真队列

**单算例**：在 **算例详情** 点击 **提交求解**（默认远程，48 CPU / 256 GB）。

**排队串行**（等价于 UI 版 `submit_queue.sh`）：

1. 在 **算例** 多选有 INP 的算例 → **加入仿真队列**，或详情页 **加入队列**
2. 打开 **仿真队列**，用上移/下移/置顶/置底调整顺序
3. 点击 **开始**；同一时间只运行一个；完成后自动提交下一个
4. 可 **暂停**（不杀当前作业，仅停止派发下一个）、**清空已完成**

队列状态持久化：`output/logs/ui_sim_queue.json`。

作业文件写入 `output/jobs/{slug}/`

### 4.3 监控进度

1. 打开 **作业监控**，选择或输入 slug
2. 勾选 **远程同步 (.sta/.lck)** — 从服务器 scp 拉取状态文件后再解析
3. 调整轮询间隔（5–60 s，默认 30 s）
4. 查看：状态徽章、进度条、仿真时间、帧数、ETA、KE/IE

状态含义：

| 状态 | 说明 |
|------|------|
| WAITING | 尚无 `.sta` |
| RUNNING | 存在 `.lck` 或进程运行中 |
| COMPLETED | `.sta` 含 `COMPLETED SUCCESSFULLY` 且存在 ODB |
| FAILED | 错误、未正常结束、变形速度超限等 |
| STOPPED | 有 `.sta` 但既非完成也非运行 |

### 4.4 远程终止

- **算例详情** 或 **作业监控** → **远程终止**（仅 RUNNING 时可点）
- 服务器执行 `scripts/linux/stop_paperbox_job.sh {slug}`：`pkill` 匹配进程并删除 `.lck`

### 4.5 后处理

算例 **COMPLETED** 且本地/已同步 ODB 后：

1. **同步远程**（若 ODB 只在服务器）
2. **提取曲线** → `scripts/extract_stress_strain_from_odb.py` → `output/post/{slug}/*_stress_strain.csv`
3. **生成 PNG** → `scripts/plot_stress_strain.py`
4. 在 **结果** Tab 查看 Recharts 应力–应变图

### 4.6 移入回收站

**算例详情** → **移入回收站**（需确认，可选范围）

| 范围 | 说明 |
|------|------|
| **仅本机**（默认） | 移动本机 `output/export|jobs|post/{slug}` → `output/trash/`，**立即返回成功** |
| **本机 + 远程** | 本机同上；远程 SSH 移入服务器 `output/trash/` 在**后台**执行，SSH 失败不会导致本机操作报错 |

若本机无对应目录（数据仅在服务器），选「本机 + 远程」或先在监控页同步后再操作。

### 4.7 数据来源说明

| 页面 | 默认读取 | 如何看到服务器最新状态 |
|------|----------|------------------------|
| 算例列表 | **本机** `output/` | 不会自动 scp；状态来自本机 `.sta/.lck/.odb` |
| **仪表盘** | 本机 `output/` | 勾选 **「同步服务器 output」** 后点刷新：先 `POST /sync-output` scp 状态文件，再纳入服务器 `output/jobs` 算例并统计 |
| 作业监控 | 本机；勾选「远程同步」后 | 每次刷新前 scp 当前 slug 的 `.sta/.lck/_meta.json` |
| 回收站 | 本机 `output/trash/` | 远程 trash 需选「本机+远程」移入时一并处理 |

页顶蓝色提示条会标明当前数据来源。仪表盘勾选会记住到浏览器 localStorage。

---

## 5. 算例详情说明

### 5.1 时间信息

| 字段 | 来源 |
|------|------|
| 导出时间 | `case_manifest.json` / INP 文件时间 |
| 完成时间 | 成功完成时 ODB 修改时间 |
| 墙钟耗时 | `.sta` 中 `WALLCLOCK TIME (SEC)` |
| ODB 大小 | 本地 ODB 文件 |

算例列表与仪表盘支持两类筛选：

| 类型 | 说明 |
|------|------|
| **状态** | 运行中 / 已完成 / 失败 / 已停止 / 等待中；快捷标签 + 多选 |
| **参数标签** | 从 `case_manifest.json` / `*_meta.json` 解析：Q、结构、材料、单元、seed、应变、加载速率、**dt**、步长、阵列、profile、网格 preset；多选下拉，选项旁显示算例数量 |

同一维度内多选为 **或** 关系，不同维度之间为 **且** 关系（例如：材料=Neo-Hooke **且** Q=0）。列表表格增加 **标签** 列展示主要参数。

标签数据来自导出 manifest；仅有 `.sta` 无 manifest 的算例可能没有标签。

---

从 `case_manifest.json` 与 `{slug}_meta.json` 解析为分组表格：

- 几何、网格、材料、载荷与接触、显式续算（若有）

点击 **查看原始 JSON** 可查看完整 manifest/meta。

### 5.3 作业日志 Tab

显示本地 `.sta` 文件尾部（远程需先 **同步远程**）。

---

## 6. 预设模板

| 预设 ID | 用途 |
|---------|------|
| `bcc_q0_baseline` | BCC Q=0 论文基线（seed 0.6、80% 应变、5 mm/min、Neo-Hooke 材料） |
| `sfbls_q05_baseline` | SFBLS Q=0.5 基线 |
| `fast_test` | 快速验证（小应变、elastic、较少资源） |

预设定义：`src/abaqus/settings.py` → `list_presets()`。

---

## 7. HTTP API 速查

前缀：`/api/abaqus`（任务状态：`/api/tasks/{task_id}`）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/dashboard?discover_remote=true` | 仪表盘（纳入远程 jobs 算例） |
| POST | `/sync-output` | 从服务器 scp `.sta/.lck/_meta.json` |
| GET | `/cases?status=RUNNING` | 算例列表（可选按状态过滤） |
| GET | `/cases/{slug}` | 详情 + 参数分组 + 时间 |
| DELETE | `/cases/{slug}?scope=local` | 移入回收站（默认仅本机） |
| GET | `/trash` | 回收站列表 |
| POST | `/trash/{trash_id}/restore` | 还原算例 |
| DELETE | `/trash/{trash_id}` | 永久删除 |
| GET | `/cases/{slug}/curve` | σ–ε CSV JSON |
| GET | `/cad/verified` | verified STEP 列表 |
| POST | `/cad/generate` | 启动 STEP 生成任务（Q/L/cells/backend/mode） |
| GET | `/presets` | 导出预设 |
| POST | `/settings/preview` | 预览 slug / variant |
| POST | `/export` | 启动导出任务 |
| POST | `/mesh` | 启动网格/导出任务（同 export 脚本） |
| GET | `/queue` | 仿真队列状态 |
| POST | `/queue` | 批量加入队列（`slugs`） |
| PATCH | `/queue/reorder` | 按 id 列表重排 |
| POST | `/queue/start` | 开始串行派发 |
| POST | `/queue/pause` | 暂停派发 |
| POST | `/queue/clear-finished` | 清空已完成/失败项 |
| POST | `/queue/{id}/move` | 上移/下移/置顶/置底（`direction`） |
| DELETE | `/queue/{id}` | 移除队列项（running 除外） |
| GET | `/jobs/{slug}/status?sync_remote=` | 作业状态 |
| GET | `/jobs/{slug}/logs` | `.sta` 尾部 |
| POST | `/jobs/{slug}/submit` | 提交求解 |
| POST | `/jobs/{slug}/sync-remote` | scp 同步 |
| POST | `/jobs/{slug}/stop` | 终止（body: `{"target":"remote"}`） |
| POST | `/jobs/{slug}/extract` | ODB → CSV |
| POST | `/jobs/{slug}/plot` | CSV → PNG |

异步任务（导出、CAD、提交、提取等）返回 `task_id`，轮询 `/api/tasks/{task_id}`；状态文件在 `output/logs/ui_tasks/`。队列状态在 `output/logs/ui_sim_queue.json`。

---

## 8. 常见问题

**前端能开但算例列表为空**

- 本机 `output/export/` 无历史算例 → 先走 **导出 INP** 或从服务器同步 `output/`

**提交/终止/删除报 SSH 错误**

- 检查 `ssh art@172.20.200.93` 是否免密或已设 `HU_BAI_SSH_KEY`
- 确认远程 `HUBAI_REMOTE_ROOT` 路径存在且已同步代码

**监控一直 WAITING**

- 作业可能只在服务器运行 → 开启 **远程同步**
- 或尚未提交，只有 INP 无 `.sta`

**提取曲线失败**

- 需本地存在 ODB；先 **同步远程** 或等作业 COMPLETED

**Windows 本机终止无效**

- UI 默认 **远程终止**；本机无 bash 时仅删 `.lck`，进程仍在服务器上

**Node 找不到**

- 确认 `D:\nodejs` 在 PATH，或新开终端使环境变量生效

---

## 9. 文档维护清单

更新 Web UI 功能时，请逐项核对并改本文档：

| 变更类型 | 需更新的文档章节 | 对照源文件 |
|----------|------------------|------------|
| 新页面 / 导航 | §3、§4 | `frontend/src/layout/AppLayout.tsx`、`frontend/src/pages/` |
| 新 API | §7 | `api/routers/abaqus_*.py`、`api/schemas/abaqus.py` |
| 导出参数 / 预设 | §4.1、§6 | `src/abaqus/settings.py`、`frontend/src/components/ExportForm.tsx` |
| 状态 / 时间逻辑 | §4.3、§5.1 | `src/abaqus/job_status.py`、`src/abaqus/case_info.py` |
| 远程操作 | §1、§4.4、§4.6 | `api/services/remote.py`、`src/abaqus/trash.py` |
| 回收站 | §3、§4.6、§7 | `src/abaqus/trash.py`、`frontend/src/pages/Trash.tsx` |
| 启动 / 依赖 | §1、§2 | `requirements.txt`、`frontend/package.json`、`README.md` |

代码入口注释（提醒维护文档）：

- `api/main.py` 模块 docstring
- `frontend/README.md`

---

*最后与代码对齐：2026-07-14 — CAD/STEP 生成、尺寸/结构、网格任务、仿真队列*
