# Pull lightweight job status files from server (sta, meta) for local watch_job_progress.ps1
param(
    [Parameter(Mandatory)][string]$ServerRoot,
    [Parameter(Mandatory)][string]$Slug,
    [switch]$IncludePost
)

$ErrorActionPreference = "Stop"
$LocalRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

if (-not (Test-Path $ServerRoot)) {
    throw "Cannot reach server path: $ServerRoot"
}

$pulls = @(
    @{
        Rel = "output\jobs\$Slug"
        Patterns = @("*.sta", "*.lck", "*.log", "*.dat")
    },
    @{
        Rel = "output\export\$Slug"
        Patterns = @("*_meta.json", "case_manifest.json", "active_case.json")
    }
)

if ($IncludePost) {
    $pulls += @{
        Rel = "output\post\$Slug"
        Patterns = @("*.csv", "*.png", "*.json")
    }
}

Write-Host "=== pull_job_status ===" -ForegroundColor Cyan
Write-Host "  slug:   $Slug"
Write-Host "  server: $ServerRoot"
Write-Host ""

foreach ($p in $pulls) {
    $remote = Join-Path $ServerRoot $p.Rel
    $local = Join-Path $LocalRoot $p.Rel
    if (-not (Test-Path $remote)) {
        Write-Host "  skip (missing): $remote" -ForegroundColor Gray
        continue
    }
    New-Item -ItemType Directory -Force -Path $local | Out-Null
    foreach ($pat in $p.Patterns) {
        Write-Host "  $($p.Rel)\$pat" -ForegroundColor Cyan
        & robocopy $remote $local $pat /R:1 /W:2 /NFL /NDL /NJH /NJS
    }
}

Write-Host ""
Write-Host "Local watch:" -ForegroundColor Green
Write-Host "  .\scripts\watch_job_progress.ps1 -Slug $Slug -UseMeta -PollSeconds 30"
