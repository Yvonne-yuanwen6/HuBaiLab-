# Pull equal-area elliptic-strut 4x4x4 paper_box arrays from server for QA.
#
#   powershell -File scripts/pull_ellipse_paper_box_444_from_server.ps1
#   powershell -File scripts/pull_ellipse_paper_box_444_from_server.ps1 -Q 0,0.5,1.0,1.5 -Force

param(
    [string]$RemoteHost = "art@172.20.200.93",
    [string]$RemoteRoot = "/media/art/file/XiangLang/Lattice/LWY/HuBaiLab",
    [string[]]$Q = @("0", "0.5", "1.0", "1.5"),
    [switch]$IncludeSeeds,
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$ScriptDir = $PSScriptRoot
$Root = (Resolve-Path (Join-Path $ScriptDir "..")).Path

if ($Q.Count -eq 1 -and $Q[0] -match ',') {
    $Q = @($Q[0] -split ',' | ForEach-Object { $_.Trim() } | Where-Object { $_ })
}

$VariantByQ = @{
    "0"   = "bcc_af2q0"
    "0.5" = "sfbls_af2q0p5"
    "1.0" = "sfbls_af2q1"
    "1.5" = "sfbls_af2q1p5"
}

function Q-Tag([string]$qVal) {
    return ($qVal -replace '\.', 'p')
}

$pulled = 0
$missing = @()

foreach ($qVal in $Q) {
    $tag = Q-Tag $qVal
    $variant = $VariantByQ[$qVal]
    if (-not $variant) {
        Write-Warning "Unknown Q=$qVal - skip"
        continue
    }

    $localDir = Join-Path $Root "output\cad\_paper_box_array_ellipse_eqarea_q$tag"
    New-Item -ItemType Directory -Force -Path $localDir | Out-Null

    $remoteDir = "$RemoteRoot/output/cad/_paper_box_array_ellipse_eqarea_q$tag"
    $arrayNamePreferred = "hu_bai_${variant}_L20_4x4x4_paper_box_ellipse_eqarea_array.step"
    $arrayNameFallback = "hu_bai_${variant}_L20_4x4x4_paper_box_array.step"
    $manifestName = "hu_bai_${variant}_L20_4x4x4_paper_box_array_manifest.json"

    $files = @(
        @{
            RemoteCandidates = @("$remoteDir/$arrayNamePreferred", "$remoteDir/$arrayNameFallback")
            Local = Join-Path $localDir $arrayNamePreferred
            Required = $true
        },
        @{ RemoteCandidates = @("$remoteDir/$manifestName"); Local = Join-Path $localDir $manifestName; Required = $false }
    )

    if ($IncludeSeeds) {
        $seedName = "unitcell_${variant}_paper_box_ellipse_ellmin_eqarea.step"
        $files += @{
            Remote = "$RemoteRoot/output/cad/_unitcell_paper_box_cut_ellipse_eqarea/$seedName"
            Local  = Join-Path $localDir $seedName
            Required = $false
        }
    }

    Write-Host "=== Q=$qVal -> $localDir ===" -ForegroundColor Cyan

    foreach ($f in $files) {
        $localPath = $f.Local
        if ((Test-Path $localPath) -and -not $Force) {
            $sz = (Get-Item $localPath).Length
            if ($sz -gt 0) {
                Write-Host "  skip (exists): $(Split-Path $localPath -Leaf) ($([math]::Round($sz/1MB,2)) MB)"
                $pulled++
                continue
            }
        }

        $remotePath = $null
        foreach ($candidate in $f.RemoteCandidates) {
            $probe = ssh $RemoteHost "test -s '$candidate' && wc -c < '$candidate'" 2>$null
            if ($probe) {
                $remotePath = $candidate
                break
            }
        }
        if (-not $remotePath) {
            $msg = "  missing: $(Split-Path $localPath -Leaf)"
            if ($f.Required) { $missing += "Q=$qVal $($f.RemoteCandidates -join ' | ')" }
            else { Write-Host $msg -ForegroundColor DarkYellow }
            continue
        }

        $bytes = [int64]($probe.Trim())
        Write-Host "  pull: $(Split-Path $localPath -Leaf) ($([math]::Round($bytes/1MB,2)) MB) ..."
        scp "${RemoteHost}:$remotePath" $localPath | Out-Null
        if (-not (Test-Path $localPath) -or (Get-Item $localPath).Length -lt 1024) {
            if ($f.Required) { $missing += "Q=$qVal pull failed: $localPath" }
            continue
        }
        $pulled++
        Write-Host "  OK: $localPath" -ForegroundColor Green
    }
}

Write-Host ""
if ($missing.Count -gt 0) {
    Write-Host "Not ready or failed:" -ForegroundColor Yellow
    $missing | ForEach-Object { Write-Host "  $_" }
    exit 1
}

Write-Host "Pulled $pulled file(s). Inspect under output\cad\_paper_box_array_ellipse_eqarea_q*\" -ForegroundColor Green
