# Archive a completed case by renaming export/jobs/post directories and inner files.
# Usage:
#   powershell -File scripts/archive_case_slug.ps1 -OldSlug hu_bai_bcc_af2q0_L20_4x4x4_solid_cad_f_fast80 -ArchiveTag lr25m12
param(
    [Parameter(Mandatory = $true)]
    [string]$OldSlug,
    [string]$ArchiveTag = "lr25m12",
    [switch]$WhatIf
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$NewSlug = "${OldSlug}_${ArchiveTag}"

function Test-SlugDir {
    param([string]$Base, [string]$Slug)
    Test-Path (Join-Path $Root "output\$Base\$Slug")
}

function Rename-SlugTree {
    param([string]$Base)
    $oldDir = Join-Path $Root "output\$Base\$OldSlug"
    $newDir = Join-Path $Root "output\$Base\$NewSlug"
    if (-not (Test-Path $oldDir)) { return $false }

    if (Test-Path $newDir) {
        throw "Archive target already exists: output\$Base\$NewSlug"
    }

    Write-Host "  [$Base] $OldSlug -> $NewSlug"
    if ($WhatIf) { return $true }

    Rename-Item -LiteralPath $oldDir -NewName $NewSlug

    Get-ChildItem -LiteralPath $newDir -File | ForEach-Object {
        if ($_.Name -like "*$OldSlug*") {
            $newName = $_.Name.Replace($OldSlug, $NewSlug)
            if ($newName -ne $_.Name) {
                Rename-Item -LiteralPath $_.FullName -NewName $newName
            }
        }
    }

    Get-ChildItem -LiteralPath $newDir -File -Filter "*.json" | ForEach-Object {
        $text = [System.IO.File]::ReadAllText($_.FullName)
        if ($text.Contains($OldSlug)) {
            $updated = $text.Replace($OldSlug, $NewSlug)
            [System.IO.File]::WriteAllText($_.FullName, $updated, (New-Object System.Text.UTF8Encoding $false))
        }
    }
    return $true
}

Write-Host "=== Archive case slug ===" -ForegroundColor Cyan
Write-Host "  Old: $OldSlug"
Write-Host "  New: $NewSlug"
if ($WhatIf) { Write-Host "  (WhatIf â€?no changes)" -ForegroundColor Yellow }

$moved = @()
foreach ($base in @("export", "jobs", "post")) {
    if (Rename-SlugTree -Base $base) { $moved += $base }
}

if ($moved.Count -eq 0) {
    Write-Host "[WARN] No output directories found for $OldSlug" -ForegroundColor Yellow
    exit 1
}

Write-Host "Archived under: $($moved -join ', ')" -ForegroundColor Green
