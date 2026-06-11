# Monitor HuBaiLab OCC/gmsh Python jobs and system RAM.
# If memory is low, pause heavy fuse jobs (keep newest) and write a resume flag.
param(
    [double]$MinFreeGB = 2.5,
    [int]$MaxOccWS_MB = 4500,
    [int]$MaxConcurrentOcc = 1,
    [int]$IntervalSec = 15
)

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$LogDir = Join-Path $Root "output\reports"
$Log = Join-Path $LogDir "hu_bai_mem_watch.log"
$Flag = Join-Path $LogDir "hu_bai_mem_paused.flag"
$State = Join-Path $LogDir "hu_bai_mem_watch_state.json"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

$OccPatterns = @(
    'run_hu_bai_bcc_unitcell',
    'run_hu_bai_bcc_merge_zslabs',
    'merge_manual_zslabs_gmsh',
    'prepare_manual_zslabs',
    '_occ_fuse_zslab_stack_from_ref',
    'run_hu_bai_bcc_.*_step_fuse'
)
$OccRegex = ($OccPatterns -join '|')

function Write-Log([string]$Msg) {
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $Msg"
    Add-Content -Path $Log -Value $line
    Write-Host $line
}

function Get-RamStats {
    $os = Get-CimInstance Win32_OperatingSystem
    $totalGB = [math]::Round($os.TotalVisibleMemorySize / 1MB, 2)
    $freeGB = [math]::Round($os.FreePhysicalMemory / 1MB, 2)
    [PSCustomObject]@{ TotalGB = $totalGB; FreeGB = $freeGB; UsedGB = [math]::Round($totalGB - $freeGB, 2) }
}

function Get-OccJobs {
    Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -and $_.CommandLine -match $OccRegex } |
        ForEach-Object {
            $p = Get-Process -Id $_.ProcessId -ErrorAction SilentlyContinue
            $ws = if ($p) { [math]::Round($p.WorkingSet64 / 1MB, 0) } else { 0 }
            $pm = if ($p) { [math]::Round($p.PrivateMemorySize64 / 1MB, 0) } else { 0 }
            $start = if ($p) { $p.StartTime.ToString('o') } else { '' }
            [PSCustomObject]@{
                PID = $_.ProcessId
                WS_MB = $ws
                PM_MB = $pm
                StartTime = $start
                Cmd = $_.CommandLine
            }
        }
}

function Get-AbaqusCount {
    @(
        Get-Process standard, explicit, pre, ABQcaeK -ErrorAction SilentlyContinue
    ).Count
}

function Write-State($ram, $jobs, $abaqus, $action) {
    $payload = @{
        updated_at = (Get-Date -Format 'o')
        ram_free_gb = $ram.FreeGB
        ram_total_gb = $ram.TotalGB
        occ_jobs = @($jobs | ForEach-Object { @{ pid = $_.PID; ws_mb = $_.WS_MB; cmd = $_.Cmd.Substring(0, [Math]::Min(200, $_.Cmd.Length)) } })
        abaqus_count = $abaqus
        last_action = $action
    }
    ($payload | ConvertTo-Json -Depth 4) + "`n" | Set-Content -Path $State -Encoding UTF8
}

function Stop-OccJob($job, [string]$reason) {
    try {
        Stop-Process -Id $job.PID -Force -ErrorAction Stop
        Write-Log "  stopped PID $($job.PID): $reason"
        return $true
    } catch {
        Write-Log "  failed to stop PID $($job.PID): $_"
        return $false
    }
}

Write-Log "watch start: min_free=${MinFreeGB}GB max_occ_ws=${MaxOccWS_MB}MB max_concurrent=$MaxConcurrentOcc interval=${IntervalSec}s"

while ($true) {
    $ram = Get-RamStats
    $jobs = @(Get-OccJobs | Sort-Object StartTime -Descending)
    $occWS = ($jobs | Measure-Object -Property WS_MB -Sum).Sum
    if (-not $occWS) { $occWS = 0 }
    $abaqus = Get-AbaqusCount

    $jobSummary = if ($jobs.Count -eq 0) { 'none' } else {
        ($jobs | ForEach-Object { "PID=$($_.PID) WS=$($_.WS_MB)MB" }) -join '; '
    }
    Write-Log ("RAM {0}/{1}GB free | OCC jobs={2} WS={3}MB | abaqus={4} | {5}" -f `
            $ram.FreeGB, $ram.TotalGB, $jobs.Count, $occWS, $abaqus, $jobSummary)

    $action = 'ok'
    $pauseReasons = @()

    if ($ram.FreeGB -lt $MinFreeGB) {
        $pauseReasons += "free RAM ${ram.FreeGB}GB < ${MinFreeGB}GB"
    }
    if ($occWS -gt $MaxOccWS_MB -and $jobs.Count -gt 0) {
        $pauseReasons += "OCC working set ${occWS}MB > ${MaxOccWS_MB}MB"
    }
    if ($jobs.Count -gt $MaxConcurrentOcc) {
        $pauseReasons += "concurrent OCC jobs $($jobs.Count) > $MaxConcurrentOcc"
    }

    if ($pauseReasons.Count -gt 0 -and $jobs.Count -gt 0) {
        $reason = $pauseReasons -join '; '
        Write-Log "PAUSE excess OCC jobs: $reason"
        $keep = $jobs | Select-Object -First 1
        $toStop = $jobs | Select-Object -Skip 1
        foreach ($job in $toStop) {
            Stop-OccJob $job "keep newest PID $($keep.PID)"
        }
        if ($ram.FreeGB -lt $MinFreeGB -and $keep) {
            Stop-OccJob $keep "critical low RAM"
            $action = 'paused_all'
            @(
                "paused_at=$(Get-Date -Format o)"
                "reason=$reason"
                "free_gb=$($ram.FreeGB)"
                "occ_ws_mb=$occWS"
                "stopped_pids=$(($jobs | ForEach-Object { $_.PID }) -join ',')"
                "resume_hint=Run scripts/run_hu_bai_guarded_pipeline.ps1 when RAM recovers"
            ) | Set-Content -Path $Flag -Encoding UTF8
            Write-Log "flag written: $Flag"
            Write-State $ram @() $abaqus $action
            break
        }
        $action = 'trimmed_concurrent'
    }

    Write-State $ram $jobs $abaqus $action

    if ($jobs.Count -eq 0 -and $abaqus -eq 0) {
        Write-Log "No OCC jobs or Abaqus solver; watch idle (continuing)."
    }

    Start-Sleep -Seconds $IntervalSec
}
