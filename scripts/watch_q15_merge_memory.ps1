# Pause Q=1.5 gmsh merge if RAM gets too low while Abaqus fast80 runs.
param(
    [double]$MinFreeGB = 2.0,
    [int]$MaxMergeWS_MB = 3500,
    [int]$IntervalSec = 20
)

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Log = Join-Path $Root "output\reports\q15_merge_mem_watch.log"
$Flag = Join-Path $Root "output\reports\q15_merge_paused_by_watch.flag"
New-Item -ItemType Directory -Force -Path (Split-Path $Log) | Out-Null

function Write-Log([string]$Msg) {
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $Msg"
    Add-Content -Path $Log -Value $line
    Write-Host $line
}

function Get-MergePids {
    Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -match 'merge_manual_zslabs_gmsh\.py.*--Q\s*1\.5' } |
        Select-Object -ExpandProperty ProcessId
}

function Get-RamStats {
    $os = Get-CimInstance Win32_OperatingSystem
    $totalGB = [math]::Round($os.TotalVisibleMemorySize / 1MB, 2)
    $freeGB = [math]::Round($os.FreePhysicalMemory / 1MB, 2)
    [PSCustomObject]@{ TotalGB = $totalGB; FreeGB = $freeGB; UsedGB = [math]::Round($totalGB - $freeGB, 2) }
}

Write-Log "watch start: min_free=${MinFreeGB}GB max_merge_ws=${MaxMergeWS_MB}MB interval=${IntervalSec}s"

while ($true) {
    $ram = Get-RamStats
    $pids = @(Get-MergePids)
    $mergeWS = 0
    foreach ($procId in $pids) {
        $p = Get-Process -Id $procId -ErrorAction SilentlyContinue
        if ($p) { $mergeWS += [math]::Round($p.WorkingSet64 / 1MB, 0) }
    }

    $abaqus = @(Get-Process explicit -ErrorAction SilentlyContinue).Count
    Write-Log ("RAM {0}/{1}GB free | Q15 merge PIDs=[{2}] WS={3}MB | explicit={4}" -f `
            $ram.FreeGB, $ram.TotalGB, ($pids -join ','), $mergeWS, $abaqus)

    $pause = $false
    $reason = ""
    if ($ram.FreeGB -lt $MinFreeGB) {
        $pause = $true
        $reason = "free RAM ${ram.FreeGB}GB < ${MinFreeGB}GB"
    }
    if ($mergeWS -gt $MaxMergeWS_MB -and $pids.Count -gt 0) {
        $pause = $true
        $reason = "Q15 merge working set ${mergeWS}MB > ${MaxMergeWS_MB}MB"
    }

    if ($pause -and $pids.Count -gt 0) {
        Write-Log "PAUSE Q15 merge: $reason"
        foreach ($procId in $pids) {
            try {
                Stop-Process -Id $procId -Force -ErrorAction Stop
                Write-Log "  stopped PID $procId"
            } catch {
                Write-Log "  failed to stop PID ${procId}: $_"
            }
        }
        @(
            "paused_at=$(Get-Date -Format o)"
            "reason=$reason"
            "free_gb=$($ram.FreeGB)"
            "merge_ws_mb=$mergeWS"
            "note=Resume with: py -3 scripts/merge_manual_zslabs_gmsh.py --Q 1.5"
        ) | Set-Content -Path $Flag -Encoding UTF8
        Write-Log "flag written: $Flag"
        break
    }

    if ($pids.Count -eq 0) {
        Write-Log "Q15 merge not running; watch exiting."
        break
    }

    Start-Sleep -Seconds $IntervalSec
}
