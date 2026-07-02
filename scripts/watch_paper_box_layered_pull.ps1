# Poll server until Q=1.0 / Q=1.5 array STEPs exist, then pull to local staging.
#
#   powershell -File scripts/watch_paper_box_layered_pull.ps1
#   powershell -File scripts/watch_paper_box_layered_pull.ps1 -PollMinutes 5

param(
    [string]$RemoteHost = "art@172.20.200.93",
    [string]$RemoteRoot = "/media/art/file/XiangLang/Lattice/LWY/HuBaiLab",
    [string[]]$Q = @("1.0", "1.5"),
    [int]$PollMinutes = 10,
    [switch]$IncludeZslabs
)

$ErrorActionPreference = "Continue"
$ScriptDir = $PSScriptRoot
$PullScript = Join-Path $ScriptDir "pull_paper_box_array_from_server.ps1"
$LogPath = Join-Path $ScriptDir "..\output\logs\paperbox_layered_pull_watch.log"
New-Item -ItemType Directory -Force -Path (Split-Path $LogPath) | Out-Null

$targets = @{
    "1.0" = "$RemoteRoot/output/cad/_paper_box_array_q1p0/hu_bai_sfbls_af2q1_L20_4x4x4_paper_box_array.step"
    "1.5" = "$RemoteRoot/output/cad/_paper_box_array_q1p5/hu_bai_sfbls_af2q1p5_L20_4x4x4_paper_box_array.step"
}

function Write-Log([string]$Msg) {
    $line = "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] $Msg"
    Add-Content -Path $LogPath -Value $line
    Write-Host $line
}

function Test-RemoteFile([string]$Path) {
    ssh $RemoteHost "test -s '$Path'" 2>$null
    return ($LASTEXITCODE -eq 0)
}

Write-Log "watch start: Q=$($Q -join ',') poll=${PollMinutes}m log=$LogPath"

$ready = @{}
while ($true) {
    $allReady = $true
    foreach ($qVal in $Q) {
        if ($ready.ContainsKey($qVal)) { continue }
        $path = $targets[$qVal]
        if (-not $path) {
            Write-Log "unknown Q=$qVal"
            $ready[$qVal] = $true
            continue
        }
        if (Test-RemoteFile $path) {
            Write-Log "READY Q=$qVal"
            $ready[$qVal] = $true
        }
        else {
            $allReady = $false
            $tail = ssh $RemoteHost "tail -1 $RemoteRoot/output/logs/paperbox_layered_fuse_q$($qVal -replace '\.','p').log 2>/dev/null || tail -1 $RemoteRoot/output/logs/paperbox_layered_fuse.log 2>/dev/null" 2>$null
            Write-Log "waiting Q=$qVal | $tail"
        }
    }

    if ($ready.Count -ge $Q.Count) {
        Write-Log "all targets ready â€?pulling"
        $pullArgs = @(
            "-File", $PullScript,
            "-RemoteHost", $RemoteHost,
            "-RemoteRoot", $RemoteRoot,
            "-Q", $Q
        )
        if ($IncludeZslabs) { $pullArgs += "-IncludeZslabs" }
        & powershell @pullArgs
        $rc = $LASTEXITCODE
        if ($rc -eq 0) {
            Write-Log "pull complete"
            exit 0
        }
        Write-Log "pull failed exit=$rc â€?will retry next poll"
        $ready.Clear()
    }

    Start-Sleep -Seconds ($PollMinutes * 60)
}
