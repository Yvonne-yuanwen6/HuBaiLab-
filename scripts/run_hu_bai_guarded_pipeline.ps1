# Memory-guarded sequential HuBaiLab pipeline: CAD fuse -> fast80 export/submit.
# Only one heavy OCC job at a time; waits for RAM before each step.
param(
    [switch]$SkipGeneration,
    [switch]$SkipFast80,
    [switch]$ForceRerun,
    [double]$MinFreeGB = 3.0,
    [int]$MemoryMB = 8192,
    [int]$Cpus = 4,
    [double]$MeshSize = 1.42,
    [double]$Strain = 0.8,
    [int]$RamPollSec = 20
)

$ErrorActionPreference = "Stop"
$ScriptDir = $PSScriptRoot
. (Join-Path $ScriptDir "submit_helpers.ps1")
$Root = (Resolve-Path (Join-Path $ScriptDir "..")).Path
Set-Location $Root
$env:PYTHONPATH = $Root

$LogDir = Join-Path $Root "output\reports"
$QueueLog = Join-Path $LogDir "hu_bai_guarded_queue.log"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

$cases = @(
    @{ Q = 0.5; Variant = "sfbls_af2q0p5" },
    @{ Q = 1.0; Variant = "sfbls_af2q1" },
    @{ Q = 1.5; Variant = "sfbls_af2q1p5" }
)

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

function Write-QLog([string]$Msg) {
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $Msg"
    Add-Content -Path $QueueLog -Value $line
    Write-Host $line
}

function Get-RamFreeGB {
    $os = Get-CimInstance Win32_OperatingSystem
    [math]::Round($os.FreePhysicalMemory / 1MB, 2)
}

function Wait-Ram([string]$Label) {
    while ($true) {
        $free = Get-RamFreeGB
        $occ = @(Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
            Where-Object { $_.CommandLine -match 'run_hu_bai_bcc|merge_manual_zslabs|prepare_manual_zslabs|_occ_fuse' }).Count
        if ($free -ge $MinFreeGB -and $occ -eq 0) {
            Write-QLog "RAM OK ($free GB free, no OCC jobs) -> $Label"
            return
        }
        Write-QLog "waiting RAM ($free GB free, need >= $MinFreeGB GB; OCC jobs=$occ) before: $Label"
        Start-Sleep -Seconds $RamPollSec
    }
}

function Test-StepReady {
    param([string]$Variant)
    $cadDir = Join-Path $Root "output\cad"
    $step = Join-Path $cadDir "hu_bai_${Variant}_L20_4x4x4_solid_array.step"
    $manifest = Join-Path $cadDir "hu_bai_${Variant}_L20_4x4x4_array_sw_manifest.json"
    if (-not (Test-Path $step)) { return $false }
    if (-not (Test-Path $manifest)) { return $false }
    try {
        $m = Get-Content $manifest -Raw | ConvertFrom-Json
        if ([int]$m.fused_volume_count -ne 1) { return $false }
        if ($m.step_solidworks_safe -eq $false) { return $false }
    } catch {
        return $false
    }
    return $true
}

function Test-Fast80Done {
    param([string]$Slug)
    $jobDir = Join-Path $Root "output\jobs\$Slug"
    $odb = Join-Path $jobDir "$Slug.odb"
    $sta = Join-Path $jobDir "$Slug.sta"
    if (Test-Path $odb) { return $true }
    if (Test-Path $sta) {
        $last = Get-Content $sta -Tail 5 -ErrorAction SilentlyContinue | Out-String
        if ($last -match 'COMPLETED') { return $true }
    }
    return $false
}

function Invoke-Py {
    param([string[]]$PyArgs)
    $ProjectPy = Get-ProjectPython
    if ($ProjectPy -eq "py") { & py -3 @PyArgs } else { & $ProjectPy @PyArgs }
}

function Wait-AbaqusIdle {
    while ($true) {
        $abaqus = Get-Process standard, explicit, pre, ABQcaeK -ErrorAction SilentlyContinue
        if (-not $abaqus) { return }
        Write-QLog "waiting Abaqus solver ($($abaqus.Count) proc) ..."
        Start-Sleep -Seconds 30
    }
}

Write-QLog "=== guarded pipeline start (min_free=${MinFreeGB}GB) ==="

if (-not $SkipGeneration) {
    foreach ($case in $cases) {
        $variant = $case.Variant
        $q = $case.Q
        if (Test-StepReady -Variant $variant) {
            Write-QLog "[SKIP gen] $variant STEP ready"
            continue
        }
        Wait-Ram "generate $variant (Q=$q)"
        Write-QLog "[GEN] $variant (Q=$q)"
        Invoke-Py @(
            "scripts\run_hu_bai_bcc_unitcell_sequential_step_fuse.py",
            "--cells", "4",
            "--Q", "$q",
            "--keep-work-dir"
        )
        if ($LASTEXITCODE -ne 0) {
            Write-QLog "[ERROR] generation failed: $variant exit=$LASTEXITCODE"
            exit $LASTEXITCODE
        }
        if (-not (Test-StepReady -Variant $variant)) {
            Write-QLog "[ERROR] STEP not valid after generation: $variant"
            exit 1
        }
    }
}

if ($SkipFast80) {
    Write-QLog "Skip fast80 (--SkipFast80)"
    exit 0
}

foreach ($case in $cases) {
    $variant = $case.Variant
    $q = $case.Q
    $slug = "hu_bai_${variant}_L20_4x4x4_solid_cad_f_fast80"
    try {
        $step = Get-VerifiedCadStep -Root $Root -Variant $variant -Cells 4
    } catch {
        Write-QLog "[ERROR] $($_.Exception.Message)"
        exit 1
    }

    if (-not $ForceRerun -and (Test-Fast80Done -Slug $slug)) {
        Write-QLog "[SKIP fast80] $slug already completed"
        continue
    }

    Wait-AbaqusIdle
    Wait-Ram "export $slug"
    Write-QLog "[EXPORT] $slug"
    Invoke-Py @(
        "scripts\run_hu_bai_bcc_solid_cad_export.py",
        "--cells", "4",
        "--Q", "$q",
        "--profile", "fast",
        "--case-suffix", "fast80",
        "--strain", "$Strain",
        "--mesh-size", "$MeshSize",
        "--cad", $step
    )
    if ($LASTEXITCODE -ne 0) {
        Write-QLog "[ERROR] export failed: $slug"
        exit $LASTEXITCODE
    }

    Wait-Ram "submit $slug"
    Write-QLog "[SUBMIT] $slug"
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
        Write-QLog "[ERROR] submit failed: $slug"
        exit $LASTEXITCODE
    }
}

Write-QLog "=== guarded pipeline complete ==="
