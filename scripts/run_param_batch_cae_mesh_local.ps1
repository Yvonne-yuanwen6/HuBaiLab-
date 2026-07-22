# Local param-batch CAE pipeline — MUST match server BATCH_SIM_MESH_PROTOCOL=1.
#
# Parity lock (do not change without -AllowNonProtocol):
#   heal v3 (OCP prerepair + Gmsh OCC gates) →
#   CAE tet seed=0.6 quality=fast virtual-topology C3D4 rodsPerDiameter=3 →
#   compression INP: 80% / 5 mm/min / Neo-Hooke paper / STORE OFFSETS + ContactSettle
#   run_slug = cae_tet0p6mm80_5mmin_paperbox
#
# Laptop: mesh SERIAL; Job memory default 45% (CAE write only — does not change mesh).
#
#   powershell -File scripts/run_param_batch_cae_mesh_local.ps1
#   powershell -File scripts/run_param_batch_cae_mesh_local.ps1 -Only af2q1_deq2_k2
param(
    [string[]]$Only = @(),
    [double]$JobMemoryPct = 45,
    [switch]$SkipExisting,
    [switch]$SkipHeal,
    [switch]$SkipExport,
    [switch]$AllowNonProtocol,
    # Non-protocol overrides (ignored unless -AllowNonProtocol):
    [double]$SeedMm = 0.6,
    [ValidateSet("fast", "lattice", "lattice_contact", "lattice_curve", "paper", "coarse")]
    [string]$MeshQuality = "fast"
)

$ErrorActionPreference = "Stop"
# NativeCommandError from python stderr must not abort the pipeline
$PSNativeCommandUseErrorActionPreference = $false
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $Root

$Slug = "cae_tet0p6mm80_5mmin_paperbox"
$ProtocolSeed = 0.6
$ProtocolQuality = "fast"

if (-not $AllowNonProtocol) {
    if ([math]::Abs($SeedMm - $ProtocolSeed) -gt 1e-9 -or $MeshQuality -ne $ProtocolQuality) {
        throw "Refusing non-protocol mesh (seed=$SeedMm quality=$MeshQuality). Server parity requires seed=0.6 quality=fast. Pass -AllowNonProtocol only for diagnostics."
    }
    $SeedMm = $ProtocolSeed
    $MeshQuality = $ProtocolQuality
}

$BatchCad = & python -c "from pathlib import Path; root=Path(r'$Root')/'output'/'cad';
cands=[p for p in root.iterdir() if p.is_dir() and (p/'_batch_index.json').is_file()];
print(cands[0] if cands else '')"
$BatchCad = "$BatchCad".Trim()
if (-not $BatchCad -or -not (Test-Path -LiteralPath $BatchCad)) {
    throw "Cannot find cad batch folder with _batch_index.json under output/cad"
}
$IndexPath = Join-Path $BatchCad "_batch_index.json"
# Windows Abaqus Explicit cannot use Chinese cwd (charmap UnicodeEncodeError).
# CAD index may stay under the Chinese folder; all export/jobs/post use ASCII.
$SimBatchName = "param_batch"
Write-Host ("  CAD index: {0}" -f $BatchCad) -ForegroundColor DarkGray
Write-Host ("  Sim tree:  output/{{export,jobs,post}}/{0}/  (ASCII)" -f $SimBatchName) -ForegroundColor DarkGray

$DefaultOrder = @(
    # Prefer cases that still need protocol mesh (orchestrator may override via -Only).
    "af2q1_deq2_k1",
    "af2q1_deq2_k1p5",
    "af2q1_deq2_k2",
    "af2q1p5_deq2_k1p5",
    "af1q1_deq2_k1",
    "af2q0p5_deq2_k1p5"
)

$idx = Get-Content -Raw -Encoding UTF8 $IndexPath | ConvertFrom-Json
$cases = if ($Only.Count -gt 0) { $Only } else { $DefaultOrder }

$os = Get-CimInstance Win32_OperatingSystem
$totalGb = [math]::Round($os.TotalVisibleMemorySize / 1MB, 1)
$freeGb = [math]::Round($os.FreePhysicalMemory / 1MB, 1)
$cpu = Get-CimInstance Win32_Processor | Select-Object -First 1
Write-Host "=== LOCAL == SERVER protocol (BATCH_SIM_MESH_PROTOCOL=1) ===" -ForegroundColor Cyan
Write-Host ("  CPU: {0}c/{1}t | RAM {2}GB free={3}GB | JobMemWrite={4}% (mesh serial)" -f $cpu.NumberOfCores, $cpu.NumberOfLogicalProcessors, $totalGb, $freeGb, $JobMemoryPct)
Write-Host "  Heal: structure-preserving v3 | CAE: seed=0.6 fast vtopo C3D4 | Export: 80%/5mm/min/paper/contact"
Write-Host "  slug: $Slug"
if ($AllowNonProtocol) { Write-Host "  WARN: AllowNonProtocol — results NOT comparable to server mainline" -ForegroundColor Yellow }

$logDir = Join-Path $Root "output\logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$runLog = Join-Path $logDir "param_batch_cae_mesh_local.log"
Add-Content -Encoding UTF8 $runLog ("`n==== {0} protocol-local start ====" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"))

$env:HU_BAI_JOB_MEMORY_PCT = "$JobMemoryPct"
$env:HU_BAI_VIRTUAL_TOPOLOGY = "1"
$env:HU_BAI_ELEM_TYPE = "C3D4"
$env:HU_BAI_MESH_MODE = "tet"
$env:HU_BAI_MESH_QUALITY = $MeshQuality
$env:HU_BAI_SEED = "$SeedMm"
$env:HU_BAI_PART_NAME = "LATTICE"
$env:HU_BAI_RODS_PER_DIAMETER = "3.0"
$env:HU_BAI_ROOT = $Root
$env:BATCH_HEAL_OCP_PREREPAIR = "1"
$env:BATCH_HEAL_TIMEOUT_S = "2400"
$env:BATCH_HEAL_PRESET_TIMEOUT_S = "900"
Remove-Item Env:HU_BAI_MERGE_SOLIDS -ErrorAction SilentlyContinue

function Get-CaseParams([string]$cid) {
    $c = $idx.cases.$cid
    if (-not $c) { throw "case not in index: $cid" }
    return @{
        Af  = [double]$c.Af
        Q   = [double]$c.Q
        deq = [double]$c.deq_mm
        k   = [double]$c.k
    }
}

function Write-ProtocolManifest([string]$path, [hashtable]$obj) {
    $json = $obj | ConvertTo-Json -Depth 6
    Set-Content -LiteralPath $path -Value $json -Encoding UTF8
}

$ok = @(); $fail = @(); $skip = @()

foreach ($cid in $cases) {
    $stepUse = & python -c "from pathlib import Path
root=Path(r'$Root'); cid='$cid'; batch=Path(r'$BatchCad')
ver=root/'output'/'cad'/'verified'/f'batch_{cid}_paper_box_array.step'
local=batch/cid/f'{cid}_444.step'
# Prefer verified copy of pulled 444; sync verified from local 444 if missing/outdated size
if local.is_file() and (not ver.is_file() or ver.stat().st_size != local.stat().st_size):
    ver.parent.mkdir(parents=True, exist_ok=True)
    import shutil
    shutil.copy2(local, ver)
    print('SYNC_VERIFIED', file=__import__('sys').stderr)
p=ver if ver.is_file() else (local if local.is_file() else None)
print(p if p else '')"
    $stepUse = "$stepUse".Trim()
    if (-not $stepUse) {
        Write-Host "SKIP $cid — no *_444.step locally" -ForegroundColor Yellow
        $skip += $cid
        Add-Content $runLog "SKIP $cid no_444"
        continue
    }

    $outDir = Join-Path $Root "output\export\$SimBatchName\$cid\$Slug"
    $outDir = "$outDir".Trim()
    New-Item -ItemType Directory -Force -Path $outDir | Out-Null
    $meshOut = Join-Path $outDir "${Slug}_cae_mesh.inp"
    $compOut = Join-Path $outDir "${Slug}.inp"
    $manifestPath = Join-Path $outDir "protocol_local_manifest.json"

    $params = Get-CaseParams $cid
    $deq = $params.deq
    $Af = $params.Af
    $Q = $params.Q

    if ($SkipExisting -and (Test-Path -LiteralPath $meshOut) -and ((Get-Item -LiteralPath $meshOut).Length -gt 1MB)) {
        Write-Host "REUSE mesh $cid" -ForegroundColor DarkGray
        if (-not $SkipExport -and -not ((Test-Path -LiteralPath $compOut) -and ((Get-Item -LiteralPath $compOut).Length -gt 1MB))) {
            Write-Host "  EXPORT compression INP (reuse mesh) ..."
        } else {
            $ok += $cid
            Add-Content $runLog "REUSE $cid"
            continue
        }
    } else {
        $freeNow = [math]::Round((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory / 1MB, 1)
        Write-Host ""
        Write-Host ("--- {0} Af={1} Q={2} deq={3} freeRAM={4}GB ---" -f $cid, $Af, $Q, $deq, $freeNow) -ForegroundColor Cyan
        Write-Host ("  STEP: {0}" -f $stepUse)
        Add-Content $runLog ("MESH start {0} deq={1} step={2}" -f $cid, $deq, $stepUse)

        $meshStep = $stepUse
        $healDir = Join-Path $Root "output\cad\verified\heal_$cid"
        $hpExisting = Join-Path $healDir "healed_path.txt"
        if ((-not $SkipHeal) -and (Test-Path -LiteralPath $hpExisting)) {
            $cand = (Get-Content -LiteralPath $hpExisting -Raw).Trim()
            if ($cand -and (Test-Path -LiteralPath $cand)) {
                Write-Host ("  [1/3] HEAL reuse -> {0}" -f $cand) -ForegroundColor Green
                $meshStep = $cand
                Add-Content $runLog ("HEAL reuse $cid -> $meshStep")
                $SkipHealForCase = $true
            } else { $SkipHealForCase = $false }
        } else { $SkipHealForCase = $SkipHeal }

        if (-not $SkipHealForCase) {
            New-Item -ItemType Directory -Force -Path $healDir | Out-Null
            Write-Host "  [1/3] HEAL (server-identical v3) ..." -ForegroundColor Cyan
            $prevEap = $ErrorActionPreference
            $ErrorActionPreference = "Continue"
            $healOut = & python -c @"
import json, os, sys
from pathlib import Path
sys.path.insert(0, r'$Root')
os.chdir(r'$Root')
from src.export.step_heal_for_cae import heal_step_for_cae
src, out_dir = r'$stepUse', r'$healDir'
path, report = heal_step_for_cae(src, out_dir, basename='healed')
Path(out_dir, 'healed_path.txt').write_text(path + chr(10), encoding='utf-8')
Path(out_dir, 'heal_report.json').write_text(json.dumps(report, indent=2, ensure_ascii=False)+chr(10), encoding='utf-8')
# stdout only (stderr NativeCommandError aborts PS Stop mode)
print(path)
print('HEAL_META used_heal=%s' % report.get('used_heal'))
"@ 2>&1
            $ErrorActionPreference = $prevEap
            foreach ($line in @($healOut)) {
                $s = "$line"
                if ($s -match 'HEAL_META|Error|Traceback|NativeCommandError|CategoryInfo') {
                    Write-Host "    $s" -ForegroundColor DarkYellow
                }
            }
            if (Test-Path -LiteralPath $hpExisting) {
                $meshStep = (Get-Content -LiteralPath $hpExisting -Raw).Trim()
            }
            if (-not $meshStep -or -not (Test-Path -LiteralPath $meshStep)) {
                Write-Host "    HEAL fallback -> raw verified" -ForegroundColor Yellow
                $meshStep = $stepUse
            } else {
                Write-Host ("    HEAL OK -> {0}" -f $meshStep) -ForegroundColor Green
            }
            Add-Content $runLog ("HEAL $cid -> $meshStep")
        } elseif ($SkipHeal) {
            # Explicit -SkipHeal: always use raw verified/local STEP (do not prefer prior heal).
            Write-Host ("  [1/3] HEAL skipped; mesh STEP={0}" -f $meshStep) -ForegroundColor DarkGray
        }

        Write-Host ("  [2/3] CAE PROTOCOL seed={0} {1} vtopo C3D4" -f $SeedMm, $MeshQuality) -ForegroundColor Cyan
        $env:HU_BAI_STEP = $meshStep
        $env:HU_BAI_OUT = $meshOut
        $env:HU_BAI_ROD_DIAMETER = "$deq"
        $caseLog = Join-Path $outDir "cae_mesh_local.log"
        $t0 = Get-Date
        # License / CAE chatter on stderr must not abort under $ErrorActionPreference=Stop
        $prevEap = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        & abaqus cae "noGUI=scripts\abaqus_cae_hex_mesh_pilot.py" 2>&1 | Tee-Object -FilePath $caseLog
        $code = $LASTEXITCODE
        $ErrorActionPreference = $prevEap
        $dt = [int]((Get-Date) - $t0).TotalSeconds

        $good = $false
        if ((Test-Path -LiteralPath $meshOut) -and ((Get-Item -LiteralPath $meshOut).Length -gt 1MB)) {
            $head = Get-Content -LiteralPath $meshOut -TotalCount 80 -ErrorAction SilentlyContinue | Out-String
            if ($head -match '(?m)^\*Node\b') { $good = $true }
        }
        if (-not ($code -eq 0 -and $good)) {
            Write-Host ("FAIL mesh {0} wall={1}s exit={2}" -f $cid, $dt, $code) -ForegroundColor Red
            Add-Content $runLog ("FAIL mesh {0} wall={1}s exit={2}" -f $cid, $dt, $code)
            $fail += $cid
            continue
        }
        $sz = [math]::Round((Get-Item -LiteralPath $meshOut).Length / 1MB, 1)
        Write-Host ("    MESH OK wall={0}s size={1}MB" -f $dt, $sz) -ForegroundColor Green
        Add-Content $runLog ("OK mesh {0} wall={1}s mb={2}" -f $cid, $dt, $sz)
    }

    if (-not $SkipExport) {
        Write-Host "  [3/3] EXPORT compression INP (server export_from_mesh args) ..." -ForegroundColor Cyan
        # Match server case_roots: EXPORT_ROOT=.../export/{batch}/{cid}  (slug subdir added by exporter)
        $env:HU_BAI_EXPORT_ROOT = (Join-Path $Root "output\export\$SimBatchName\$cid")
        $env:HU_BAI_JOBS_ROOT = (Join-Path $Root "output\jobs\$SimBatchName\$cid")
        $env:HU_BAI_POST_ROOT = (Join-Path $Root "output\post\$SimBatchName\$cid")
        New-Item -ItemType Directory -Force -Path $env:HU_BAI_EXPORT_ROOT, $env:HU_BAI_JOBS_ROOT, $env:HU_BAI_POST_ROOT | Out-Null

        $exportLog = Join-Path $outDir "cae_export_local.log"
        $exArgs = @(
            "scripts/run_hu_bai_bcc_solid_cad_cae_tet_export.py",
            "--cells", "4", "--Q", "$Q", "--Af", "$Af", "--rod-diameter", "$deq",
            "--profile", "fast",
            "--cad", "$stepUse",
            "--cae-seed", "0.6",
            "--cae-element-type", "C3D4",
            "--cae-mesh-quality", "lattice_contact",
            "--strain", "0.80", "--load-rate-mm-min", "5",
            "--explicit-dt", "0.0005", "--explicit-dt-mode", "automatic",
            "--material-model", "paper",
            "--contact-store-offsets",
            "--contact-settle", "--contact-settle-fraction", "0.15", "--contact-settle-soft-s0", "0.02",
            "--slug-mode", "short",
            "--short-slug", "$Slug",
            "--mesh-locally",
            "--cae-mesh-inp", "$meshOut"
        )
        # Note: --cae-mesh-quality lattice_contact here is metadata only when --cae-mesh-inp is set
        # (same as server export_from_mesh); actual mesh already built with protocol fast+vtopo.
        $prevEap = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        & python @exArgs 2>&1 | Tee-Object -FilePath $exportLog
        $ErrorActionPreference = $prevEap
        if (-not ((Test-Path -LiteralPath $compOut) -and ((Get-Item -LiteralPath $compOut).Length -gt 1MB))) {
            Write-Host "FAIL export $cid — no compression INP" -ForegroundColor Red
            Add-Content $runLog "FAIL export $cid"
            $fail += $cid
            continue
        }
        Write-Host ("    EXPORT OK -> {0}" -f $compOut) -ForegroundColor Green
        Add-Content $runLog "OK export $cid"
    }

    Write-ProtocolManifest $manifestPath @{
        case_id            = $cid
        run_slug           = $Slug
        parity             = "BATCH_SIM_MESH_PROTOCOL=1"
        Af                 = $Af
        Q                  = $Q
        deq_mm             = $deq
        k                  = $params.k
        step               = $stepUse
        mesh_seed_mm       = $SeedMm
        mesh_quality       = $MeshQuality
        virtual_topology   = $true
        element_type       = "C3D4"
        rods_per_diameter  = 3.0
        strain             = 0.80
        load_rate_mm_min   = 5
        material_model     = "paper"
        contact_store_offsets = $true
        contact_settle_fraction = 0.15
        contact_settle_soft_s0  = 0.02
        explicit_dt        = 0.0005
        host               = $env:COMPUTERNAME
        noted              = "Mesh/INP settings match server. Explicit numerical noise may differ if cpus differ."
        updated_at         = (Get-Date -Format "o")
    }

    $ok += $cid
}

Write-Host ""
Write-Host "=== summary ===" -ForegroundColor Cyan
Write-Host ("OK ({0}): {1}" -f $ok.Count, ($ok -join ", "))
Write-Host ("FAIL ({0}): {1}" -f $fail.Count, ($fail -join ", "))
Write-Host ("SKIP ({0}): {1}" -f $skip.Count, ($skip -join ", "))
Add-Content $runLog ("==== done OK={0} FAIL={1} SKIP={2} ====" -f ($ok -join ","), ($fail -join ","), ($skip -join ","))

if ($fail.Count -gt 0) { exit 2 }
exit 0
