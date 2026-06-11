# Sequential: 4x4x4 BCC (Q=0) fast80, then SFBLS Q=1 fast80.
param(
    [switch]$SkipBcc,
    [switch]$SkipQ1,
    [switch]$ForceRerun,
    [int]$MemoryMB = 8192,
    [int]$Cpus = 4,
    [double]$MeshSize = 0.8,
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

function Ensure-BccFastExport {
    $fastSlug = "hu_bai_bcc_af2q0_L20_4x4x4_solid_cad_f_fast"
    $fastExport = Join-Path $Root "output\export\$fastSlug"
    $fastInp = Join-Path $fastExport "$fastSlug.inp"
    $fastMeta = Join-Path $fastExport "${fastSlug}_meta.json"
    $fastManifest = Join-Path $fastExport "case_manifest.json"
    if ((Test-Path $fastInp) -and (Test-Path $fastMeta) -and (Test-Path $fastManifest)) {
        return
    }

    $jobInp = Join-Path $Root "output\jobs\$fastSlug\$fastSlug.inp"
    if (-not (Test-Path $jobInp)) {
        Write-Host "[ERROR] Missing successful BCC fast job INP: $jobInp" -ForegroundColor Red
        exit 1
    }

    Write-Host "Bootstrap BCC fast export from completed job INP ..." -ForegroundColor Yellow
    New-Item -ItemType Directory -Force -Path $fastExport | Out-Null
    Copy-Item -Path $jobInp -Destination $fastInp -Force

    $meta = @{
        nx = 4; ny = 4; nz = 4
        cell_size = 20.0
        height_ratio = 0.0
        compression_displacement = 36.0
        step_time = 86.4
        step_name = "Compression"
        reference_area_mm2 = 6400.0
        reference_height_mm = 80.0
        mesh_z_min = -41.0
        mesh_z_max = 41.0
        plate_ref_node_id = 56986
        amplitude_hold_fraction = 0.02
        loading_direction = "top_down"
        case_slug = $fastSlug
        geometry_tag = "hu_bai_bcc_af2q0_L20_4x4x4_cad"
        support_type = "bcc_cad_solid"
        support_angle_deg = $null
        r_frame = 1.0
        r_support = 1.0
        r_vertical = 1.0
    }
    $metaJson = ($meta | ConvertTo-Json -Depth 4) + "`n"
    [System.IO.File]::WriteAllText($fastMeta, $metaJson, (New-Object System.Text.UTF8Encoding $false))

    $manifest = @{
        slug = $fastSlug
        profile = "fast"
        stroke = "full"
        stroke_tag = "f"
        structure = "BCC_AF2Q0"
        reference = "Hu & Bai 2024 — CAD solid (STEP/X_T) explicit compression"
        figure_target = "Fig. 3.3 compressive stress-strain (solid C3D4 mesh)"
        export_dir = $fastExport
        job_dir = Join-Path $Root "output\jobs\$fastSlug"
        post_dir = Join-Path $Root "output\post\$fastSlug"
        compression_inp = $fastInp
        case_manifest = $fastManifest
        meta_json = $fastMeta
        cad_step = Join-Path $Root "output\cad\hu_bai_bcc_af2q0_L20_4x4x4_solid_array.step"
        cad_stl = $null
        cad_xt = $null
        odb = Join-Path $Root "output\jobs\$fastSlug\$fastSlug.odb"
        job_name = $fastSlug
        job_inp_name = "$fastSlug.inp"
        stress_strain_csv = Join-Path $Root "output\post\$fastSlug\${fastSlug}_stress_strain.csv"
        stress_strain_raw_csv = Join-Path $Root "output\post\$fastSlug\${fastSlug}_stress_strain_raw.csv"
        stress_strain_png = Join-Path $Root "output\post\$fastSlug\${fastSlug}_stress_strain.png"
        yield_json = Join-Path $Root "output\post\$fastSlug\${fastSlug}_yield.json"
        paper_params = @{
            cell_size_mm = 20.0
            rod_diameter_mm = 2.0
            block_cells = @(4, 4, 4)
        }
        material = @{
            E_MPa = 25.0
            nu = 0.47
            yield_MPa = 4.69
            density_kg_m3 = 1135.0
        }
        mesh = @{
            element = "C3D4"
            source = "gmsh_step_volume"
            mesh_size_mm = 1.2
            node_count = 0
            element_count = 0
        }
        loading = @{
            compression_displacement_mm = 36.0
            target_engineering_strain = 0.45
            step_time_s = 216.0
            load_rate_mm_min = 10.0
            quasi_static_paper_rate = $false
            step_time_overridden = $false
            friction = 0.1
            explicit_dt = 0.0005
            amplitude_hold_fraction = 0.02
            explicit_mass_scaling = 50.0
            explicit_n_increments_est = 432000
            case_suffix = "fast"
            contact_mode = "pair"
            fixed_bottom_plate = $true
            plate_margin_mm = 10.0
            plate_embed_mm = 0.6
            top_surface_z_band_mm = 10.0
            top_face_normal_z_min = 0.35
            lattice_load_faces = 22529
            lattice_load_nodes = 7723
            lattice_self_contact = $true
        }
    }
    $manifestJson = ($manifest | ConvertTo-Json -Depth 6) + "`n"
    [System.IO.File]::WriteAllText($fastManifest, $manifestJson, (New-Object System.Text.UTF8Encoding $false))
}

function Invoke-BccFast80ExportSubmit {
    $cadCandidates = @(
        (Join-Path $Root "output\cad\verified\hu_bai_bcc_af2q0_L20_4x4x4_solid_merged.STEP"),
        (Join-Path $Root "output\cad\hu_bai_bcc_af2q0_L20_4x4x4_solid_array.step")
    )
    $cad = $cadCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
    if (-not $cad) {
        Write-Host "[ERROR] Missing BCC 4x4x4 CAD STEP. Expected one of:" -ForegroundColor Red
        $cadCandidates | ForEach-Object { Write-Host "  $_" -ForegroundColor Red }
        exit 1
    }
    Invoke-ExportSubmit `
        -Label "BCC Q=0 fast80" `
        -Q 0 `
        -Slug "hu_bai_bcc_af2q0_L20_4x4x4_solid_cad_f_fast80" `
        -Cad $cad
}

function Invoke-BccFast80CloneSubmit {
    # Legacy: clone mesh from fast (1.2 mm). Prefer Invoke-BccFast80ExportSubmit for new defaults.
    Ensure-BccFastExport
    $ProjectPy = Get-ProjectPython
    $fastSlug = "hu_bai_bcc_af2q0_L20_4x4x4_solid_cad_f_fast"
    $slug = "hu_bai_bcc_af2q0_L20_4x4x4_solid_cad_f_fast80"

    Write-Host ""
    Write-Host "========== BCC Q=0 fast80 (clone mesh from fast) ==========" -ForegroundColor Cyan
    Write-Host "[1/2] Clone loading fast -> fast80 (80% strain, same mesh) ..."
    $cloneArgs = @(
        "scripts\clone_cad_compression_loading.py",
        "--from-slug", $fastSlug,
        "--case-suffix", "fast80",
        "--strain", "$Strain"
    )
    if ($ProjectPy -eq "py") {
        & py -3 @cloneArgs
    } else {
        & $ProjectPy @cloneArgs
    }
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[ERROR] Clone failed: $slug" -ForegroundColor Red
        exit $LASTEXITCODE
    }

    Write-Host "[2/2] Submit Abaqus ..."
    $submitArgs = @(
        "-File", (Join-Path $ScriptDir "submit_hu_bai_bcc_solid_cad_compression.ps1"),
        "-SkipExport",
        "-Slug", $slug,
        "-MemoryMB", $MemoryMB,
        "-Cpus", $Cpus,
        "-ForceRerun"
    )
    & powershell @submitArgs
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[ERROR] Submit failed: $slug" -ForegroundColor Red
        exit $LASTEXITCODE
    }
}

function Invoke-ExportSubmit {
    param(
        [string]$Label,
        [double]$Q,
        [string]$Slug,
        [string]$Cad
    )
    if (-not (Test-Path $Cad)) {
        Write-Host "[ERROR] Missing CAD for ${Label}: $Cad" -ForegroundColor Red
        exit 1
    }

    $ProjectPy = Get-ProjectPython
    Write-Host ""
    Write-Host "========== $Label ($Slug) ==========" -ForegroundColor Cyan
    Write-Host "  CAD: $Cad"

    Write-Host "[1/2] Export INP (fast80, mesh=$MeshSize mm, strain=$([int]($Strain * 100))%) ..."
    $exportArgs = @(
        "scripts\run_hu_bai_bcc_solid_cad_export.py",
        "--cells", "4",
        "--Q", "$Q",
        "--profile", "fast",
        "--case-suffix", "fast80",
        "--strain", "$Strain",
        "--mesh-size", "$MeshSize",
        "--cad", $Cad
    )
    if ($ProjectPy -eq "py") {
        & py -3 @exportArgs
    } else {
        & $ProjectPy @exportArgs
    }
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[ERROR] Export failed: $Slug" -ForegroundColor Red
        exit $LASTEXITCODE
    }

    Write-Host "[2/2] Submit Abaqus ..."
    $submitArgs = @(
        "-File", (Join-Path $ScriptDir "submit_hu_bai_bcc_solid_cad_compression.ps1"),
        "-SkipExport",
        "-Slug", $Slug,
        "-MemoryMB", $MemoryMB,
        "-Cpus", $Cpus
    )
    if ($ForceRerun) { $submitArgs += "-ForceRerun" }
    & powershell @submitArgs
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[ERROR] Submit failed: $Slug" -ForegroundColor Red
        exit $LASTEXITCODE
    }
}

Write-Host "=== 4x4x4 BCC fast80 -> Q1 fast80 pipeline ===" -ForegroundColor Yellow

if (-not $SkipBcc) {
    Invoke-BccFast80ExportSubmit
}

if (-not $SkipQ1) {
    try {
        $q1Cad = Get-VerifiedCadStep -Root $Root -Variant "sfbls_af2q1" -Cells 4
    } catch {
        Write-Host "[ERROR] $($_.Exception.Message)" -ForegroundColor Red
        exit 1
    }
    Invoke-ExportSubmit `
        -Label "SFBLS Q=1 fast80" `
        -Q 1 `
        -Slug "hu_bai_sfbls_af2q1_L20_4x4x4_solid_cad_f_fast80" `
        -Cad $q1Cad
}

Write-Host ""
Write-Host "Pipeline complete: BCC fast80 then Q1 fast80." -ForegroundColor Green
