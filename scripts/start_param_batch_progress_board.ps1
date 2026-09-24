# One-shot launcher for param_batch remote HTML progress board.
# After submitting a server Explicit job, from repo root:
#
#   powershell -File scripts/start_param_batch_progress_board.ps1 -CaseId af2q1_deq2p5_k1
#   powershell -File scripts/start_param_batch_progress_board.ps1 -CaseId af2q1_deq2p5_k1 -Background
#
# Opens/updates: output/logs/progress_board/{CaseId}_{Slug}.html
param(
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$CaseId,

    [string]$Slug = "cae_tet0p6mm80_5mmin_paperbox",
    [string]$BatchName = "param_batch",
    [string]$RemoteHost = $(if ($env:HU_BAI_REMOTE_HOST) { $env:HU_BAI_REMOTE_HOST } else { "art@172.20.200.93" }),
    [string]$RemoteRoot = $(if ($env:HU_BAI_REMOTE_ROOT) { $env:HU_BAI_REMOTE_ROOT } else { "/home/art/HuBaiLab_ssd" }),
    [double]$StepTotalSec = 0,
    [int]$IntervalSec = 20,
    [switch]$NoBrowser,
    [switch]$Background,
    [switch]$SkipHelperCheck
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$WatchScript = Join-Path $PSScriptRoot "watch_remote_abaqus_progress.ps1"
if (-not (Test-Path -LiteralPath $WatchScript)) {
    throw "Missing watcher: $WatchScript"
}

$env:HU_BAI_REMOTE_HOST = $RemoteHost
$env:HU_BAI_REMOTE_ROOT = $RemoteRoot

$html = Join-Path $Root "output\logs\progress_board\${CaseId}_${Slug}.html"
Write-Host "CaseId      : $CaseId" -ForegroundColor Cyan
Write-Host "Slug        : $Slug"
Write-Host "Remote      : ${RemoteHost}:${RemoteRoot}"
Write-Host "Board HTML  : $html"
Write-Host "Watcher     : $WatchScript"

$argList = @(
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-File", $WatchScript,
    "-CaseId", $CaseId,
    "-Slug", $Slug,
    "-BatchName", $BatchName,
    "-RemoteHost", $RemoteHost,
    "-RemoteRoot", $RemoteRoot,
    "-IntervalSec", "$IntervalSec"
)
if ($StepTotalSec -gt 0) { $argList += @("-StepTotalSec", "$StepTotalSec") }
if ($NoBrowser) { $argList += "-NoBrowser" }
if ($SkipHelperCheck) { $argList += "-SkipHelperCheck" }

if ($Background) {
    # Avoid duplicate watchers for the same case.
    Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" -ErrorAction SilentlyContinue |
        Where-Object {
            $_.CommandLine -and
            $_.CommandLine -match 'watch_remote_abaqus_progress' -and
            $_.CommandLine -match [regex]::Escape($CaseId)
        } |
        ForEach-Object {
            Write-Host "Stopping previous watcher PID $($_.ProcessId)" -ForegroundColor Yellow
            Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
        }

    $proc = Start-Process -FilePath "powershell.exe" -ArgumentList $argList -PassThru -WindowStyle Minimized
    Write-Host "Started background watcher PID=$($proc.Id)" -ForegroundColor Green
    Write-Host "Open board: $html"
    if (-not $NoBrowser) {
        Start-Sleep -Seconds 3
        if (Test-Path -LiteralPath $html) {
            try { Invoke-Item -LiteralPath $html } catch { Start-Process $html }
        }
    }
    exit 0
}

& powershell.exe @argList
exit $LASTEXITCODE
