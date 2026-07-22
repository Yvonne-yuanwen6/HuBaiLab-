# Local mirror of server scripts/linux/run_param_batch_cae_sim_queue.sh
# with BATCH_SIM_MESH_PROTOCOL=1.
#
# Flow (same as server):
#   1) heal v3 → CAE seed0.6/fast/vtopo → compression INP   (serial)
#   2) on mesh fail → SKIP, continue next case
#   3) submit Explicit for exported INPs (default max 1 on laptop)
#
#   powershell -File scripts/run_param_batch_cae_sim_local.ps1
#   powershell -File scripts/run_param_batch_cae_sim_local.ps1 -ExportOnly
#   powershell -File scripts/run_param_batch_cae_sim_local.ps1 -Only af2q1_deq2_k1
param(
    [string[]]$Only = @(),
    [switch]$ExportOnly,
    [switch]$ForceRemesh,
    [switch]$RetryKnownMeshFail,
    [int]$Cpus = 6,
    [int]$MemoryMB = 10000,
    [int]$MaxParallel = 1,
    [double]$JobMemoryPct = 45
)

$ErrorActionPreference = "Stop"
$PSNativeCommandUseErrorActionPreference = $false
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $Root
$env:Path = "D:\Apps\SIMULIA\Commands;" + $env:Path

$Slug = "cae_tet0p6mm80_5mmin_paperbox"
$KnownMeshFail = @(
    # True 0-element protocol fails (local 2026-07-20). Do NOT list cases that only failed export.
    "af2q1_deq2_k2",
    "af2q1p5_deq2_k1p5",
    "af1q1_deq2_k1",
    "af2q0p5_deq2_k1p5"
)

$BatchCad = & python -c "from pathlib import Path; root=Path(r'$Root')/'output'/'cad';
cands=[p for p in root.iterdir() if p.is_dir() and (p/'_batch_index.json').is_file()];
print(cands[0] if cands else '')"
$BatchCad = "$BatchCad".Trim()
if (-not $BatchCad) { throw "no cad batch folder with _batch_index.json" }
# ASCII-only sim tree for Windows Abaqus (Chinese cwd → charmap crash).
$SimBatchName = "param_batch"
$BatchName = $SimBatchName
$IndexPath = Join-Path $BatchCad "_batch_index.json"
$SkipPath = Join-Path $Root "output\export\$SimBatchName\_batch_sim_skipped.json"
$LogDir = Join-Path $Root "output\logs"
New-Item -ItemType Directory -Force -Path $LogDir, (Split-Path $SkipPath -Parent) | Out-Null
$RunLog = Join-Path $LogDir "param_batch_cae_sim_local.log"

function Write-Log([string]$msg) {
    $line = "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $msg
    Write-Host $line
    Add-Content -Encoding UTF8 $RunLog $line
}

function Set-SkipCase([string]$cid, [string]$reason) {
    $dir = Split-Path $SkipPath -Parent
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
    $sk = Get-SkipMap
    $sk[$cid] = @{
        reason     = $reason
        updated_at = (Get-Date -Format "o")
        host       = $env:COMPUTERNAME
        protocol   = "BATCH_SIM_MESH_PROTOCOL=1"
    }
    $obj = [ordered]@{
        updated_at = (Get-Date -Format "o")
        skipped    = $sk
    }
    $json = $obj | ConvertTo-Json -Depth 6
    $utf8NoBom = New-Object System.Text.UTF8Encoding $false
    [System.IO.File]::WriteAllText($SkipPath, $json, $utf8NoBom)
}

function Get-SkipMap {
    if (-not (Test-Path -LiteralPath $SkipPath)) { return @{} }
    $raw = [System.IO.File]::ReadAllText($SkipPath)
    $data = $raw | ConvertFrom-Json
    $m = @{}
    if ($data.skipped) {
        foreach ($p in $data.skipped.PSObject.Properties) { $m[$p.Name] = $p.Value }
    }
    return $m
}

function Clear-SkipCase([string]$cid) {
    if (-not (Test-Path -LiteralPath $SkipPath)) { return }
    $sk = Get-SkipMap
    if (-not $sk.ContainsKey($cid)) { return }
    $sk.Remove($cid)
    $obj = [ordered]@{
        updated_at = (Get-Date -Format "o")
        skipped    = $sk
    }
    $json = $obj | ConvertTo-Json -Depth 6
    $utf8NoBom = New-Object System.Text.UTF8Encoding $false
    [System.IO.File]::WriteAllText($SkipPath, $json, $utf8NoBom)
}

# Seed skip file for true local protocol mesh fails; clear false positives that only failed export.
if (-not $RetryKnownMeshFail) {
    foreach ($cid in $KnownMeshFail) {
        Set-SkipCase $cid "mesh protocol failed (seed0.6 + fast + vtopo) — local 2026-07-20"
    }
}
# Wrongly marked after mesh OK + export argparse crash:
foreach ($cid in @("af2q1_deq2_k1", "af2q1_deq2_k1p5")) {
    Clear-SkipCase $cid
}

$pick = & python -c @"
import json
from pathlib import Path
root = Path(r'$Root')
batch = Path(r'$BatchCad')
sim = root / 'output' / 'export' / '$SimBatchName'
post = root / 'output' / 'post' / '$SimBatchName'
slug = '$Slug'
only = '''$($Only -join ' ')'''.split()
only = [x for x in only if x]
force = '$($ForceRemesh.IsPresent)' == 'True'
retry_fail = '$($RetryKnownMeshFail.IsPresent)' == 'True'
known_fail = set('''$($KnownMeshFail -join ' ')'''.split())
idx = json.loads((batch / '_batch_index.json').read_text(encoding='utf-8'))
skip_path = Path(r'$SkipPath')
skipped = set()
if skip_path.is_file():
    sk = json.loads(skip_path.read_text(encoding='utf-8-sig')).get('skipped') or {}
    skipped = set(sk)
need, export_need, done, nos, skp = [], [], [], [], []
for cid in sorted(idx.get('cases') or {}):
    if only and cid not in only:
        continue
    step = batch / cid / f'{cid}_444.step'
    if not step.is_file() or step.stat().st_size < 1_000_000:
        nos.append(cid); continue
    # Complete CSV may still live under legacy Chinese post tree; treat either as DONE.
    csv_paths = [
        post / cid / slug / f'{slug}_stress_strain.csv',
    ]
    for p in (root/'output'/'post').iterdir():
        if p.is_dir() and p.name != 'param_batch':
            csv_paths.append(p / cid / slug / f'{slug}_stress_strain.csv')
    n = 0
    for csv in csv_paths:
        if csv.is_file():
            n = max(n, sum(1 for _ in csv.open(encoding='utf-8', errors='ignore')))
    inp = sim / cid / slug / f'{slug}.inp'
    mesh = sim / cid / slug / f'{slug}_cae_mesh.inp'
    has_inp = inp.is_file() and inp.stat().st_size > 1_000_000
    has_mesh = mesh.is_file() and mesh.stat().st_size > 1_000_000
    if n > 40 and not force:
        done.append(cid); continue
    if has_inp and not force:
        print('SUBMIT_READY', cid)
        continue
    if has_mesh and not force:
        export_need.append(cid)
        continue
    if (cid in known_fail or cid in skipped) and not retry_fail and not force:
        skp.append(cid); continue
    need.append(cid)
for c in need:
    print('MESH', c)
for c in export_need:
    print('EXPORT', c)
for c in done:
    print('DONE', c)
for c in skp:
    print('SKIP', c)
for c in nos:
    print('NOSTEP', c)
"@

$meshCases = @()
$exportCases = @()
$submitReady = @()
$doneCases = @()
$skipCases = @()
$noStep = @()
foreach ($line in @($pick)) {
    $s = "$line".Trim()
    if ($s -match '^MESH\s+(\S+)') { $meshCases += $Matches[1] }
    elseif ($s -match '^EXPORT\s+(\S+)') { $exportCases += $Matches[1] }
    elseif ($s -match '^SUBMIT_READY\s+(\S+)') { $submitReady += $Matches[1] }
    elseif ($s -match '^DONE\s+(\S+)') { $doneCases += $Matches[1] }
    elseif ($s -match '^SKIP\s+(\S+)') { $skipCases += $Matches[1] }
    elseif ($s -match '^NOSTEP\s+(\S+)') { $noStep += $Matches[1] }
}

Write-Host "=== LOCAL == SERVER CAE queue (MESH_PROTOCOL=1) ===" -ForegroundColor Cyan
Write-Host ("  CAD={0}" -f $BatchCad) -ForegroundColor DarkGray
Write-Host ("  sim_batch={0} (ASCII)  cpus={1} mem={2}MB  maxParallel={3}  exportOnly={4}" -f $SimBatchName, $Cpus, $MemoryMB, $MaxParallel, $ExportOnly.IsPresent)
Write-Host ("  MESH ({0}): {1}" -f $meshCases.Count, ($meshCases -join ", "))
Write-Host ("  EXPORT reuse mesh ({0}): {1}" -f $exportCases.Count, ($exportCases -join ", "))
Write-Host ("  SUBMIT_READY ({0}): {1}" -f $submitReady.Count, ($submitReady -join ", "))
Write-Host ("  DONE skip ({0}): {1}" -f $doneCases.Count, ($doneCases -join ", "))
Write-Host ("  PROTOCOL SKIP ({0}): {1}" -f $skipCases.Count, ($skipCases -join ", "))
Write-Host ("  NO STEP ({0}): {1}" -f $noStep.Count, ($noStep -join ", "))
Write-Log ("queue start mesh={0} export={1} submit_ready={2}" -f ($meshCases -join ","), ($exportCases -join ","), ($submitReady -join ","))

$meshOk = @()
$meshFail = @()

function Invoke-MeshLocal([string]$cid, [switch]$ReuseMesh) {
    Write-Log ("PROTOCOL {0} $cid" -f ($(if ($ReuseMesh) { "EXPORT(reuse mesh)" } else { "MESH+EXPORT" })))
    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    $args = @("-NoProfile", "-File", (Join-Path $PSScriptRoot "run_param_batch_cae_mesh_local.ps1"), "-Only", $cid, "-JobMemoryPct", "$JobMemoryPct")
    if ($ReuseMesh) { $args += "-SkipExisting" }
    & powershell @args
    $rc = $LASTEXITCODE
    $ErrorActionPreference = $prevEap
    $inp = Join-Path $Root "output\export\$SimBatchName\$cid\$Slug\$Slug.inp"
    if (($rc -eq 0) -and (Test-Path -LiteralPath $inp) -and ((Get-Item -LiteralPath $inp).Length -gt 1MB)) {
        $script:meshOk += $cid
        $script:submitReady += $cid
        Clear-SkipCase $cid
        Write-Log "EXPORT OK $cid"
        return $true
    }
    $script:meshFail += $cid
    $meshPath = Join-Path $Root "output\export\$SimBatchName\$cid\$Slug\${Slug}_cae_mesh.inp"
    if ((Test-Path -LiteralPath $meshPath) -and ((Get-Item -LiteralPath $meshPath).Length -gt 1MB)) {
        Set-SkipCase $cid "compression export failed after mesh"
        Write-Log "SKIP export fail $cid (mesh kept)"
    } else {
        Set-SkipCase $cid "mesh protocol failed (seed0.6 + fast + vtopo)"
        Write-Log "SKIP mesh fail $cid (recorded)"
    }
    return $false
}

foreach ($cid in $exportCases) { Invoke-MeshLocal $cid -ReuseMesh | Out-Null }
foreach ($cid in $meshCases) { Invoke-MeshLocal $cid | Out-Null }

function Submit-Case([string]$cid) {
    $expDir = Join-Path $Root "output\export\$SimBatchName\$cid\$Slug"
    $jobDir = Join-Path $Root "output\jobs\$SimBatchName\$cid\$Slug"
    $postDir = Join-Path $Root "output\post\$SimBatchName\$cid\$Slug"
    $inpSrc = Join-Path $expDir "$Slug.inp"
    if (-not (Test-Path -LiteralPath $inpSrc)) {
        Write-Log "SUBMIT miss INP $cid"
        return $false
    }
    New-Item -ItemType Directory -Force -Path $jobDir, $postDir | Out-Null
    # Fresh solve in ASCII cwd (drop partial Chinese-path leftovers).
    Get-ChildItem -LiteralPath $jobDir -File -ErrorAction SilentlyContinue |
        Where-Object { $_.Extension -match '\.(lck|odb|sta|dat|msg|log|com|prt|sim)$' -or $_.Name -like '*.abq' -or $_.Name -like '*.res' -or $_.Name -like '*.pac' -or $_.Name -like '*.mdl' -or $_.Name -like '*.stt' -or $_.Name -like '*.sel' } |
        Remove-Item -Force -ErrorAction SilentlyContinue
    Copy-Item -LiteralPath $inpSrc -Destination (Join-Path $jobDir "$Slug.inp") -Force
    # Copy meta next to export for post (already under ASCII export).
    Write-Log "SUBMIT $cid cwd=$jobDir cpus=$Cpus mem=${MemoryMB}MB"
    Push-Location $jobDir
    try {
        $env:PYTHONUTF8 = "1"
        $env:PYTHONIOENCODING = "utf-8"
        $prevEap = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        & abaqus "job=$Slug" "input=$Slug.inp" "oldjob=delete" "cpus=$Cpus" "memory=$MemoryMB" interactive 2>&1 |
            Tee-Object -FilePath (Join-Path $jobDir "${Slug}_submit_local.log")
        $code = $LASTEXITCODE
        $ErrorActionPreference = $prevEap
    } finally {
        Pop-Location
    }
    $sta = Join-Path $jobDir "$Slug.sta"
    $ok = $false
    if (Test-Path -LiteralPath $sta) {
        $txt = Get-Content -LiteralPath $sta -Raw -ErrorAction SilentlyContinue
        if ($txt -match "THE ANALYSIS HAS COMPLETED SUCCESSFULLY") { $ok = $true }
    }
    if ($ok) {
        Write-Log "SOLVE OK $cid — post"
        $odb = Join-Path $jobDir "$Slug.odb"
        $meta = Join-Path $expDir "${Slug}_meta.json"
        $csv = Join-Path $postDir "${Slug}_stress_strain.csv"
        $raw = Join-Path $postDir "${Slug}_stress_strain_raw.csv"
        if ((Test-Path -LiteralPath $odb) -and (Test-Path -LiteralPath $meta)) {
            $ErrorActionPreference = "Continue"
            & abaqus python (Join-Path $Root "scripts\extract_stress_strain_from_odb.py") `
                --odb $odb --meta $meta --csv $csv --raw-csv $raw --force-mode paper --curve-method paper 2>&1 |
                Tee-Object -FilePath (Join-Path $postDir "extract_local.log")
            $ErrorActionPreference = "Stop"
        }
        return $true
    }
    Write-Log "SOLVE FAIL/incomplete $cid exit=$code"
    return $false
}

$solveOk = @(); $solveFail = @()
if (-not $ExportOnly) {
    $queue = @($submitReady | Select-Object -Unique)
    foreach ($cid in $queue) {
        # MaxParallel=1 on laptop (serial solves).
        if (Submit-Case $cid) { $solveOk += $cid } else { $solveFail += $cid }
    }
} else {
    Write-Log "EXPORT_ONLY=1 — not submitting solves"
}

Write-Host ""
Write-Host "=== summary ===" -ForegroundColor Cyan
Write-Host ("MESH OK ({0}): {1}" -f $meshOk.Count, ($meshOk -join ", "))
Write-Host ("MESH FAIL/SKIP ({0}): {1}" -f $meshFail.Count, ($meshFail -join ", "))
Write-Host ("SOLVE OK ({0}): {1}" -f $solveOk.Count, ($solveOk -join ", "))
Write-Host ("SOLVE FAIL ({0}): {1}" -f $solveFail.Count, ($solveFail -join ", "))
Write-Log ("done mesh_ok={0} mesh_fail={1} solve_ok={2} solve_fail={3}" -f ($meshOk -join ","), ($meshFail -join ","), ($solveOk -join ","), ($solveFail -join ","))

if ($meshFail.Count -gt 0 -or $solveFail.Count -gt 0) { exit 2 }
exit 0
