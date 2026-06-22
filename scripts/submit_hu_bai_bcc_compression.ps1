# Hu & Bai 2024 BCC quasi-static compression (Fig. 3.3 baseline)
param(
    [switch]$ForceRerun,
    [switch]$ForceSkip,
    [switch]$SkipExport,
    [switch]$SkipPenetrationCheck,
    [switch]$StrictPenetration
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
Write-Host "=== Hu & Bai BCC compression (DEPRECATED — use solid_cad) ===" -ForegroundColor Yellow
Write-Host "  Use: scripts/submit_hu_bai_bcc_solid_cad_compression.ps1" -ForegroundColor Yellow
exit 2
if (-not $SkipExport) {
    Write-Host "[1/3] Export solid INP ..."
    $env:PYTHONPATH = $Root
    $ProjectPy = Get-ProjectPython
    if ($ProjectPy -eq "py") {
        & py -3 scripts\run_hu_bai_bcc_export.py --skip-wireframe
    } else {
        & $ProjectPy scripts\run_hu_bai_bcc_export.py --skip-wireframe
    }
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
} else {
    Write-Host "[1/3] Skip export (using existing INP)" -ForegroundColor Yellow
}

$case = Read-ActiveCaseManifest -Root $Root
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
Write-Host "  Export: $($case.export_dir)"
Write-Host "  Job:    $JobDir"

if (-not (Test-Path $InpSrc)) {
    Write-Host "[ERROR] Missing: $InpSrc" -ForegroundColor Red
    exit 1
}

New-Item -ItemType Directory -Force -Path $JobDir, $PostDir | Out-Null
Copy-Item -Path $InpSrc -Destination $InpJob -Force
if (Test-Path $case.topology_b31_inp) {
    Copy-Item -Path $case.topology_b31_inp -Destination (Join-Path $JobDir ($JobName + "_topology_b31.inp")) -Force
}

if (-not (Select-String -Path $InpJob -Pattern "\*Coupling|\*Boundary|\*Step" -Quiet)) {
    Write-Host "[ERROR] INP missing compression step blocks. Re-export." -ForegroundColor Red
    exit 1
}
Write-Host "  Compression INP OK" -ForegroundColor Green

$manifestPath = if ($case.case_manifest) { $case.case_manifest } else { Join-Path $Root "output\active_case.json" }
Invoke-PenetrationRiskCheck -Root $Root -ManifestPath $manifestPath -InpPath $InpJob -MetaPath $Meta `
    -SkipPenetrationCheck:$SkipPenetrationCheck -StrictPenetration:$StrictPenetration

$skipSolve = Confirm-SkipCompletedSolve -JobName $JobName -JobDir $JobDir -OdbPath $Odb -StaPath $Sta `
    -InpJobPath $InpJob -ForceRerun:$ForceRerun -ForceSkip:$ForceSkip
if ($skipSolve -and (Test-Path $Lck)) {
    Remove-Item $Lck -Force -ErrorAction SilentlyContinue
}

if (-not $skipSolve) {
    Write-Host '[2/3] Re-solve: prepare job directory ...' -ForegroundColor Yellow
    Prepare-AbaqusJobRerun -JobDir $JobDir -JobName $JobName -Force:$ForceRerun `
        -Root $Root -PostDir $PostDir -Slug $case.slug
    Write-Host "[2/3] Submit Abaqus (cwd: $JobDir) ..."
    Set-Location $JobDir
    if (-not (Get-Command abaqus -ErrorAction SilentlyContinue)) {
        Write-Host "[ERROR] abaqus not in PATH." -ForegroundColor Yellow
        exit 1
    }
    abaqus job=$JobName input=$($case.job_inp_name) cpus=4 memory=4096 interactive
    if ($LASTEXITCODE -ne 0) {
        Archive-FailedAbaqusJob -Root $Root -JobDir $JobDir -JobName $JobName `
            -Slug $case.slug -PostDir $PostDir -StaPath $Sta -Reason 'abaqus_exit_error'
        exit $LASTEXITCODE
    }
    $Dat = Join-Path $JobDir ($JobName + ".dat")
    if ((Test-Path $Dat) -and ((Get-Content $Dat -Raw) -match '\*\*\*ERROR')) {
        Archive-FailedAbaqusJob -Root $Root -JobDir $JobDir -JobName $JobName `
            -Slug $case.slug -PostDir $PostDir -StaPath $Sta -Reason 'abaqus_dat_error'
        Write-Host "[ERROR] See $JobName.dat" -ForegroundColor Red
        exit 1
    }
    if (-not (Test-Path $Odb)) {
        Archive-FailedAbaqusJob -Root $Root -JobDir $JobDir -JobName $JobName `
            -Slug $case.slug -PostDir $PostDir -StaPath $Sta -Reason 'missing_odb'
        Write-Host "[ERROR] $Odb not found" -ForegroundColor Red
        exit 1
    }
    if (-not (Test-AbaqusJobCompleted -StaPath $Sta -OdbPath $Odb)) {
        Archive-FailedAbaqusJob -Root $Root -JobDir $JobDir -JobName $JobName `
            -Slug $case.slug -PostDir $PostDir -StaPath $Sta
        Write-Host "[ERROR] Job did not complete successfully (see $Sta)." -ForegroundColor Red
        exit 1
    }
}

Set-Location $Root
Write-Host "Done. ODB: $Odb" -ForegroundColor Green

Write-Host "[3/3] Post-process ..."
$extract = Join-Path $Root "scripts\extract_stress_strain_from_odb.py"
$Csv = $case.stress_strain_csv
$Raw = $case.stress_strain_raw_csv
$Png = $case.stress_strain_png
$YieldJson = $case.yield_json

if (Get-Command abaqus -ErrorAction SilentlyContinue) {
    abaqus python $extract --odb $Odb --meta $Meta --csv $Csv --raw-csv $Raw --force-mode paper --curve-method paper --yield-json $YieldJson
    if ($LASTEXITCODE -ne 0) {
        abaqus python $extract --odb $Odb --meta $Meta --csv $Csv --raw-csv $Raw --force-mode fixed_bottom_ref --curve-method paper --yield-json $YieldJson
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