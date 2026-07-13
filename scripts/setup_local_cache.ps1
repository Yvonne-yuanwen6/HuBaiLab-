# 一次性：把 npm / pip 全局缓存目录改到 D:\HuBaiLab\.cache（可选迁移旧缓存）
# 用法: powershell -ExecutionPolicy Bypass -File D:\HuBaiLab\scripts\setup_local_cache.ps1

. (Join-Path $PSScriptRoot "local_config.ps1")

Write-Host "HuBaiLab 缓存目录 -> $HuBaiCacheRoot" -ForegroundColor Cyan

# npm
if (Get-Command npm -ErrorAction SilentlyContinue) {
    $oldNpm = npm config get cache 2>$null
    npm config set cache $env:NPM_CONFIG_CACHE
    Write-Host "npm cache: $oldNpm -> $env:NPM_CONFIG_CACHE"
} else {
    Write-Host "npm 未在 PATH 中，跳过 npm config" -ForegroundColor Yellow
}

# pip
if (Get-Command pip -ErrorAction SilentlyContinue) {
    pip config set global.cache-dir $env:PIP_CACHE_DIR 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "pip config 写入失败（可忽略）；运行时仍会用 PIP_CACHE_DIR=$($env:PIP_CACHE_DIR)" -ForegroundColor Yellow
    } else {
        Write-Host "pip cache-dir -> $($env:PIP_CACHE_DIR)"
    }
} else {
    Write-Host "pip 未在 PATH 中，跳过 pip config" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "建议：新开 PowerShell 后先执行 . D:\HuBaiLab\scripts\local_config.ps1" -ForegroundColor Green
Write-Host "可选清理 C 盘旧缓存（确认无其他程序在用后）:" -ForegroundColor Gray
Write-Host "  Remove-Item -Recurse -Force `"$env:LOCALAPPDATA\Temp\*`" -ErrorAction SilentlyContinue"
Write-Host "  Remove-Item -Recurse -Force `"$env:LOCALAPPDATA\npm-cache`" -ErrorAction SilentlyContinue"
