# Live Abaqus job progress in the terminal (poll .sta).
param(
    [string]$Slug = "hu_bai_sfbls_af2q1_L20_4x4x4_solid_cad_f_fast80",
    [string[]]$SlugQueue = @(),
    [string]$SlugQueueCsv = "",
    [string]$RemoteHost = "",
    [string]$RemoteRoot = "",
    [double]$StepTimeS = 0,
    [double]$TargetStrain = 0.8,
    [int]$PollSeconds = 30,
    [switch]$UseMeta
)

$ErrorActionPreference = "SilentlyContinue"
$ScriptDir = $PSScriptRoot
. (Join-Path $ScriptDir "submit_helpers.ps1")
$Root = (Resolve-Path (Join-Path $ScriptDir "..")).Path

if ($SlugQueueCsv) {
    $SlugQueue = @($SlugQueueCsv -split ',' | ForEach-Object { $_.Trim() } | Where-Object { $_ })
}
if ($SlugQueue.Count -eq 0) { $SlugQueue = @($Slug) }

$RemoteWatch = [bool]$RemoteHost -and [bool]$RemoteRoot
if ($RemoteHost -xor $RemoteRoot) {
    throw "Use -RemoteHost and -RemoteRoot together (e.g. art@172.20.200.93 and /media/art/file/XiangLang/Lattice/LWY/HuBaiLab)."
}

function Sync-RemoteJobFiles {
    param([Parameter(Mandatory)][string]$JobSlug)
    if (-not $RemoteWatch) { return }
    $jobDir = Join-Path $Root "output\jobs\$JobSlug"
    $exportDir = Join-Path $Root "output\export\$JobSlug"
    New-Item -ItemType Directory -Force -Path $jobDir, $exportDir | Out-Null
    $remoteJob = "$RemoteRoot/output/jobs/$JobSlug"
    scp "${RemoteHost}:${remoteJob}/${JobSlug}.sta" $jobDir 2>$null | Out-Null
    scp "${RemoteHost}:${remoteJob}/${JobSlug}.lck" $jobDir 2>$null | Out-Null
    scp "${RemoteHost}:$RemoteRoot/output/export/${JobSlug}/${JobSlug}_meta.json" $exportDir 2>$null | Out-Null
}

function Resolve-JobMeta {
    param([string]$JobSlug)
    $metaPath = Join-Path $Root "output\export\$JobSlug\${JobSlug}_meta.json"
    if (-not (Test-Path $metaPath)) { return $null }
    try { return Get-Content $metaPath -Raw | ConvertFrom-Json } catch { return $null }
}

function Resolve-ActiveSlug {
    param([string[]]$Candidates)
    foreach ($s in $Candidates) {
        $lck = Join-Path $Root "output\jobs\$s\$s.lck"
        if (Test-Path $lck) { return $s }
    }
    foreach ($s in $Candidates) {
        $sta = Join-Path $Root "output\jobs\$s\$s.sta"
        $odb = Join-Path $Root "output\jobs\$s\$s.odb"
        if ((Test-Path $sta) -and -not (Test-AbaqusJobCompleted -StaPath $sta -OdbPath $odb)) {
            $lck = Join-Path $Root "output\jobs\$s\$s.lck"
            if (-not (Test-Path $lck)) { continue }
        }
    }
    foreach ($s in $Candidates) {
        $sta = Join-Path $Root "output\jobs\$s\$s.sta"
        $odb = Join-Path $Root "output\jobs\$s\$s.odb"
        if (-not (Test-AbaqusJobCompleted -StaPath $sta -OdbPath $odb)) { return $s }
    }
    return $Candidates[-1]
}

function Parse-StaLine {
    param([string]$Line)
    if ($Line -match 'Output Field Frame Number\s+(\d+),\s+of\s+(\d+),\s+at step time\s+([\d.E+-]+)') {
        return [PSCustomObject]@{
            Kind = 'frame'
            Frame = [int]$Matches[1]
            Frames = [int]$Matches[2]
            SimS = [double]$Matches[3]
        }
    }
    if ($Line -match '^\s+(\d+)\s+([\d.E+-]+)\s+([\d.E+-]+)\s+(\d\d:\d\d:\d\d)\s+([\d.E+-]+)\s+(\d+)\s+([\d.E+-]+)\s+([\d.E+-]+)') {
        return [PSCustomObject]@{
            Kind = 'inc'
            Inc = [int]$Matches[1]
            # Column 2 = current-step time; column 3 = total time (includes restart history).
            SimS = [double]$Matches[2]
            TotalS = [double]$Matches[3]
            Wall = [string]$Matches[4]
            Ke = [double]$Matches[7]
            Ie = [double]$Matches[8]
        }
    }
    return $null
}

function Get-JobStatus {
    # .lck is authoritative while Abaqus holds the job open.
    if (Test-Path $Lck) { return 'RUNNING' }
    if ($RemoteWatch -and (Test-Path $Sta)) {
        $t = Get-Content $Sta -Raw -ErrorAction SilentlyContinue
        if ($t -match 'THE ANALYSIS HAS COMPLETED SUCCESSFULLY') { return 'COMPLETED' }
    } elseif (Test-AbaqusJobCompleted -StaPath $Sta -OdbPath $Odb) {
        return 'COMPLETED'
    }
    if ((Test-Path $Sta) -and -not (Test-Path $Lck)) {
        $t = Get-Content $Sta -Raw
        if ($t -match 'THE ANALYSIS HAS NOT BEEN COMPLETED') { return 'FAILED' }
        if ($t -match 'deformation speed/wave speed') { return 'FAILED' }
    }
    if ((-not $RemoteWatch) -and (Get-Process explicit -ErrorAction SilentlyContinue)) {
        return 'RUNNING'
    }
    if (Test-Path $Sta) { return 'STOPPED' }
    return 'WAITING'
}

function Format-Eta {
    param([double]$SimS, [double]$WallSec, [double]$StepS)
    if ($SimS -le 0.5) { return 'calculating...' }
    $rate = $WallSec / $SimS
    $remain = [math]::Max(0, $StepS - $SimS)
    $etaSec = [int][math]::Round($remain * $rate)
    $eta = (Get-Date).AddSeconds($etaSec)
    return $eta.ToString('MM-dd HH:mm')
}

Write-Host "=== Job progress watcher ===" -ForegroundColor Cyan
Write-Host "  queue: $($SlugQueue -join ' -> ')"
Write-Host "  poll=${PollSeconds}s"
if ($RemoteWatch) { Write-Host "  remote: ${RemoteHost}:${RemoteRoot}" -ForegroundColor Cyan }
Write-Host ""

$queueIdx = 0
while ($queueIdx -lt $SlugQueue.Count) {
    $Slug = $SlugQueue[$queueIdx]
    $JobDir = Join-Path $Root "output\jobs\$Slug"
    $Sta = Join-Path $JobDir "$Slug.sta"
    $Odb = Join-Path $JobDir "$Slug.odb"
    $Lck = Join-Path $JobDir "$Slug.lck"

    $stepTime = $StepTimeS
    $targetStrain = $TargetStrain
    $strainBase = 0.0
    $continueTag = ''
    if ($UseMeta -or $stepTime -le 0) {
        $meta = Resolve-JobMeta -JobSlug $Slug
        if ($meta) {
            if ($stepTime -le 0) { $stepTime = [double]$meta.step_time }
            if ($meta.reference_height_mm -gt 0) {
                $targetStrain = [double]$meta.compression_displacement / [double]$meta.reference_height_mm
            }
            if ($meta.restart_continue) {
                $rc = $meta.restart_continue
                $strainBase = [double]$rc.source_strain
                $targetStrain = [double]$rc.target_strain
                $continueTag = " continue from $($rc.source_slug) @ $([int](100*$strainBase))%"
            } elseif ($meta.loading -and $meta.loading.continue_source_strain) {
                $strainBase = [double]$meta.loading.continue_source_strain
                $continueTag = " continue from $([int](100*$strainBase))%"
            }
        }
    }
    if ($stepTime -le 0) { $stepTime = 480 }

    Write-Host "--- $Slug (step=${stepTime}s, strain~$([int]($targetStrain*100))%$continueTag) ---" -ForegroundColor Cyan
    Write-Host "  sta: $Sta"
    Write-Host ""

while ($true) {
    Sync-RemoteJobFiles -JobSlug $Slug
    $status = Get-JobStatus
    $now = Get-Date -Format 'HH:mm:ss'
    $simS = 0.0
    $totalS = 0.0
    $ke = $null
    $ie = $null
    $wallSec = 0
    $frameInfo = ''

    if (Test-Path $Sta) {
        $lines = Get-Content $Sta -Tail 40
        foreach ($line in ($lines | Select-Object -Last 1)) { }
        foreach ($line in $lines) {
            $p = Parse-StaLine $line
            if (-not $p) { continue }
            if ($p.Kind -eq 'frame') {
                $frameInfo = "frame $($p.Frame)/$($p.Frames)"
                if ($p.SimS -gt $simS) { $simS = $p.SimS }
            } elseif ($p.Kind -eq 'inc') {
                $simS = $p.SimS
                $totalS = $p.TotalS
                $ke = $p.Ke
                $ie = $p.Ie
                $ts = [TimeSpan]::Parse($p.Wall)
                $wallSec = $ts.TotalSeconds
            }
        }
    }

    $pct = if ($stepTime -gt 0) { [math]::Min(100, 100 * $simS / $stepTime) } else { 0 }
    $deltaStrain = [math]::Max(0.0, $targetStrain - $strainBase)
    $strain = $strainBase + $deltaStrain * $simS / $stepTime
    $barLen = 40
    $filled = [int][math]::Floor($barLen * $pct / 100)
    $bar = ('#' * $filled).PadRight($barLen, '-')
    $eta = Format-Eta -SimS $simS -WallSec $wallSec -StepS $stepTime
    $explicitN = if ($RemoteWatch) { $null } else { @(Get-Process explicit -ErrorAction SilentlyContinue).Count }

    $color = switch ($status) {
        'COMPLETED' { 'Green' }
        'FAILED' { 'Red' }
        'RUNNING' { 'Yellow' }
        default { 'Gray' }
    }

    $totalNote = if ($totalS -gt ($simS + 1.0)) { "  total=${totalS:F1}s" } else { '' }
    Write-Host ("[{0}] {1}" -f $now, $status) -ForegroundColor $color
    Write-Host ("  [{0}] {1,5:F1}%  step {2,7:F1}/{3} s{4}  strain ~{5,5:F1}%  wall {6}" -f $bar, $pct, $simS, $stepTime, $totalNote, ($strain*100), ($(if($wallSec){[TimeSpan]::FromSeconds($wallSec).ToString('hh\:mm\:ss')}else{'--:--:--'})))
    if ($frameInfo) { Write-Host "  $frameInfo" }
    if ($null -ne $ke) {
        $tail = if ($null -eq $explicitN) { "ETA~$eta" } else { "explicit_procs=$explicitN  ETA~$eta" }
        Write-Host ("  KE={0:G3}  IE={1:G3}  {2}" -f $ke, $ie, $tail)
    } else {
        if ($null -eq $explicitN) { Write-Host "  ETA~$eta" }
        else { Write-Host "  explicit_procs=$explicitN  ETA~$eta" }
    }
    Write-Host ""

    if ($status -in @('COMPLETED', 'FAILED', 'STOPPED')) { break }
    Start-Sleep -Seconds $PollSeconds
}
    if ($status -eq 'COMPLETED') {
        Write-Host "  -> done, next in queue" -ForegroundColor Green
    } elseif ($status -eq 'FAILED') {
        Write-Host "  -> failed, next in queue (if any)" -ForegroundColor Red
    } else {
        Write-Host "  -> stopped" -ForegroundColor Gray
    }
    Write-Host ""
    $queueIdx++
}
Write-Host "=== Queue watch finished ===" -ForegroundColor Cyan
