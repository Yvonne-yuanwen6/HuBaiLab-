# Mesh test subarrays under output/cad/test/{332,333,442,443}.
#
# Same protocol as server BATCH_SIM_MESH_PROTOCOL=1 / run_param_batch_cae_mesh_local.ps1:
#   heal v3 (optional -SkipHeal) -> CAE tet seed=0.6 quality=fast vtopo C3D4 rodsPerDiameter=3
#
# Mesh only here. Compression INP: py -3 scripts/run_test_subarray_cae_export.py (or linux queue).
#
#   powershell -File scripts/run_test_subarray_cae_mesh_local.ps1
#   powershell -File scripts/run_test_subarray_cae_mesh_local.ps1 -OnlySize 332 -OnlyCase af2q0_deq2_k1
#   powershell -File scripts/run_test_subarray_cae_mesh_local.ps1 -SkipHeal -SkipExisting
param(
    [string[]]$OnlySize = @(),
    [string[]]$OnlyCase = @(),
    [switch]$SkipExisting,
    [switch]$SkipHeal,
    [double]$JobMemoryPct = 45
)

$ErrorActionPreference = "Stop"
$PSNativeCommandUseErrorActionPreference = $false
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $Root

if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
    throw "py launcher not found"
}
if (-not (Get-Command abaqus -ErrorAction SilentlyContinue)) {
    throw "abaqus not found on PATH"
}

$SeedMm = 0.6
$MeshQuality = "fast"
$Slug = "cae_tet0p6mm80_5mmin_paperbox"
$DeqMm = 2.0
$SizesDefault = @("332", "333", "442", "443")
$CasesDefault = @(
    "af2q0_deq2_k1",
    "af2q0p5_deq2_k1",
    "af2q1_deq2_k1",
    "af2q1p5_deq2_k1"
)

$sizes = if ($OnlySize.Count -gt 0) { $OnlySize } else { $SizesDefault }
$cases = if ($OnlyCase.Count -gt 0) { $OnlyCase } else { $CasesDefault }

$env:HU_BAI_JOB_MEMORY_PCT = "$JobMemoryPct"
$env:HU_BAI_VIRTUAL_TOPOLOGY = "1"
$env:HU_BAI_ELEM_TYPE = "C3D4"
$env:HU_BAI_MESH_MODE = "tet"
$env:HU_BAI_MESH_QUALITY = $MeshQuality
$env:HU_BAI_SEED = "$SeedMm"
$env:HU_BAI_PART_NAME = "LATTICE"
$env:HU_BAI_RODS_PER_DIAMETER = "3.0"
$env:HU_BAI_ROD_DIAMETER = "$DeqMm"
$env:HU_BAI_ROOT = $Root
$env:BATCH_HEAL_OCP_PREREPAIR = "1"
$env:BATCH_HEAL_TIMEOUT_S = "2400"
$env:BATCH_HEAL_PRESET_TIMEOUT_S = "900"
Remove-Item Env:HU_BAI_MERGE_SOLIDS -ErrorAction SilentlyContinue

$logDir = Join-Path $Root "output\logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$runLog = Join-Path $logDir "test_subarray_cae_mesh_local.log"
Add-Content -Encoding UTF8 $runLog ("`n==== {0} test-subarray mesh start ====" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"))

$os = Get-CimInstance Win32_OperatingSystem
$freeGb = [math]::Round($os.FreePhysicalMemory / 1MB, 1)
Write-Host "=== TEST SUBARRAY CAE MESH (protocol seed=0.6 fast vtopo) ===" -ForegroundColor Cyan
Write-Host ("  sizes={0} cases={1} freeRAM={2}GB SkipHeal={3} SkipExisting={4}" -f `
    ($sizes -join ","), ($cases -join ","), $freeGb, $SkipHeal.IsPresent, $SkipExisting.IsPresent)
Write-Host ("  out: output/export/test/{size}/{case}/$Slug/")

$ok = @(); $fail = @(); $skip = @()

foreach ($size in $sizes) {
    foreach ($cid in $cases) {
        $key = "${cid}_${size}"
        $stepUse = Join-Path $Root "output\cad\test\$size\${cid}_${size}.step"
        if (-not (Test-Path -LiteralPath $stepUse)) {
            Write-Host "SKIP $key - STEP missing: $stepUse" -ForegroundColor Yellow
            $skip += $key
            Add-Content $runLog "SKIP $key no_step"
            continue
        }

        $outDir = Join-Path $Root "output\export\test\$size\$cid\$Slug"
        New-Item -ItemType Directory -Force -Path $outDir | Out-Null
        $meshOut = Join-Path $outDir "${Slug}_cae_mesh.inp"
        $healDir = Join-Path $Root "output\cad\test\$size\heal_$cid"
        $hpExisting = Join-Path $healDir "healed_path.txt"

        if ($SkipExisting -and (Test-Path -LiteralPath $meshOut) -and ((Get-Item -LiteralPath $meshOut).Length -gt 1MB)) {
            $head = Get-Content -LiteralPath $meshOut -TotalCount 40 -ErrorAction SilentlyContinue | Out-String
            if ($head -match '(?m)^\*Node\b') {
                Write-Host "REUSE mesh $key" -ForegroundColor DarkGray
                $ok += $key
                Add-Content $runLog "REUSE $key"
                continue
            }
        }

        $freeNow = [math]::Round((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory / 1MB, 1)
        Write-Host ""
        Write-Host ("--- {0} deq={1} freeRAM={2}GB ---" -f $key, $DeqMm, $freeNow) -ForegroundColor Cyan
        Write-Host ("  STEP: {0}" -f $stepUse)
        Add-Content $runLog ("MESH start {0} step={1}" -f $key, $stepUse)

        $meshStep = $stepUse
        if ((-not $SkipHeal) -and (Test-Path -LiteralPath $hpExisting)) {
            $cand = (Get-Content -LiteralPath $hpExisting -Raw).Trim()
            if ($cand -and (Test-Path -LiteralPath $cand)) {
                Write-Host ("  [1/2] HEAL reuse -> {0}" -f $cand) -ForegroundColor Green
                $meshStep = $cand
                $doHeal = $false
            } else { $doHeal = $true }
        } else {
            $doHeal = -not $SkipHeal
        }

        if ($doHeal) {
            New-Item -ItemType Directory -Force -Path $healDir | Out-Null
            Write-Host "  [1/2] HEAL (v3) ..." -ForegroundColor Cyan
            $prevEap = $ErrorActionPreference
            $ErrorActionPreference = "Continue"
            $healOut = & py -3 -c @"
import json, os, sys
from pathlib import Path
sys.path.insert(0, r'$Root')
os.chdir(r'$Root')
from src.export.step_heal_for_cae import heal_step_for_cae
src, out_dir = r'$stepUse', r'$healDir'
path, report = heal_step_for_cae(src, out_dir, basename='healed')
Path(out_dir, 'healed_path.txt').write_text(path + chr(10), encoding='utf-8')
Path(out_dir, 'heal_report.json').write_text(json.dumps(report, indent=2, ensure_ascii=False)+chr(10), encoding='utf-8')
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
                Write-Host "    HEAL fallback -> raw STEP" -ForegroundColor Yellow
                $meshStep = $stepUse
            } else {
                Write-Host ("    HEAL OK -> {0}" -f $meshStep) -ForegroundColor Green
            }
            Add-Content $runLog ("HEAL $key -> $meshStep")
        } else {
            Write-Host ("  [1/2] HEAL skipped; mesh STEP={0}" -f $meshStep) -ForegroundColor DarkGray
        }

        Write-Host ("  [2/2] CAE PROTOCOL seed={0} {1} vtopo C3D4" -f $SeedMm, $MeshQuality) -ForegroundColor Cyan
        $env:HU_BAI_STEP = $meshStep
        $env:HU_BAI_OUT = $meshOut
        $caseLog = Join-Path $outDir "cae_mesh_local.log"
        $t0 = Get-Date
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
            Write-Host ("FAIL mesh {0} wall={1}s exit={2}" -f $key, $dt, $code) -ForegroundColor Red
            Add-Content $runLog ("FAIL mesh {0} wall={1}s exit={2}" -f $key, $dt, $code)
            $fail += $key
            continue
        }
        $sz = [math]::Round((Get-Item -LiteralPath $meshOut).Length / 1MB, 1)
        Write-Host ("    MESH OK wall={0}s size={1}MB -> {2}" -f $dt, $sz, $meshOut) -ForegroundColor Green
        Add-Content $runLog ("OK mesh {0} wall={1}s mb={2}" -f $key, $dt, $sz)
        $ok += $key

        $manifest = @{
            case_id           = $cid
            size_tag          = $size
            run_slug          = $Slug
            parity            = "BATCH_SIM_MESH_PROTOCOL=1"
            deq_mm            = $DeqMm
            L_mm              = 20.0
            step              = $stepUse
            mesh_step         = $meshStep
            mesh_seed_mm      = $SeedMm
            mesh_quality      = $MeshQuality
            virtual_topology  = $true
            element_type      = "C3D4"
            rods_per_diameter = 3.0
            mesh_inp          = $meshOut
            wall_s            = $dt
        } | ConvertTo-Json -Depth 4
        Set-Content -LiteralPath (Join-Path $outDir "protocol_local_manifest.json") -Value $manifest -Encoding UTF8
    }
}

Write-Host ""
Write-Host ("=== DONE ok={0} fail={1} skip={2} ===" -f $ok.Count, $fail.Count, $skip.Count) -ForegroundColor Cyan
if ($ok.Count) { Write-Host ("  OK: {0}" -f ($ok -join ", ")) -ForegroundColor Green }
if ($fail.Count) { Write-Host ("  FAIL: {0}" -f ($fail -join ", ")) -ForegroundColor Red }
if ($skip.Count) { Write-Host ("  SKIP: {0}" -f ($skip -join ", ")) -ForegroundColor Yellow }
Add-Content $runLog ("DONE ok={0} fail={1} skip={2}" -f $ok.Count, $fail.Count, $skip.Count)
if ($fail.Count -gt 0) { exit 1 }
exit 0
