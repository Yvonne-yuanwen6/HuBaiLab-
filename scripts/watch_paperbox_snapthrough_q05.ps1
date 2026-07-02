# Live terminal monitor: Q0.5 snap-through sweep (pull .sta locally each poll).
param(
    [string]$RemoteHost = "art@172.20.200.93",
    [string]$RemoteRoot = "/media/art/file/XiangLang/Lattice/LWY/HuBaiLab",
    [string]$LocalRoot = "D:\HuBaiLab",
    [double]$StepTimeS = 768.0,
    [double]$TargetStrain = 0.8,
    [int]$PollSeconds = 30
)

$ErrorActionPreference = "SilentlyContinue"
$ScriptDir = $PSScriptRoot
. (Join-Path $ScriptDir "submit_helpers.ps1")

$TrackJobs = @(
    @{ Label = "Q0.5 B nosettle"; Tag = "sfbls_af2q0p5"; Suffix = "cae_tet0p6mm80_5mmin_paperbox_paperbox_nosettle" },
    @{ Label = "Q1.0 B nosettle"; Tag = "sfbls_af2q1";   Suffix = "cae_tet0p6mm80_5mmin_paperbox_paperbox_nosettle" },
    @{ Label = "Q0.5 C settle5p"; Tag = "sfbls_af2q0p5"; Suffix = "cae_tet0p6mm80_5mmin_paperbox_paperbox_settle5p" },
    @{ Label = "Q0.5 D dt1e-4";  Tag = "sfbls_af2q0p5"; Suffix = "cae_tet0p6mm80_5mmin_paperbox_paperbox_nosettle_dt1e4" },
    @{ Label = "Q0.5 E nohold";   Tag = "sfbls_af2q0p5"; Suffix = "cae_tet0p6mm80_5mmin_paperbox_paperbox_nosettle_dt1e4_nohold" }
)

function Parse-StaLine {
    param([string]$Line)
    if ($Line -match 'Output Field Frame Number\s+(\d+),\s+of\s+(\d+),\s+at step time\s+([\d.E+-]+)') {
        return [PSCustomObject]@{ Kind = 'frame'; SimS = [double]$Matches[3] }
    }
    if ($Line -match '^\s+(\d+)\s+([\d.E+-]+)\s+([\d.E+-]+)\s+(\d\d:\d\d:\d\d)') {
        return [PSCustomObject]@{
            Kind = 'inc'
            SimS = [double]$Matches[3]
            Wall = [string]$Matches[4]
        }
    }
    return $null
}

function Sync-RemoteSta {
    param([string]$Slug)
    $jobDir = Join-Path $LocalRoot "output\jobs\$Slug"
    New-Item -ItemType Directory -Force -Path $jobDir | Out-Null
    $remoteJob = "$RemoteRoot/output/jobs/$Slug"
    scp "${RemoteHost}:${remoteJob}/${Slug}.sta" $jobDir 2>$null | Out-Null
    scp "${RemoteHost}:${remoteJob}/${Slug}.lck" $jobDir 2>$null | Out-Null
}

function Get-VariantStatus {
    param([string]$Slug)
    $sta = Join-Path $LocalRoot "output\jobs\$Slug\$Slug.sta"
    $lck = Join-Path $LocalRoot "output\jobs\$Slug\$Slug.lck"
    $odb = Join-Path $LocalRoot "output\jobs\$Slug\$Slug.odb"

    if ((Test-Path $sta) -and (Select-String -Path $sta -Pattern 'THE ANALYSIS HAS COMPLETED SUCCESSFULLY' -Quiet)) {
        return 'COMPLETED'
    }
    if (Test-Path $lck) { return 'RUNNING' }
    if ((Test-Path $sta) -and (Select-String -Path $sta -Pattern 'THE ANALYSIS HAS NOT BEEN COMPLETED|excessively distorted' -Quiet)) {
        return 'FAILED'
    }
    if (Test-Path $sta) { return 'STOPPED' }
    return 'WAITING'
}

function Read-StaProgress {
    param([string]$Slug)
    $sta = Join-Path $LocalRoot "output\jobs\$Slug\$Slug.sta"
    $simS = 0.0
    $wall = '--:--:--'
    if (-not (Test-Path $sta)) { return $simS, $wall }
    foreach ($line in (Get-Content $sta -Tail 50 -ErrorAction SilentlyContinue)) {
        $p = Parse-StaLine $line
        if (-not $p) { continue }
        if ($p.SimS -gt $simS) { $simS = $p.SimS }
        if ($p.Kind -eq 'inc') { $wall = $p.Wall }
    }
    return $simS, $wall
}

Write-Host "=== Q0.5 sweep + Q1.0 B nosettle monitor (poll=${PollSeconds}s, scp .sta) ===" -ForegroundColor Cyan
Write-Host "  Remote: ${RemoteHost}:${RemoteRoot}" -ForegroundColor Cyan
Write-Host ""

while ($true) {
    $now = Get-Date -Format "HH:mm:ss"
    Write-Host "========== [$now] ==========" -ForegroundColor DarkGray

    foreach ($j in $TrackJobs) {
        $slug = "hu_bai_$($j.Tag)_L20_4x4x4_solid_cad_f_$($j.Suffix)"
        Sync-RemoteSta -Slug $slug
        $st = Get-VariantStatus -Slug $slug
        $simS, $wall = Read-StaProgress -Slug $slug

        $pct = if ($StepTimeS -gt 0) { [math]::Min(100, 100 * $simS / $StepTimeS) } else { 0 }
        $estr = $TargetStrain * $simS / $StepTimeS * 100
        $filled = [int][math]::Floor(40 * $pct / 100)
        $bar = ("#" * $filled).PadRight(40, "-")
        $color = switch ($st) {
            'COMPLETED' { 'Green' }
            'RUNNING'   { 'Yellow' }
            'FAILED'    { 'Red' }
            'STOPPED'   { 'Red' }
            default     { 'Gray' }
        }

        Write-Host ("--- {0} [{1}] ---" -f $j.Label, $st) -ForegroundColor $color
        if ($st -eq 'WAITING') {
            Write-Host "  (not started)"
        } elseif ($st -eq 'RUNNING' -and $simS -le 0) {
            Write-Host "  packager / pre-increment (no progress line yet)"
        } else {
            Write-Host ("  [{0}] {1,5:F1}%  sim {2,7:F1}/{3} s  strain~{4,5:F1}%  wall {5}" -f $bar, $pct, $simS, $StepTimeS, $estr, $wall)
        }
        Write-Host ""
    }

    $sweep = ssh $RemoteHost "pgrep -af run_paperbox_snapthrough_sweep.sh 2>/dev/null | grep -v grep | head -1"
    if ($sweep) { Write-Host "  queue: RUNNING" -ForegroundColor DarkYellow }
    else { Write-Host "  queue: idle / finished" -ForegroundColor DarkGray }

  $doneLine = ssh $RemoteHost "grep '^DONE ' '$RemoteRoot/output/logs/paperbox_snapthrough_sweep.log' 2>/dev/null | tail -1"
    if ($doneLine) {
        Write-Host "  $doneLine" -ForegroundColor Green
        Write-Host "=== sweep DONE ===" -ForegroundColor Green
        break
    }

    Start-Sleep -Seconds $PollSeconds
}
