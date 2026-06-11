# Merge manual z-slabs (gmsh) then export + submit fast80 for selected Q values.
param(
    [string]$Q = "1.0,1.5",
    [switch]$SkipMerge,
    [switch]$SkipSubmit,
    [switch]$ForceRerun,
    [int]$MemoryMB = 8192,
    [int]$Cpus = 4,
    [double]$MeshSize = 1.42,
    [double]$Strain = 0.8
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

function Get-VariantName([double]$q) {
    switch ([math]::Round($q, 2)) {
        0.5 { "sfbls_af2q0p5" }
        1.0 { "sfbls_af2q1" }
        1.5 { "sfbls_af2q1p5" }
        default { throw "Unsupported Q=$q" }
    }
}

$ProjectPy = Get-ProjectPython
function Invoke-Py { param([string[]]$PyArgs)
    if ($ProjectPy -eq "py") { & py -3 @PyArgs } else { & $ProjectPy @PyArgs }
}

$qList = @($Q.Split(",") | ForEach-Object { [double]$_.Trim() })
foreach ($q in $qList) {
    $variant = Get-VariantName $q
    $manualDir = Join-Path $Root "output\cad\manual\hu_bai_${variant}_L20_4x4x4"
    $merged = Join-Path $manualDir "hu_bai_${variant}_L20_4x4x4_solid_merged.step"
    $slug = "hu_bai_${variant}_L20_4x4x4_solid_cad_f_fast80"

    Write-Host ""
    Write-Host "========== Q=$q ($variant) ==========" -ForegroundColor Cyan

    if (-not $SkipMerge) {
        Write-Host "[1/3] Gmsh merge 4 z-slabs ..."
        Invoke-Py @("scripts\merge_manual_zslabs_gmsh.py", "--Q", "$q")
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
        Write-Host "  Copy the confirmed merged STEP to output\cad\verified\ if not already there." -ForegroundColor DarkYellow
    }

    try {
        $cad = Get-VerifiedCadStep -Root $Root -Variant $variant -Cells 4
    } catch {
        Write-Host "[ERROR] $($_.Exception.Message)" -ForegroundColor Red
        exit 1
    }

    if ($SkipSubmit) { continue }

    Write-Host "[2/3] Export INP fast80 (mesh=$MeshSize mm, strain=$([int]($Strain * 100))%) ..."
    Write-Host "  CAD (verified): $cad"
    $exportArgs = @(
        "scripts\run_hu_bai_bcc_solid_cad_export.py",
        "--cells", "4",
        "--Q", "$q",
        "--profile", "fast",
        "--case-suffix", "fast80",
        "--strain", "$Strain",
        "--mesh-size", "$MeshSize",
        "--cad", $cad
    )
    Invoke-Py $exportArgs
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    Write-Host "[3/3] Submit Abaqus ..."
    $submitArgs = @(
        "-File", (Join-Path $ScriptDir "submit_hu_bai_bcc_solid_cad_compression.ps1"),
        "-SkipExport",
        "-Slug", $slug,
        "-MemoryMB", $MemoryMB,
        "-Cpus", $Cpus
    )
    if ($ForceRerun) { $submitArgs += "-ForceRerun" }
    & powershell @submitArgs
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

Write-Host ""
Write-Host "Done: manual merge + fast80 for Q=$($Q -join ', ')." -ForegroundColor Green
