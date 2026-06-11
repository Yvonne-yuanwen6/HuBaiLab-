# Wait for active HuBaiLab export/submit/Abaqus work, then run Q=0.5 4x4x4 fast80.
param(
    [int]$PollSeconds = 30,
    [int]$MemoryMB = 8192,
    [int]$Cpus = 4,
    [switch]$ForceRerun
)

$ErrorActionPreference = "Stop"
$ScriptDir = $PSScriptRoot
. (Join-Path $ScriptDir "submit_helpers.ps1")
$Root = (Resolve-Path (Join-Path $ScriptDir "..")).Path
Set-Location $Root
$env:PYTHONPATH = $Root

$VenvPy = Join-Path $Root ".venv\Scripts\python.exe"
function Get-ProjectPython {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        if (Test-Path $VenvPy) {
            try { & $VenvPy -c "import sys; sys.exit(0)" 2>$null; if ($LASTEXITCODE -eq 0) { return $VenvPy } } catch { }
        }
        return "py"
    }
    if (Test-Path $VenvPy) { return $VenvPy }
    throw "Python not found."
}

function Test-HuBaiBlockingWork {
    $patterns = @(
        'run_hu_bai_bcc_solid_cad_export\.py',
        'submit_hu_bai_bcc_solid_cad_compression\.ps1',
        'abaqus\s+job=',
        '\bstandard\.exe\b',
        '\bexplicit\.exe\b',
        '\bpre\.exe\b'
    )
    $regex = ($patterns -join '|')
    $procs = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -and $_.CommandLine -match $regex }
    return @($procs)
}

Write-Host "=== Waiting for export/submit/Abaqus to finish (poll ${PollSeconds}s) ===" -ForegroundColor Yellow
while ($true) {
    $busy = Test-HuBaiBlockingWork
    if ($busy.Count -eq 0) {
        Write-Host "No blocking HuBaiLab jobs detected." -ForegroundColor Green
        break
    }
    $summary = ($busy | ForEach-Object {
        $cmd = $_.CommandLine
        if ($cmd.Length -gt 120) { $cmd = $cmd.Substring(0, 120) + '...' }
        "PID $($_.ProcessId): $cmd"
    }) -join "`n  "
    Write-Host "  Still running ($($busy.Count)):`n  $summary" -ForegroundColor DarkYellow
    Start-Sleep -Seconds $PollSeconds
}

try {
    $cad = Get-VerifiedCadStep -Root $Root -Variant "sfbls_af2q0p5" -Cells 4
} catch {
    Write-Host "[ERROR] $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}

$slug = "hu_bai_sfbls_af2q0p5_L20_4x4x4_solid_cad_f_fast80"
$ProjectPy = Get-ProjectPython

Write-Host ""
Write-Host "=== Q=0.5 fast80 export + submit ===" -ForegroundColor Cyan
Write-Host "  CAD: $cad"
Write-Host "  slug: $slug"

Write-Host "[1/2] Export INP (fast80, mesh=0.8 mm, strain=80%) ..."
$exportArgs = @(
    "scripts\run_hu_bai_bcc_solid_cad_export.py",
    "--cells", "4",
    "--Q", "0.5",
    "--profile", "fast",
    "--case-suffix", "fast80",
    "--strain", "0.8",
    "--cad", $cad
)
if ($ProjectPy -eq "py") {
    & py -3 @exportArgs
} else {
    & $ProjectPy @exportArgs
}
if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERROR] Export failed: $slug" -ForegroundColor Red
    exit $LASTEXITCODE
}

Write-Host "[2/2] Submit Abaqus ..."
$submitArgs = @(
    "-File", (Join-Path $ScriptDir "submit_hu_bai_bcc_solid_cad_compression.ps1"),
    "-SkipExport",
    "-Slug", $slug,
    "-MemoryMB", $MemoryMB,
    "-Cpus", $Cpus
)
if ($ForceRerun) { $submitArgs += "-ForceRerun" }
& powershell @submitArgs
if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERROR] Submit failed: $slug" -ForegroundColor Red
    exit $LASTEXITCODE
}

Write-Host ""
Write-Host "Q=0.5 fast80 completed." -ForegroundColor Green
