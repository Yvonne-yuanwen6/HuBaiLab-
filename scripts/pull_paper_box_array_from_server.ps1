# Pull paper-box 4x4x4 array STEP (+ manifest, z-slabs) from server to local staging.
# Does NOT write into output/cad/verified/ — copy there manually after QA.
#
#   powershell -File scripts/pull_paper_box_array_from_server.ps1
#   powershell -File scripts/pull_paper_box_array_from_server.ps1 -Q 1.0,1.5
#   powershell -File scripts/pull_paper_box_array_from_server.ps1 -IncludeZslabs

param(
    [string]$RemoteHost = "art@172.20.200.93",
    [string]$RemoteRoot = "/home/art/Documents/Lattice/LWY/HuBaiLab",
    [string[]]$Q = @("1.0", "1.5"),
    [switch]$IncludeZslabs,
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$ScriptDir = $PSScriptRoot
$Root = (Resolve-Path (Join-Path $ScriptDir "..")).Path

if ($Q.Count -eq 1 -and $Q[0] -match ',') {
    $Q = @($Q[0] -split ',' | ForEach-Object { $_.Trim() } | Where-Object { $_ })
}

$VariantByQ = @{
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
        Write-Warning "Unknown Q=$qVal — skip"
        continue
    }

    $localDir = Join-Path $Root "output\cad\_paper_box_array_q$tag"
    New-Item -ItemType Directory -Force -Path $localDir | Out-Null

    $remoteDir = "$RemoteRoot/output/cad/_paper_box_array_q$tag"
    $arrayName = "hu_bai_${variant}_L20_4x4x4_paper_box_array.step"
    $manifestName = "hu_bai_${variant}_L20_4x4x4_paper_box_layered_manifest.json"

    $files = @(
        @{ Remote = "$remoteDir/$arrayName"; Local = Join-Path $localDir $arrayName; Required = $true },
        @{ Remote = "$remoteDir/$manifestName"; Local = Join-Path $localDir $manifestName; Required = $false }
    )

    if ($IncludeZslabs) {
        foreach ($iz in 0..3) {
            $zname = "zslab_iz${iz}_4x4_paper_box_fused.step"
            $files += @{
                Remote = "$remoteDir/$zname"
                Local  = Join-Path $localDir $zname
                Required = $false
            }
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

        $probe = ssh $RemoteHost "test -s '$($f.Remote)' && wc -c < '$($f.Remote)'" 2>$null
        if (-not $probe) {
            $msg = "  missing: $(Split-Path $localPath -Leaf)"
            if ($f.Required) { $missing += "Q=$qVal $($f.Remote)" }
            else { Write-Host $msg -ForegroundColor DarkYellow }
            continue
        }

        $bytes = [int64]($probe.Trim())
        Write-Host "  pull: $(Split-Path $localPath -Leaf) ($([math]::Round($bytes/1MB,2)) MB) ..."
        scp "${RemoteHost}:$($f.Remote)" $localPath | Out-Null
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

Write-Host "Pulled $pulled file(s). Inspect under output\cad\_paper_box_array_q*\" -ForegroundColor Green
Write-Host "After QA, copy into output\cad\verified\ manually." -ForegroundColor DarkGray
