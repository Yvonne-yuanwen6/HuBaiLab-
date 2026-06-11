# Archive BCC fast/fast80 runs that used 25 mm/min + 1.2 mm mesh before 2026-06 re-run.
# Frees canonical slugs (*_fast80, 4x4x4 *_fast) for new defaults (10 mm/min, 0.8 mm mesh).
param(
    [switch]$WhatIf,
    [switch]$SkipFastBase
)

$ErrorActionPreference = "Stop"
$ScriptDir = $PSScriptRoot
$ArchiveTag = "lr25m12"

$fast80Slugs = @(
    "hu_bai_bcc_af2q0_L20_3x3x3_solid_cad_f_fast80",
    "hu_bai_bcc_af2q0_L20_4x4x4_solid_cad_f_fast80"
)

Write-Host "=== Archive legacy BCC fast80 ($ArchiveTag) ===" -ForegroundColor Cyan

foreach ($slug in $fast80Slugs) {
    $args = @(
        "-File", (Join-Path $ScriptDir "archive_case_slug.ps1"),
        "-OldSlug", $slug,
        "-ArchiveTag", $ArchiveTag
    )
    if ($WhatIf) { $args += "-WhatIf" }
    & powershell @args
    if ($LASTEXITCODE -ne 0 -and -not $WhatIf) {
        Write-Host "[WARN] Skipped or missing: $slug" -ForegroundColor Yellow
    }
}

if (-not $SkipFastBase) {
    $fastSlug = "hu_bai_bcc_af2q0_L20_4x4x4_solid_cad_f_fast"
    Write-Host ""
    Write-Host "=== Archive 4x4x4 BCC fast base (clone source, same legacy loading) ===" -ForegroundColor Cyan
    $args = @(
        "-File", (Join-Path $ScriptDir "archive_case_slug.ps1"),
        "-OldSlug", $fastSlug,
        "-ArchiveTag", $ArchiveTag
    )
    if ($WhatIf) { $args += "-WhatIf" }
    & powershell @args
    if ($LASTEXITCODE -ne 0 -and -not $WhatIf) {
        Write-Host "[WARN] Skipped or missing: $fastSlug" -ForegroundColor Yellow
    }
}

Write-Host ""
Write-Host "Done. Re-run BCC fast80 with:" -ForegroundColor Green
Write-Host "  powershell -File scripts/run_bcc_q1_4x4x4_fast80.ps1 -SkipQ1 [-ForceRerun]" -ForegroundColor Cyan
