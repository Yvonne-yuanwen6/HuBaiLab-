# Serial queue: CAE built-in C3D4 tet mesh + full compression INP + local Abaqus submit.
#
#   powershell -File scripts/run_cae_tet_queue_bcc_q05_q15.ps1
#   powershell -File scripts/run_cae_tet_queue_bcc_q05_q15.ps1 -ExportOnly
#   powershell -File scripts/run_cae_tet_queue_bcc_q05_q15.ps1 -CaseKeys bcc,q05

param(
    [string]$CaseSuffix = "cae_tet1p2mm80_5mmin_noself",
    [string[]]$CaseKeys = @("bcc", "q05", "q1", "q15"),
    [double]$CaeSeed = 1.2,
    [double]$LoadRateMmMin = 5,
    [double]$Strain = 0.8,
    [int]$MemoryMB = 16384,
    [int]$Cpus = 8,
    [switch]$NoSelfContact,
    [switch]$ForceRerun,
    [switch]$SkipCompleted,
    [switch]$ExportOnly,
    [switch]$ContinueOnFailure
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

$CaseMap = @{
    bcc = @{ Label = "BCC Q0"; Q = 0.0; Variant = "bcc_af2q0" }
    q05 = @{ Label = "SFBLS Q0.5"; Q = 0.5; Variant = "sfbls_af2q0p5" }
    q1  = @{ Label = "SFBLS Q1"; Q = 1.0; Variant = "sfbls_af2q1" }
    q15 = @{ Label = "SFBLS Q1.5"; Q = 1.5; Variant = "sfbls_af2q1p5" }
}

$LogPath = Join-Path $Root "output\reports\cae_tet_${CaseSuffix}_queue.log"
New-Item -ItemType Directory -Path (Split-Path $LogPath -Parent) -Force | Out-Null
function Write-QLog([string]$Msg) {
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  $Msg"
    Add-Content -Path $LogPath -Value $line
    Write-Host $line
}

Write-QLog "=== CAE tet queue start suffix=$CaseSuffix seed=${CaeSeed}mm strain=$Strain rate=${LoadRateMmMin}mm/min ==="
$ProjectPy = Get-ProjectPython
$results = @{}

# Allow -CaseKeys "q05,q1" as well as -CaseKeys q05,q1
$normalizedKeys = @()
foreach ($raw in $CaseKeys) {
    foreach ($part in ($raw -split ',')) {
        $p = $part.Trim().ToLower()
        if ($p) { $normalizedKeys += $p }
    }
}
if ($normalizedKeys.Count -eq 0) { $normalizedKeys = @("bcc", "q05", "q1", "q15") }

foreach ($k in $normalizedKeys) {
    if (-not $CaseMap.ContainsKey($k)) {
        Write-QLog "SKIP unknown case key: $key"
        continue
    }
    $spec = $CaseMap[$k]
    $cad = Get-VerifiedCadStep -Root $Root -Variant $spec.Variant -Cells 4
    $slug = "hu_bai_$($spec.Variant)_L20_4x4x4_solid_cad_f_$CaseSuffix"

    if ($SkipCompleted -and ((Get-JobOutcome -Slug $slug) -eq 'success')) {
        Write-QLog "SKIP completed: $slug"
        $results[$k] = 'skipped'
        continue
    }

    Write-QLog "EXPORT $slug (CAE seed ${CaeSeed}mm) cad=$cad"
    $exportArgs = @(
        "scripts\run_hu_bai_bcc_solid_cad_cae_tet_export.py",
        "--cells", "4",
        "--Q", "$($spec.Q)",
        "--profile", "fast",
        "--case-suffix", $CaseSuffix,
        "--cae-seed", "$CaeSeed",
        "--strain", "$Strain",
        "--load-rate-mm-min", "$LoadRateMmMin",
        "--cad", $cad
    )
    if ($NoSelfContact) { $exportArgs += "--no-lattice-self-contact" }
    if ($ProjectPy -eq "py") {
        & py -3 @exportArgs
    } else {
        & $ProjectPy @exportArgs
    }
    if ($LASTEXITCODE -ne 0) {
        $results[$k] = 'export_failed'
        Write-QLog "FAILED export: $slug exit=$LASTEXITCODE"
        if (-not $ContinueOnFailure) { exit $LASTEXITCODE }
        continue
    }

    if ($ExportOnly) {
        $results[$k] = 'exported'
        continue
    }

    Write-QLog "SUBMIT $slug cpus=$Cpus mem=${MemoryMB}MB"
    $submitArgs = @(
        "-File", (Join-Path $ScriptDir "submit_hu_bai_bcc_solid_cad_compression.ps1"),
        "-SkipExport",
        "-Slug", $slug,
        "-MemoryMB", $MemoryMB,
        "-Cpus", $Cpus
    )
    if ($ForceRerun) { $submitArgs += "-ForceRerun" }
    & powershell @submitArgs
    if ($LASTEXITCODE -ne 0 -and (Get-JobOutcome -Slug $slug) -ne 'success') {
        $results[$k] = 'submit_failed'
        Write-QLog "FAILED submit: $slug exit=$LASTEXITCODE"
        if (-not $ContinueOnFailure) { exit $LASTEXITCODE }
        continue
    }

    $wait = Wait-JobOutcome -Slug $slug -Want "success"
    $results[$k] = $wait
    Write-QLog "DONE $slug -> $wait"
}

Write-QLog "=== CAE tet queue finished: $($results | ConvertTo-Json -Compress) ==="
Write-Host ""
Write-Host "Log: $LogPath" -ForegroundColor Cyan
Write-Host "Server sync example:" -ForegroundColor Cyan
Write-Host "  scp -r output/export/hu_bai_*_${CaseSuffix} art@172.20.200.93:/media/art/file/XiangLang/Lattice/LWY/HuBaiLab/output/export/" -ForegroundColor Gray
Write-Host "  ssh art@172.20.200.93 'cd /media/art/file/XiangLang/Lattice/LWY/HuBaiLab && bash scripts/linux/submit_queue.sh --slugs-csv ...'" -ForegroundColor Gray
