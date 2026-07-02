# Fig. 3.3 style batch �?repo fast80 profile (80% strain etc. 原文未给); Q values from §2.1
param(
    [switch]$ForceRerun
)

$ErrorActionPreference = "Stop"
$ScriptDir = $PSScriptRoot
$Root = (Resolve-Path (Join-Path $ScriptDir "..")).Path
Set-Location $Root

$slugs = @(
    "hu_bai_sfbls_af2q0p5_L20_3x3x3_solid_cad_f_fast80",
    "hu_bai_sfbls_af2q1_L20_3x3x3_solid_cad_f_fast80",
    "hu_bai_sfbls_af2q1p5_L20_3x3x3_solid_cad_f_fast80"
)

foreach ($slug in $slugs) {
    Write-Host ""
    Write-Host "========== Submit $slug ==========" -ForegroundColor Cyan
    $args = @(
        "-File", (Join-Path $ScriptDir "submit_hu_bai_bcc_solid_cad_compression.ps1"),
        "-SkipExport",
        "-Slug", $slug,
        "-MemoryMB", 8192,
        "-Cpus", 4
    )
    if ($ForceRerun) { $args += "-ForceRerun" }
    & powershell @args
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[ERROR] Failed: $slug" -ForegroundColor Red
        exit $LASTEXITCODE
    }
}

Write-Host ""
Write-Host "All Fig. 3.3 SFBLS fast80 jobs completed." -ForegroundColor Green
