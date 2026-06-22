# output/ 目录说明

本仓库为 Hu & Bai 专用。Git 中**只提交目录骨架**；STEP、ODB、INP、曲线等算例数据请通过组内压缩包分发，解压到本目录即可。

## 目录布局

```
output/
├── active_case.json          # 最近一次实体压缩导出的算例索引（运行后生成）
├── cad/                      # 融合实体 STEP + SW 校验 manifest
├── export/{slug}/            # INP、CSV、case_manifest、meta
├── jobs/{slug}/              # Abaqus 作业目录（INP 副本、ODB）
├── post/{slug}/              # 应力–应变曲线 CSV / PNG / yield
├── failed/{slug}/{timestamp}/ # 崩溃/未完成归档（jobs/ + post/ + failure_manifest.json）
│   ├── jobs/                 # 该次 run 的 ODB、.sta 等（move，与 run 一一对应）
│   ├── compression_meta.json # 归档时快照的 export meta
│   ├── post/                 # 从 jobs/*.odb 当场 extract（不再拷贝共享 post/）
│   └── failure_manifest.json
└── previews/                 # 线框预览 PNG（preview 脚本）
```

完整命名规则见根目录 [`README.md`](../README.md#命名规则)。

## 组员接入已有算例

将收到的 `output` 压缩包解压，确保覆盖到 `HuBaiLab/output/`（保留上述子目录结构）。然后可直接：

```powershell
powershell -File scripts/submit_hu_bai_bcc_solid_cad_compression.ps1 `
  -SkipExport -Slug hu_bai_bcc_af2q0_L20_3x3x3_solid_cad_f_fast -ForceSkip
```
