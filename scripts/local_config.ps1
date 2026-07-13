# HuBaiLab 本机路径：算例数据、临时文件、pip/npm 缓存统一放在 D 盘仓库下，避免占用 C:
# 用法（PowerShell 会话开头）:
#   . D:\HuBaiLab\scripts\local_config.ps1
# 或由 remote_config.ps1 / start_webui_api.ps1 自动 dot-source。

$Root = if ($env:HU_BAI_PROJECT_ROOT) { $env:HU_BAI_PROJECT_ROOT } else { "D:\HuBaiLab" }
$CacheRoot = if ($env:HU_BAI_CACHE_ROOT) { $env:HU_BAI_CACHE_ROOT } else { Join-Path $Root ".cache" }

$TempDir = Join-Path $CacheRoot "temp"
$PipCache = Join-Path $CacheRoot "pip"
$NpmCache = Join-Path $CacheRoot "npm"

foreach ($d in @($TempDir, $PipCache, $NpmCache)) {
    if (-not (Test-Path $d)) {
        New-Item -ItemType Directory -Path $d -Force | Out-Null
    }
}

$env:HU_BAI_PROJECT_ROOT = $Root
$env:HU_BAI_CACHE_ROOT = $CacheRoot
$env:HU_BAI_FORCE_LOCAL_CACHE = "1"
$env:TEMP = $TempDir
$env:TMP = $TempDir
$env:PIP_CACHE_DIR = $PipCache
$env:NPM_CONFIG_CACHE = $NpmCache
$env:PYTHONPATH = $Root

$HuBaiProjectRoot = $Root
$HuBaiCacheRoot = $CacheRoot
$HuBaiTempDir = $TempDir
