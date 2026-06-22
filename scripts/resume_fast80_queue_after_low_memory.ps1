# After low-memory pause: wait for RAM, then re-run fast80 queue at reduced CPU count (serial).
param(
    [string]$WaitSlug = "hu_bai_sfbls_af2q1_L20_4x4x4_solid_cad_f_fast80",
    [int]$ResumeCpus = 6,
    [int]$MemoryMB = 6144,
    [double]$MinFreeGBToResume = 3.0,
    [int]$PollSeconds = 30,
    [double]$LoadRateMmMin = 5,
    [string]$PauseFlag = ""
)

$ErrorActionPreference = "Stop"
$ScriptDir = $PSScriptRoot
$Root = (Resolve-Path (Join-Path $ScriptDir "..")).Path
$LogDir = Join-Path $Root "output\reports"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$Log = Join-Path $LogDir "fast80_low_mem_resume.log"

function Write-Log([string]$Msg) {
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $Msg"
    Add-Content -Path $Log -Value $line
    Write-Host $line
}

function Get-FreeRamGB {
    $os = Get-CimInstance Win32_OperatingSystem
    return [math]::Round($os.FreePhysicalMemory / 1MB, 2)
}

function Stop-QueueWatchers {
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object {
            $_.Name -eq 'powershell.exe' -and
            [string]$_.CommandLine -match 'run_sfbls_q05_q15_fast80_after_q1|resume_fast80_queue_after_low_memory'
        } |
        ForEach-Object {
            if ($_.ProcessId -eq $PID) { return }
            try {
                Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop
                Write-Log "Stopped PID $($_.ProcessId) (old queue/resume watcher)"
            } catch {
                Write-Log "WARN could not stop PID $($_.ProcessId): $_"
            }
        }
}

Write-Log "resume start: slug=$WaitSlug cpus=$ResumeCpus memory=${MemoryMB}MB load=${LoadRateMmMin}mm/min"
if ($PauseFlag -and (Test-Path $PauseFlag)) {
    Write-Log "pause flag: $PauseFlag"
    Get-Content $PauseFlag -ErrorAction SilentlyContinue | ForEach-Object { Write-Log "  $_" }
}

while ((Get-FreeRamGB) -lt $MinFreeGBToResume) {
    $free = Get-FreeRamGB
    Write-Log "waiting for RAM free ${free}GB < ${MinFreeGBToResume}GB ..."
    Start-Sleep -Seconds $PollSeconds
}
Write-Log "RAM OK: free $(Get-FreeRamGB)GB -> launching queue at ${ResumeCpus} cpus"

Stop-QueueWatchers
Start-Sleep -Seconds 2

$queueLog = Join-Path $Root "output\cad\_stepwise_q1p0\sw_zstack\fast80_planA_queue_6cpu.log"
$jobDir = Join-Path $Root "output\jobs\$WaitSlug"
$watchLog = Join-Path $LogDir "abaqus_mem_watch_${WaitSlug}.log"

Start-Process powershell -ArgumentList @(
    '-NoProfile', '-File', (Join-Path $ScriptDir 'watch_abaqus_solve_memory.ps1'),
    '-JobName', $WaitSlug,
    '-JobDir', $jobDir,
    '-Slug', $WaitSlug,
    '-MinFreeGB', '1.5',
    '-WarnFreeGB', '2.5',
    '-IntervalSec', '30',
    '-ResumeCpus', "$ResumeCpus",
    '-ResumeMemoryMB', "$MemoryMB",
    '-LoadRateMmMin', "$LoadRateMmMin"
) -WindowStyle Hidden

$cmd = @"
Set-Location '$Root'
& powershell -NoProfile -File scripts\run_sfbls_q05_q15_fast80_after_q1.ps1 `
  -Cpus $ResumeCpus -MemoryMB $MemoryMB -LoadRateMmMin $LoadRateMmMin `
  -FallbackLoadRateMmMin $LoadRateMmMin *>&1 | Tee-Object -FilePath '$queueLog' -Append
"@
Start-Process powershell -ArgumentList @('-NoProfile', '-Command', $cmd) -WindowStyle Hidden

Write-Log "Started 6-core queue -> $queueLog"
Write-Log "Memory watch log -> $watchLog"
