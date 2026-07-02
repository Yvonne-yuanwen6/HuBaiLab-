# Fig.3.3 实验曲线 — 精准数字化

手工估点误差大。**推荐用 WebPlotDigitizer 从原图像素级取点**（免费、业界标准）。

## 方法一：WebPlotDigitizer（推荐，最准）

1. 打开 https://automeris.io/WebPlotDigitizer/
2. **Load Image** → 选论文 Fig.3.3 截图（PNG，尽量清晰）
3. **Axes** → 选 **2D (XY) Plot**
4. **校准坐标**（点 plot 区域四角/刻度）：
   - 点 1：`(0.0, 0.00)` — 原点
   - 点 2：`(0.8, 0.04)` — 右上（按图中刻度）
   - 确认 X/Y 轴类型为 **Linear**
5. **新建 4 个 dataset**，分别沿四条彩色曲线取点（建议每条 40–80 点）：
   | Dataset 名称 | 曲线 |
   |--------------|------|
   | `BCC` | 浅蓝 |
   | `AF2Q05` | 深蓝 |
   | `AF2Q1` | 粉 |
   | `AF2Q15` | 红 |
   - 可用 **Automatic line extraction**（选曲线颜色）或手动点选
6. **导出**（二选一）：
   - **File → Export JSON** → 存为 `data/reference/wpd/fig33.json`
   - 或每条曲线 **Export CSV** → 存到 `data/reference/wpd/csv/`
7. 导入仓库并出标准图：

```bash
py -3 scripts/import_webplotdigitizer_fig33.py --json data/reference/wpd/fig33.json
py -3 scripts/plot_hu_bai_fig33_standard.py
```

或 CSV：

```bash
py -3 scripts/import_webplotdigitizer_fig33.py --csv-dir data/reference/wpd/csv
py -3 scripts/plot_hu_bai_fig33_standard.py
```

**保存 WPD 工程**（`.tar`）以便以后修改：`File → Export project (.tar)` → `data/reference/wpd/fig33.tar`

---

## 方法二：Engauge Digitizer（桌面版）

- 下载：https://markummitchell.github.io/engauge-digitizer/
- 同样：校准轴 → 沿曲线取点 → 导出 CSV → 用 `--csv-dir` 导入

---

## 方法三：自动颜色提取（快但需校准）

1. 原图放：`data/reference/hu_bai_fig33_experiment.png`
2. 若叠线不准，先校准 plot 框：

```bash
py -3 scripts/digitize_hu_bai_fig33.py --calibrate
py -3 scripts/digitize_hu_bai_fig33.py --validate
```

3. 与 WPD 结果对比；自动法在 inset 图/图例区域容易出错。

---

## 方法四：论文原始数据（终极）

若 Hu & Bai  thesis / 补充材料有 Fig.3.3 数值表，直接替换 `data/hu_bai_fig33_experiment_traced.json` 中 `points` 即可。

---

## 校验

- 标准图：`output/reports/hu_bai_fig33_experiment_standard.png`
- 自动提取叠图：`output/reports/hu_bai_fig33_digitize_validation.png`（黑线应贴在原图曲线上）
