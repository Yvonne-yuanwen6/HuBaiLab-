# Q0.5 unit-cell element/mesh study:
#   A: C3D4  rods/d=3
#   B: C3D4  rods/d=5
#   C: C3D10M rods/d=3
# Same material / BC / load; Energy Output includes ALLAE.
param(
    [ValidateSet("export", "submit", "all", "post")]
    [string]$Mode = "all",
    [ValidateSet("A", "B", "C", "all")]
    [string]$Only = "all",
    [int]$Cpus = 8,
    [int]$MemoryMB = 12288,
    [switch]$SkipMeshIfExists
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $Root
$env:PYTHONPATH = $Root
$env:Path = "D:\Apps\SIMULIA\Commands;" + $env:Path

. (Join-Path $PSScriptRoot "submit_helpers.ps1")

$LogDir = Join-Path $Root "output\logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$Log = Join-Path $LogDir "q05_uc_elem_mesh_study.log"

function Write-QLog([string]$msg) {
    $line = "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $msg
    Write-Host $line
    Add-Content -Path $Log -Value $line -Encoding UTF8
}

$Cad = Join-Path $Root "output\cad\verified\hu_bai_sfbls_af2q0p5_L20_1x1x1_paper_box_array.step"
if (-not (Test-Path $Cad)) {
    throw "Missing verified Q0.5 unitcell STEP: $Cad"
}

# Shared physics (materials / BC / load identical across A/B/C)
$Common = @(
    "--Q", "0.5",
    "--Af", "2.0",
    "--cells", "1",
    "--L", "20",
    "--rod-diameter", "2.0",
    "--cad", $Cad,
    "--profile", "fast",
    "--mesh-locally",
    "--cae-virtual-topology",
    "--cae-mesh-quality", "lattice_curve",
    "--strain", "0.80",
    "--load-rate-mm-min", "5",
    "--explicit-dt", "0.0005",
    "--explicit-dt-mode", "automatic",
    "--contact-mode", "pair",
    "--contact-store-offsets",
    "--contact-settle",
    "--material-model", "neo_hooke"
)

$Cases = @(
    @{
        Id = "A"
        Label = "C3D4 rods/d=3"
        Suffix = "cae_tet0p6mm80_5mmin_uc_c3d4_r3"
        Seed = 0.6
        Elem = "C3D4"
        Rods = 3.0
    },
    @{
        Id = "B"
        Label = "C3D4 rods/d=5"
        Suffix = "cae_tet0p4mm80_5mmin_uc_c3d4_r5"
        Seed = 0.4
        Elem = "C3D4"
        Rods = 5.0
    },
    @{
        Id = "C"
        Label = "C3D10M rods/d=3"
        Suffix = "cae_tet0p6mm80_5mmin_uc_c3d10m_r3"
        Seed = 0.6
        Elem = "C3D10M"
        Rods = 3.0
    }
)

function Get-Slug([string]$suffix) {
    return "hu_bai_sfbls_af2q0p5_L20_1x1x1_solid_cad_f_$suffix"
}

function Export-Case($c) {
    $slug = Get-Slug $c.Suffix
    $meshInp = Join-Path $Root "output\export\$slug\${slug}_cae_mesh.inp"
    $jobInp = Join-Path $Root "output\export\$slug\$slug.inp"
    Write-QLog "EXPORT $($c.Id) $($c.Label) -> $slug"

    $args = $Common + @(
        "--case-suffix", $c.Suffix,
        "--cae-seed", "$($c.Seed)",
        "--cae-element-type", $c.Elem,
        "--cae-rods-per-diameter", "$($c.Rods)"
    )
    if ($SkipMeshIfExists -and (Test-Path $meshInp)) {
        $args += @("--cae-mesh-inp", $meshInp)
        Write-QLog "  reuse mesh INP: $meshInp"
    }

    & py -3 (Join-Path $Root "scripts\run_hu_bai_bcc_solid_cad_cae_tet_export.py") @args
    if ($LASTEXITCODE -ne 0) { throw "export failed for $($c.Id) exit=$LASTEXITCODE" }

    # Sanity: ALLAE + element type
    if (-not (Test-Path $jobInp)) { throw "missing job INP: $jobInp" }
    $txt = Get-Content $jobInp -Raw
    if ($txt -notmatch "ALLAE") { throw "ALLAE missing in $jobInp" }
    if ($txt -notmatch [regex]::Escape("*Element, type=$($c.Elem)")) {
        Write-QLog "WARN: expected *Element, type=$($c.Elem) not found (check mesh)"
    }
    Write-QLog "OK export $($c.Id) ALLAE present"
    return $slug
}

function Submit-Case($c) {
    $slug = Get-Slug $c.Suffix
    $exportDir = Join-Path $Root "output\export\$slug"
    $jobDir = Join-Path $Root "output\jobs\$slug"
    $postDir = Join-Path $Root "output\post\$slug"
    New-Item -ItemType Directory -Force -Path $jobDir, $postDir | Out-Null

    $srcInp = Join-Path $exportDir "$slug.inp"
    if (-not (Test-Path $srcInp)) { throw "missing $srcInp — run export first" }
    Copy-Item -Force $srcInp (Join-Path $jobDir "$slug.inp")

    $sta = Join-Path $jobDir "$slug.sta"
    $odb = Join-Path $jobDir "$slug.odb"
    if ((Test-Path $sta) -and (Test-Path $odb)) {
        $staText = Get-Content $sta -Raw -ErrorAction SilentlyContinue
        if ($staText -match "THE ANALYSIS HAS COMPLETED SUCCESSFULLY") {
            Write-QLog "SKIP submit $($c.Id) already COMPLETED"
            return $slug
        }
    }

    Write-QLog "SUBMIT $($c.Id) cpus=$Cpus memory=$MemoryMB cwd=$jobDir"
    Push-Location $jobDir
    try {
        & abaqus job=$slug input="$slug.inp" cpus=$Cpus memory=$MemoryMB interactive
        $rc = $LASTEXITCODE
    } finally {
        Pop-Location
    }
    $staPath = Join-Path $jobDir "$slug.sta"
    $datPath = Join-Path $jobDir "$slug.dat"
    $ok = $false
    if (Test-Path $staPath) {
        $staText = Get-Content $staPath -Raw -ErrorAction SilentlyContinue
        $ok = ($staText -match "THE ANALYSIS HAS COMPLETED SUCCESSFULLY")
    }
    $oom = $false
    if (Test-Path $datPath) {
        $datText = Get-Content $datPath -Raw -ErrorAction SilentlyContinue
        if ($datText -match "out-of-memory|memory allocation request failed") { $oom = $true }
    }
    if (-not $ok) {
        $reason = if ($oom) { "OOM" } elseif ($rc -ne 0) { "exit=$rc" } else { "not COMPLETED" }
        throw "submit failed for $($c.Id) ($reason)"
    }
    Write-QLog "DONE submit $($c.Id)"
    return $slug
}

function Post-Case($c) {
    $slug = Get-Slug $c.Suffix
    $jobDir = Join-Path $Root "output\jobs\$slug"
    $postDir = Join-Path $Root "output\post\$slug"
    New-Item -ItemType Directory -Force -Path $postDir | Out-Null
    $odb = Join-Path $jobDir "$slug.odb"
    $energy = Join-Path $postDir "${slug}_energy.csv"
    if (-not (Test-Path $odb)) {
        Write-QLog "POST skip $($c.Id): no ODB"
        return
    }
    Write-QLog "POST energy $($c.Id)"
    & abaqus python (Join-Path $Root "scripts\extract_odb_energy_py2.py") $odb $energy Compression
    # Prefer existing paper extract if present in helpers
    $meta = Join-Path (Join-Path $Root "output\export\$slug") "${slug}_meta.json"
    $csv = Join-Path $postDir "${slug}_stress_strain.csv"
    $extract = Join-Path $Root "scripts\extract_odb_history_py2.py"
    if ((Test-Path $extract) -and (Test-Path $meta)) {
        Write-QLog "POST curve $($c.Id)"
        & abaqus python $extract --odb $odb --meta $meta --csv $csv --force-mode paper --curve-method paper
    }
}

$selected = if ($Only -eq "all") { $Cases } else { $Cases | Where-Object { $_.Id -eq $Only } }
if (-not $selected) { throw "No cases selected" }

Write-QLog "=== Q05 UC elem/mesh study mode=$Mode only=$Only ==="
Write-QLog "CAD: $Cad"

foreach ($c in $selected) {
    if ($Mode -in @("export", "all")) { Export-Case $c | Out-Null }
    if ($Mode -in @("submit", "all")) { Submit-Case $c | Out-Null }
    if ($Mode -eq "post") { Post-Case $c }
}

Write-QLog "=== finished mode=$Mode ==="
