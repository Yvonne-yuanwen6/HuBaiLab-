# Pull completed equal-area elliptic-strut 4x4x4 paper_box arrays (+ optional seeds).
#
#   powershell -File scripts/pull_ellipse_success_from_server.ps1
#   powershell -File scripts/pull_ellipse_success_from_server.ps1 -IncludeSeeds -Force

param(
    [string]$RemoteHost = "art@172.20.200.93",
    [string]$RemoteRoot = "/media/art/file/XiangLang/Lattice/LWY/HuBaiLab",
    [switch]$IncludeSeeds,
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

function Q-Tag([string]$qVal) { return ($qVal -replace '\.', 'p') }

function Pull-RemoteFile {
    param(
        [string]$RemotePath,
        [string]$LocalPath,
        [bool]$Required = $true,
        [int64]$MinBytes = 10240
    )
    if ((Test-Path $LocalPath) -and -not $Force) {
        $sz = (Get-Item $LocalPath).Length
        if ($sz -gt $MinBytes) {
            Write-Host "  skip (exists): $(Split-Path $LocalPath -Leaf) ($([math]::Round($sz/1MB,2)) MB)"
            return $true
        }
    }
    $probe = ssh $RemoteHost "test -s '$RemotePath' && wc -c < '$RemotePath'" 2>$null
    if (-not $probe) {
        $msg = "  missing: $RemotePath"
        if ($Required) { Write-Host $msg -ForegroundColor Red }
        else { Write-Host $msg -ForegroundColor DarkYellow }
        return $false
    }
    $bytes = [int64]($probe.Trim())
    New-Item -ItemType Directory -Force -Path (Split-Path $LocalPath -Parent) | Out-Null
    Write-Host "  pull: $(Split-Path $LocalPath -Leaf) ($([math]::Round($bytes/1MB,2)) MB) ..."
    scp "${RemoteHost}:$RemotePath" $LocalPath | Out-Null
    if (-not (Test-Path $LocalPath) -or (Get-Item $LocalPath).Length -lt $MinBytes) {
        Write-Host "  FAIL pull: $LocalPath" -ForegroundColor Red
        return $false
    }
    Write-Host "  OK: $LocalPath" -ForegroundColor Green
    return $true
}

$jobs = @(
    # ellmaj (major axis || +Z) — all 4 Q complete
    @{ Align = "ellmaj"; Q = "0";   Variant = "bcc_af2q0";     RemoteDir = "_paper_box_array_ellipse_eqarea_ellmaj_q0";   LocalDir = "_paper_box_array_ellipse_eqarea_ellmaj_q0";   ArrayNames = @("hu_bai_bcc_af2q0_L20_4x4x4_paper_box_ellipse_eqarea_ellmaj_array.step") }
    @{ Align = "ellmaj"; Q = "0.5"; Variant = "sfbls_af2q0p5"; RemoteDir = "_paper_box_array_ellipse_eqarea_ellmaj_q0p5"; LocalDir = "_paper_box_array_ellipse_eqarea_ellmaj_q0p5"; ArrayNames = @("hu_bai_sfbls_af2q0p5_L20_4x4x4_paper_box_ellipse_eqarea_ellmaj_array.step") }
    @{ Align = "ellmaj"; Q = "1.0"; Variant = "sfbls_af2q1";   RemoteDir = "_paper_box_array_ellipse_eqarea_ellmaj_q1p0"; LocalDir = "_paper_box_array_ellipse_eqarea_ellmaj_q1p0"; ArrayNames = @("hu_bai_sfbls_af2q1_L20_4x4x4_paper_box_ellipse_eqarea_ellmaj_array.step") }
    @{ Align = "ellmaj"; Q = "1.5"; Variant = "sfbls_af2q1p5"; RemoteDir = "_paper_box_array_ellipse_eqarea_ellmaj_q1p5"; LocalDir = "_paper_box_array_ellipse_eqarea_ellmaj_q1p5"; ArrayNames = @("hu_bai_sfbls_af2q1p5_L20_4x4x4_paper_box_ellipse_eqarea_ellmaj_array.step") }
    # ellmin (minor axis || +Z) — Q=0, 0.5, 1.0 complete
    @{ Align = "ellmin"; Q = "0";   Variant = "bcc_af2q0";     RemoteDir = "_paper_box_array_ellipse_eqarea_q0";   LocalDir = "_paper_box_array_ellipse_eqarea_q0";   ArrayNames = @("hu_bai_bcc_af2q0_L20_4x4x4_paper_box_ellipse_eqarea_array.step", "hu_bai_bcc_af2q0_L20_4x4x4_paper_box_array.step") }
    @{ Align = "ellmin"; Q = "0.5"; Variant = "sfbls_af2q0p5"; RemoteDir = "_paper_box_array_ellipse_eqarea_q0p5"; LocalDir = "_paper_box_array_ellipse_eqarea_q0p5"; ArrayNames = @("hu_bai_sfbls_af2q0p5_L20_4x4x4_paper_box_ellipse_eqarea_array.step", "hu_bai_sfbls_af2q0p5_L20_4x4x4_paper_box_array.step") }
    @{ Align = "ellmin"; Q = "1.0"; Variant = "sfbls_af2q1";   RemoteDir = "_paper_box_array_ellipse_eqarea_q1p0"; LocalDir = "_paper_box_array_ellipse_eqarea_q1p0"; ArrayNames = @("hu_bai_sfbls_af2q1_L20_4x4x4_paper_box_ellipse_eqarea_ellmin_array.step", "hu_bai_sfbls_af2q1_L20_4x4x4_paper_box_array.step") }
)

$failed = @()
$pulled = 0

foreach ($job in $jobs) {
    $localDir = Join-Path $Root "output\cad\$($job.LocalDir)"
    New-Item -ItemType Directory -Force -Path $localDir | Out-Null
    Write-Host "=== $($job.Align) Q=$($job.Q) -> $localDir ===" -ForegroundColor Cyan

    $remoteDir = "$RemoteRoot/output/cad/$($job.RemoteDir)"
    $gotArray = $false
    $localArray = Join-Path $localDir ($job.ArrayNames[-1])
    foreach ($name in $job.ArrayNames) {
        $remote = "$remoteDir/$name"
        $local = Join-Path $localDir $name
        if (Pull-RemoteFile -RemotePath $remote -LocalPath $local -Required $false) {
            $gotArray = $true
            $localArray = $local
            $pulled++
            break
        }
    }
    if (-not $gotArray) {
        $failed += "$($job.Align) Q=$($job.Q) array"
    }

    if ($IncludeSeeds -and $job.Align -eq "ellmin") {
        $seedDir = "$RemoteRoot/output/cad/_unitcell_paper_box_cut_ellipse_eqarea"
        $seedName = "unitcell_$($job.Variant)_paper_box_ellipse_ellmin_eqarea.step"
        $seedLocal = Join-Path $localDir $seedName
        if (Pull-RemoteFile -RemotePath "$seedDir/$seedName" -LocalPath $seedLocal -Required $false) {
            $pulled++
        }
    }
}

# ellmin seeds (Q=1.0, Q=1.5) in shared seed folder
if ($IncludeSeeds) {
    $seedRoot = Join-Path $Root "output\cad\_unitcell_paper_box_cut_ellipse_eqarea"
    New-Item -ItemType Directory -Force -Path $seedRoot | Out-Null
    Write-Host "=== ellmin seeds ===" -ForegroundColor Cyan
    foreach ($seed in @(
        "unitcell_sfbls_af2q1_paper_box_ellipse_ellmin_eqarea.step",
        "unitcell_sfbls_af2q1p5_paper_box_ellipse_ellmin_eqarea.step",
        "unitcell_bcc_af2q0_paper_box_ellipse_ellmin_eqarea.step",
        "unitcell_sfbls_af2q0p5_paper_box_ellipse_ellmin_eqarea.step"
    )) {
        $remote = "$RemoteRoot/output/cad/_unitcell_paper_box_cut_ellipse_eqarea/$seed"
        $local = Join-Path $seedRoot $seed
        if (Pull-RemoteFile -RemotePath $remote -LocalPath $local -Required $false) {
            if (Test-Path $local) { $pulled++ }
        }
    }
}

Write-Host ""
if ($failed.Count -gt 0) {
    Write-Host "Missing required arrays:" -ForegroundColor Yellow
    $failed | ForEach-Object { Write-Host "  $_" }
    exit 1
}
Write-Host "Pulled $pulled file(s). Inspect under output\cad\" -ForegroundColor Green
