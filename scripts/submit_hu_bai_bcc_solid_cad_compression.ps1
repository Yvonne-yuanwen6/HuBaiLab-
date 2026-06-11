# Hu & Bai 2024 — CAD solid (STEP/X_T) explicit compression + stress-strain curve
param(
    [switch]$ForceRerun,
    [switch]$Continue,
    [switch]$ForceSkip,
    [switch]$SkipExport,
    [switch]$SkipPenetrationCheck,
    [switch]$StrictPenetration,
    [int]$Cells = 3,
    [ValidateSet("pilot", "full")]
    [string]$Stroke = "full",
    [double]$MeshSize = 0,
    [double]$Strain = 0,
    [string]$CadPath = "",
    [double]$StepTime = 0,
    [double]$LoadRateMmMin = 0,
    [double]$ExplicitDt = 0,
    [double]$HoldFraction = -1,
    [string]$CaseSuffix = "",
    [ValidateSet("pair", "coupling_nodes")]
    [string]$ContactMode = "",
    [ValidateSet("", "fast", "paper", "pilot")]
    [string]$Profile = "",
    [string]$Slug = "",
    [int]$MemoryMB = 6144,
    [int]$Cpus = 4
)

$ErrorActionPreference = "Stop"

$ScriptDir = $PSScriptRoot
. (Join-Path $ScriptDir "submit_helpers.ps1")
$Root = (Resolve-Path (Join-Path $ScriptDir "..")).Path
$VenvPy = Join-Path $Root ".venv\Scripts\python.exe"

function Get-ProjectPython {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        if (Test-Path $VenvPy) {
            try { & $VenvPy -c "import sys; sys.exit(0)" 2>$null; if ($LASTEXITCODE -eq 0) { return $VenvPy } } catch { }
            Write-Host "[WARN] .venv broken; using py -3" -ForegroundColor Yellow
        }
        return "py"
    }
    if (Test-Path $VenvPy) { return $VenvPy }
    throw "Python not found."
}

Set-Location $Root
Write-Host "=== Hu & Bai CAD solid compression (STEP mesh + plates) ===" -ForegroundColor Cyan

if ($Continue -and $ForceRerun) {
    Write-Host "[ERROR] Use -Continue OR -ForceRerun, not both." -ForegroundColor Red
    exit 1
}

if (-not $SkipExport) {
    Write-Host "[1/3] Export CAD solid INP ..."
    $env:PYTHONPATH = $Root
    $ProjectPy = Get-ProjectPython
    $exportArgs = @(
        "scripts\run_hu_bai_bcc_solid_cad_export.py",
        "--cells", $Cells,
        "--stroke", $Stroke
    )
    if ($Profile) { $exportArgs += @("--profile", $Profile) }
    if ($CadPath) { $exportArgs += @("--cad", $CadPath) }
    if ($MeshSize -gt 0) { $exportArgs += @("--mesh-size", $MeshSize) }
    if ($Strain -gt 0) { $exportArgs += @("--strain", $Strain) }
    if ($StepTime -gt 0) { $exportArgs += @("--step-time", $StepTime) }
    if ($LoadRateMmMin -gt 0) { $exportArgs += @("--load-rate-mm-min", $LoadRateMmMin) }
    if ($ExplicitDt -gt 0) { $exportArgs += @("--explicit-dt", $ExplicitDt) }
    if ($HoldFraction -ge 0) { $exportArgs += @("--hold-fraction", $HoldFraction) }
    if ($CaseSuffix) { $exportArgs += @("--case-suffix", $CaseSuffix) }
    if ($ContactMode) { $exportArgs += @("--contact-mode", $ContactMode) }
    if ($ProjectPy -eq "py") {
        & py -3 @exportArgs
    } else {
        & $ProjectPy @exportArgs
    }
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
} else {
    Write-Host "[1/3] Skip export (using existing INP)" -ForegroundColor Yellow
}

$manifestOverride = ''
if ($Slug) {
    $manifestOverride = Join-Path $Root "output\export\$Slug\case_manifest.json"
} elseif ($SkipExport -and -not $CaseSuffix -and $Profile -eq 'fast') {
    $CaseSuffix = 'fast'
}
if ($SkipExport -and $CaseSuffix) {
    $strokeTag = if ($Stroke -eq 'pilot') { 'p' } else { 'f' }
    if ($Profile -eq 'fast') { $strokeTag = 'f' }
    $slugGuess = "hu_bai_bcc_af2q0_L20_${Cells}x${Cells}x${Cells}_solid_cad_${strokeTag}_$CaseSuffix"
    $manifestOverride = Join-Path $Root "output\export\$slugGuess\case_manifest.json"
}
$case = if ($manifestOverride -and (Test-Path $manifestOverride)) {
    Read-ActiveCaseManifest -Root $Root -ManifestPath $manifestOverride
} else {
    Read-ActiveCaseManifest -Root $Root
}
$JobDir = $case.job_dir
$PostDir = $case.post_dir
$JobName = $case.job_name
$InpSrc = $case.compression_inp
$InpJob = Join-Path $JobDir $case.job_inp_name
$Meta = $case.meta_json
$Odb = $case.odb
$Sta = Join-Path $JobDir ($JobName + ".sta")
$Lck = Join-Path $JobDir ($JobName + ".lck")

Write-Host "  Case: $($case.slug)" -ForegroundColor Cyan
Write-Host "  CAD STEP: $($case.cad_step)"

if (-not (Test-Path $InpSrc)) {
    Write-Host "[ERROR] Missing: $InpSrc" -ForegroundColor Red
    exit 1
}

New-Item -ItemType Directory -Force -Path $JobDir, $PostDir | Out-Null
Copy-Item -Path $InpSrc -Destination $InpJob -Force

if (-not (Select-String -Path $InpJob -Pattern "\*Step|\*Dynamic|\*Contact" -Quiet)) {
    Write-Host "[ERROR] INP missing compression blocks. Re-export." -ForegroundColor Red
    exit 1
}
Write-Host "  Compression INP OK" -ForegroundColor Green

$manifestPath = if ($manifestOverride -and (Test-Path $manifestOverride)) {
    $manifestOverride
} elseif ($case.case_manifest) {
    $case.case_manifest
} else {
    Join-Path (Join-Path $case.export_dir 'case_manifest.json')
}
if (-not (Test-Path $manifestPath)) {
    $manifestPath = Join-Path $Root "output\active_case.json"
}
Invoke-PenetrationRiskCheck -Root $Root -ManifestPath $manifestPath -InpPath $InpJob -MetaPath $Meta `
    -SkipPenetrationCheck:$SkipPenetrationCheck -StrictPenetration:$StrictPenetration

$skipSolve = Confirm-SkipCompletedSolve -JobName $JobName -JobDir $JobDir -OdbPath $Odb -StaPath $Sta `
    -InpJobPath $InpJob -ForceRerun:$ForceRerun -ForceSkip:$ForceSkip
if ($Continue -and -not $ForceSkip) {
    if (Test-AbaqusJobCompleted -StaPath $Sta -OdbPath $Odb) {
        Write-Host "[Continue] Job already completed successfully; skipping solve." -ForegroundColor Cyan
        $skipSolve = $true
    } else {
        $skipSolve = $false
    }
}
if ($skipSolve -and (Test-Path $Lck)) {
    Remove-Item $Lck -Force -ErrorAction SilentlyContinue
}

if (-not $skipSolve) {
    Set-Location $JobDir
    if (-not (Get-Command abaqus -ErrorAction SilentlyContinue)) {
        Write-Host "[ERROR] abaqus not in PATH." -ForegroundColor Yellow
        exit 1
    }
    if ($Continue) {
        if (-not (Test-AbaqusRestartAvailable -JobDir $JobDir -JobName $JobName -ManifestPath $manifestPath -ExportInpPath $InpSrc)) {
            Write-Host "[ERROR] No Explicit restart checkpoint (*Restart, write in INP)." -ForegroundColor Red
            Write-Host "  Re-export INP (new exports include restart), then -ForceRerun once." -ForegroundColor Yellow
            Write-Host "  The current partial ODB cannot be continued." -ForegroundColor Yellow
            exit 1
        }
        Write-Host '[2/3] Continue: resume from restart checkpoint ...' -ForegroundColor Yellow
        Prepare-AbaqusJobContinue -JobDir $JobDir -JobName $JobName -Force
        Write-Host "[2/3] Submit Abaqus restart (cwd: $JobDir) ..."
        abaqus job=$JobName oldjob=$JobName restart cpus=$Cpus memory=$MemoryMB interactive
    } else {
        Write-Host '[2/3] Re-solve: prepare job directory ...' -ForegroundColor Yellow
        Prepare-AbaqusJobRerun -JobDir $JobDir -JobName $JobName -Force:$ForceRerun
        Write-Host "[2/3] Submit Abaqus (cwd: $JobDir) ..."
        abaqus job=$JobName input=$($case.job_inp_name) oldjob=delete cpus=$Cpus memory=$MemoryMB interactive
    }
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    $Dat = Join-Path $JobDir ($JobName + ".dat")
    if ((Test-Path $Dat) -and ((Get-Content $Dat -Raw) -match '\*\*\*ERROR')) {
        Write-Host "[ERROR] See $JobName.dat" -ForegroundColor Red
        exit 1
    }
    if (-not (Test-Path $Odb)) {
        Write-Host "[ERROR] $Odb not found" -ForegroundColor Red
        exit 1
    }
}

Set-Location $Root
Write-Host "Done. ODB: $Odb" -ForegroundColor Green

Write-Host "[3/3] Post-process stress-strain ..."
$extract = Join-Path $Root "scripts\extract_stress_strain_from_odb.py"
$Csv = $case.stress_strain_csv
$Raw = $case.stress_strain_raw_csv
$Png = $case.stress_strain_png
$YieldJson = $case.yield_json

if (Get-Command abaqus -ErrorAction SilentlyContinue) {
    abaqus python $extract --odb $Odb --meta $Meta --csv $Csv --raw-csv $Raw --force-mode plate_ref --yield-json $YieldJson
    if ($LASTEXITCODE -ne 0) {
        abaqus python $extract --odb $Odb --meta $Meta --csv $Csv --raw-csv $Raw --force-mode bottom_field --yield-json $YieldJson
    }
    if (Test-Path $Csv) {
        $plotRc = Invoke-PlotStressStrain -Root $Root -Csv $Csv -Png $Png
        if ($plotRc -ne 0) {
            Write-Host "[WARN] Plot failed (exit $plotRc)." -ForegroundColor Yellow
        }
        Write-Host "  CSV: $Csv" -ForegroundColor Green
        if (Test-Path $Png) { Write-Host "  PNG: $Png" -ForegroundColor Green }
    }
}
