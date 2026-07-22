# Live monitor for local param-batch CAE mesh.
# ASCII-only UI (avoid GBK console mojibake). No real mesh % from Abaqus free-tet.
param(
    [int]$IntervalSec = 5,
    [string]$CaseId = "af2q1_deq2_k2"
)

$ErrorActionPreference = "Continue"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

function Get-ExportDir([string]$cid) {
    $p = & python -c "from pathlib import Path
root=Path(r'$Root')
batch=[p for p in (root/'output'/'cad').iterdir() if p.is_dir() and (p/'_batch_index.json').is_file()][0]
print(root/'output'/'export'/batch.name/'$cid'/'cae_tet0p6mm80_5mmin_paperbox')"
    return "$p".Trim()
}

function Get-Bar([double]$frac, [int]$width = 28) {
    if ($frac -lt 0) { $frac = 0 }
    if ($frac -gt 1) { $frac = 1 }
    $n = [int][math]::Round($frac * $width)
    $bar = "[" + ("#" * $n) + ("-" * ($width - $n)) + "]"
    $pct = [int](100 * $frac)
    return ("{0} {1,3}%" -f $bar, $pct)
}

function Get-Phase([string]$pilotText, [string]$errText, [bool]$healing, [bool]$wrapperAlive, [bool]$hasCae) {
    if ($errText -match 'CAE tet mesh failed|cae exited with an error') { return "FAILED" }
    if ($pilotText -match 'CAE PROTOCOL SUCCESS|Selected technique|node_count|OK: CAE') { return "DONE" }
    if ($hasCae -or $pilotText -match 'generateMesh|setMeshControls|Mesh failed|seedPart|virtual topology|Import STEP') {
        if ($pilotText -match 'Mesh failed TET_FREE_AF') { return "try TET_FREE_AF failed" }
        if ($pilotText -match 'Mesh failed TET_FREE') { return "try TET_FREE failed -> next" }
        if ($pilotText -match 'generateMesh|setMeshControls') { return "generateMesh (no % from Abaqus)" }
        if ($pilotText -match 'seedPart') { return "seedPart" }
        if ($pilotText -match 'virtual topology AFTER|createVirtualTopology') { return "virtual topology" }
        if ($pilotText -match 'openStep OK|Import STEP') { return "import STEP" }
        if ($pilotText -match 'Mesh config') { return "CAE start" }
        return "CAE running"
    }
    if ($healing) { return "HEAL (Gmsh/OCP) before CAE" }
    if ($wrapperAlive) { return "wrapper alive (heal or starting)" }
    if ($pilotText -match 'Mesh config') { return "start" }
    return "idle / not running"
}

function Get-StageFrac([string]$phase) {
    # if/elseif so only ONE double is returned (switch -Regex can return an array)
    if ($phase -match '^FAILED|^DONE') { return 1.0 }
    if ($phase -match 'generateMesh|TET_FREE') { return 0.75 }
    if ($phase -match '^CAE') { return 0.70 }
    if ($phase -match 'seedPart') { return 0.55 }
    if ($phase -match 'virtual') { return 0.40 }
    if ($phase -match 'import') { return 0.25 }
    if ($phase -match '^HEAL') { return 0.20 }
    if ($phase -match 'wrapper') { return 0.12 }
    return 0.05
}

$outDir = Get-ExportDir $CaseId
$tStart = Get-Date
$lastCpu = 0.0
$stall = 0

Write-Host "Abaqus free-tet has no percent progress bar." -ForegroundColor DarkYellow
Write-Host "Monitor shows phase + elapsed + CPU heartbeat. Ctrl+C stops monitor only." -ForegroundColor DarkYellow
Write-Host "Dir: $outDir"
Write-Host ""

while ($true) {
    $now = Get-Date
    $elapsed = ($now - $tStart).TotalSeconds
    $free = [math]::Round((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory / 1MB, 1)

    $cae = @(Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.ProcessName -match 'ABQcae' })
    $healProcs = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -and ($_.CommandLine -match 'heal_step_for_cae|step_heal_for_cae') })
    $wrapper = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -and ($_.CommandLine -match 'run_param_batch_cae_mesh_local') })

    $cpuSum = 0.0
    $memMb = 0
    $caeAgeMin = 0.0
    foreach ($p in $cae) {
        $cpuSum += [double]$p.CPU
        $memMb += [math]::Round($p.WorkingSet64 / 1MB)
        $age = ($now - $p.StartTime).TotalMinutes
        if ($age -gt $caeAgeMin) { $caeAgeMin = $age }
    }
    $healCpu = 0.0
    $healMb = 0
    foreach ($hp in $healProcs) {
        try {
            $pp = Get-Process -Id $hp.ProcessId -ErrorAction SilentlyContinue
            if ($pp) { $healCpu += [double]$pp.CPU; $healMb += [math]::Round($pp.WorkingSet64 / 1MB) }
        } catch {}
    }
    if ($healProcs.Count -eq 0 -and $wrapper.Count -gt 0 -and $cae.Count -eq 0) {
        $py = @(Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.ProcessName -eq 'python' -and $_.WorkingSet64 -gt 200MB })
        foreach ($pp in $py) { $healCpu += [double]$pp.CPU; $healMb += [math]::Round($pp.WorkingSet64 / 1MB) }
        if ($py.Count -gt 0) { $healProcs = $py }
    }

    $pilotPath = Join-Path $outDir "cae_hex_pilot.log"
    $errPath = Join-Path $outDir "cae_mesh_local.log.err"
    $localPath = Join-Path $outDir "cae_mesh_local.log"
    $meshPath = Join-Path $outDir "cae_tet0p6mm80_5mmin_paperbox_cae_mesh.inp"

    $pilot = if (Test-Path -LiteralPath $pilotPath) { Get-Content -LiteralPath $pilotPath -Raw -ErrorAction SilentlyContinue } else { "" }
    $err = if (Test-Path -LiteralPath $errPath) { Get-Content -LiteralPath $errPath -Raw -ErrorAction SilentlyContinue } else { "" }
    $healing = ($healProcs.Count -gt 0)
    $wrapperAlive = ($wrapper.Count -gt 0)
    $phase = Get-Phase $pilot $err $healing $wrapperAlive ($cae.Count -gt 0)

    $meshSz = "missing"
    if (Test-Path -LiteralPath $meshPath) {
        $meshSz = "{0:N2} MB" -f ((Get-Item -LiteralPath $meshPath).Length / 1MB)
    }

    $beatCpu = if ($cae.Count -gt 0) { $cpuSum } else { $healCpu }
    $dCpu = $beatCpu - $lastCpu
    if ($dCpu -gt 0.2) { $stall = 0 } else { $stall++ }
    $lastCpu = $beatCpu
    $activity = 0.0
    if (($cae.Count -gt 0) -or ($healProcs.Count -gt 0)) {
        if ($stall -ge 6) { $activity = 0.15 }
        else { $activity = [math]::Min(0.95, 0.2 + 0.08 * ($stall % 8) + [math]::Min(0.6, $dCpu / 20.0)) }
    }

    $stageFrac = [double](Get-StageFrac $phase)
    $fails = ([regex]::Matches(($pilot + "`n" + $err), 'Mesh failed \w+|generateMesh produced 0')).Count

    Clear-Host
    Write-Host ("===== CAE mesh monitor  {0}  case={1} =====" -f ($now.ToString("HH:mm:ss")), $CaseId) -ForegroundColor Cyan
    Write-Host ""
    Write-Host ("phase:     {0}" -f $phase) -ForegroundColor White
    Write-Host ("stage:     {0}   (coarse pipeline only)" -f (Get-Bar $stageFrac))
    Write-Host ("activity:  {0}   (CPU heartbeat; NOT mesh %)" -f (Get-Bar ([double]$activity)))
    Write-Host ("elapsed:   monitor {0:N0}s | CAE age {1:N1} min" -f $elapsed, $caeAgeMin)
    Write-Host ("HEAL:      procs={0}  mem={1} MB  cpu={2:N0}s" -f $healProcs.Count, $healMb, $healCpu)
    Write-Host ("CAE:       procs={0}  mem={1} MB  cpu_total={2:N0}s  dCPU={3:N1}s/{4}s" -f $cae.Count, $memMb, $cpuSum, $dCpu, $IntervalSec)
    Write-Host ("wrapper:   {0}" -f ($(if ($wrapperAlive) { "run_param_batch_cae_mesh_local alive" } else { "none" })))
    Write-Host ("RAM free:  {0} GB" -f $free)
    Write-Host ("mesh INP:  {0}" -f $meshSz)
    Write-Host ("fail hits: {0}" -f $fails)
    Write-Host ""
    Write-Host "pilot last lines:" -ForegroundColor DarkGray
    if (Test-Path -LiteralPath $pilotPath) {
        Get-Content -LiteralPath $pilotPath -Tail 6 | ForEach-Object { Write-Host ("  " + $_) -ForegroundColor DarkGray }
    } else {
        Write-Host "  (no cae_hex_pilot.log yet - normal during HEAL)" -ForegroundColor DarkGray
    }

    if ($phase -eq "FAILED") {
        Write-Host ""
        Write-Host "RESULT: mesh FAILED (see cae_mesh_local.log.err)." -ForegroundColor Red
        if (Test-Path -LiteralPath $errPath) { Get-Content -LiteralPath $errPath -Tail 12 }
        break
    }
    if ($phase -eq "DONE" -or ((Test-Path -LiteralPath $meshPath) -and ((Get-Item -LiteralPath $meshPath).Length -gt 1MB))) {
        Write-Host ""
        Write-Host "RESULT: mesh INP ready." -ForegroundColor Green
        break
    }
    if (-not $wrapperAlive -and $cae.Count -eq 0 -and $healProcs.Count -eq 0 -and $elapsed -gt 20) {
        Write-Host ""
        Write-Host "No wrapper / HEAL / CAE - job ended without SUCCESS marker." -ForegroundColor Yellow
        if (Test-Path -LiteralPath $localPath) { Get-Content -LiteralPath $localPath -Tail 15 }
        if (Test-Path -LiteralPath $errPath) { Get-Content -LiteralPath $errPath -Tail 15 }
        break
    }

    Start-Sleep -Seconds $IntervalSec
}
