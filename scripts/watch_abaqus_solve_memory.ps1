# Pause Abaqus Explicit if system free RAM drops too low (avoid OS thrash / OOM).
# On pause: archive partial results, then optionally resume fast80 queue at fewer CPUs.
param(
    [Parameter(Mandatory)][string]$JobName,
    [Parameter(Mandatory)][string]$JobDir,
    [string]$Slug = '',
    [string]$PostDir = '',
    [double]$MinFreeGB = 1.5,
    [double]$WarnFreeGB = 2.5,
    [int]$IntervalSec = 30,
    [int]$ResumeCpus = 6,
    [int]$ResumeMemoryMB = 6144,
    [double]$LoadRateMmMin = 5,
    [switch]$AutoResumeOnLowMemory
)

$ErrorActionPreference = 'Stop'
$ScriptDir = $PSScriptRoot
. (Join-Path $ScriptDir 'submit_helpers.ps1')
$Root = (Resolve-Path (Join-Path $ScriptDir '..')).Path
if (-not $Slug) { $Slug = $JobName }
if (-not $PostDir) { $PostDir = Join-Path $Root "output\post\$Slug" }

$LogDir = Join-Path $Root 'output\reports'
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$Log = Join-Path $LogDir "abaqus_mem_watch_${JobName}.log"
$Flag = Join-Path $LogDir "abaqus_mem_paused_${JobName}.flag"

function Write-Log([string]$Msg) {
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $Msg"
    Add-Content -Path $Log -Value $line
    Write-Host $line
}

function Get-RamStats {
    $os = Get-CimInstance Win32_OperatingSystem
    $totalGB = [math]::Round($os.TotalVisibleMemorySize / 1MB, 2)
    $freeGB = [math]::Round($os.FreePhysicalMemory / 1MB, 2)
    [PSCustomObject]@{ TotalGB = $totalGB; FreeGB = $freeGB }
}

function Test-AbaqusSolverRunning {
    param([string]$Name, [string]$Dir)
    $lck = Join-Path $Dir ($Name + '.lck')
    if ((Test-Path $lck) -and (Test-AbaqusJobProcessRunning -JobName $Name -JobDir $Dir)) { return $true }
    $pat = [regex]::Escape($Name)
    foreach ($proc in Get-CimInstance Win32_Process -ErrorAction SilentlyContinue) {
        if ($proc.Name -notmatch '^(standard|explicit|pre|package|ABQLauncher)\.exe$') { continue }
        $cmd = [string]$proc.CommandLine
        if ($cmd -match "job=$pat\b" -or $cmd -match $pat) { return $true }
    }
    return $false
}

Write-Log "watch start job=$JobName min_free=${MinFreeGB}GB warn=${WarnFreeGB}GB interval=${IntervalSec}s resume_cpus=$ResumeCpus auto_resume=$($AutoResumeOnLowMemory.IsPresent)"

while ($true) {
    $ram = Get-RamStats
    $running = Test-AbaqusSolverRunning -Name $JobName -Dir $JobDir
    $abaqN = @(Get-Process explicit, standard, pre, package -ErrorAction SilentlyContinue).Count

    if ($ram.FreeGB -lt $WarnFreeGB) {
        Write-Log ("WARN RAM free {0}/{1}GB | abaqus_procs={2} solver_running={3}" -f $ram.FreeGB, $ram.TotalGB, $abaqN, $running)
    } else {
        Write-Log ("OK   RAM free {0}/{1}GB | abaqus_procs={2} solver_running={3}" -f $ram.FreeGB, $ram.TotalGB, $abaqN, $running)
    }

    if ($ram.FreeGB -lt $MinFreeGB -and $running) {
        Write-Log "CRITICAL low RAM -> stopping $JobName and archiving partial results"
        Stop-AbaqusJobProcesses -JobName $JobName -JobDir $JobDir
        Start-Sleep -Seconds 2
        $archive = Archive-FailedAbaqusJob -Root $Root -JobDir $JobDir -JobName $JobName `
            -Slug $Slug -PostDir $PostDir -Reason 'low_memory_paused'
        @(
            "paused_at=$(Get-Date -Format o)"
            "reason=free_ram_${ram.FreeGB}GB_below_${MinFreeGB}GB"
            "job=$JobName"
            "slug=$Slug"
            "archive=$archive"
            "resume_cpus=$ResumeCpus"
            "resume_memory_mb=$ResumeMemoryMB"
            "load_rate_mm_min=$LoadRateMmMin"
            "resume_script=scripts/resume_fast80_queue_after_low_memory.ps1"
        ) | Set-Content -Path $Flag -Encoding UTF8
        Write-Log "Paused. Flag: $Flag"
        if ($AutoResumeOnLowMemory -and $ResumeCpus -gt 0) {
            Write-Log "Scheduling fast80 queue resume at ${ResumeCpus} cpus after RAM recovers ..."
            Start-Process powershell -ArgumentList @(
                '-NoProfile', '-File', (Join-Path $ScriptDir 'resume_fast80_queue_after_low_memory.ps1'),
                '-WaitSlug', $Slug,
                '-ResumeCpus', "$ResumeCpus",
                '-MemoryMB', "$ResumeMemoryMB",
                '-LoadRateMmMin', "$LoadRateMmMin",
                '-PauseFlag', $Flag
            ) -WindowStyle Hidden
        }
        break
    }

    if (-not $running -and $abaqN -eq 0) {
        $sta = Join-Path $JobDir ($JobName + '.sta')
        $odb = Join-Path $JobDir ($JobName + '.odb')
        if (Test-AbaqusJobCompleted -StaPath $sta -OdbPath $odb) {
            Write-Log 'Job completed successfully; watch exit.'
            break
        }
        if (-not (Test-Path (Join-Path $JobDir ($JobName + '.lck')))) {
            if ((Test-Path $sta) -or (Test-Path $odb)) {
                Write-Log 'Solver stopped (not running); watch exit (check .sta for success/failure).'
                break
            }
        }
    }

    Start-Sleep -Seconds $IntervalSec
}
