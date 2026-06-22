# Wait for active voxel job, then serial downstream cases.
# Settings: voxel pitch 1.0 mm, 25 mm/min, 80% strain, 4x4x4, 8 cpu.
#
#   powershell -File scripts/run_voxel1mm80_25mmin_queue_bcc_q05_q15.ps1
#   powershell -File scripts/run_voxel1mm80_25mmin_queue_bcc_q05_q15.ps1 `
#     -WaitSlug hu_bai_sfbls_af2q1_L20_4x4x4_solid_cad_f_voxel1mm80_25mmin_noself `
#     -CaseKeys bcc,q05,q15

param(
    [string]$WaitSlug = "hu_bai_sfbls_af2q0p5_L20_4x4x4_solid_cad_f_voxel1mm80_25mmin",
    [string]$CaseSuffix = "voxel1mm80_25mmin",
    [string[]]$CaseKeys = @("bcc", "q05", "q1", "q15"),
    [int]$PollSeconds = 60,
    [int]$MemoryMB = 8192,
    [int]$Cpus = 8,
    [double]$VoxelPitch = 1.0,
    [double]$LoadRateMmMin = 25,
    [double]$ExplicitDt = 0,
    [double]$Strain = 0.8,
    [switch]$ForceRerun,
    [switch]$SkipWait,
    [switch]$SkipCompleted,
    [switch]$ContinueOnFailure,
    [switch]$NoSelfContact
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

function Get-JobOutcome {
    param([Parameter(Mandatory)][string]$Slug)
    $jobDir = Join-Path $Root "output\jobs\$Slug"
    $sta = Join-Path $jobDir "$Slug.sta"
    $odb = Join-Path $jobDir "$Slug.odb"
    $lck = Join-Path $jobDir "$Slug.lck"
    if (Test-AbaqusJobCompleted -StaPath $sta -OdbPath $odb) { return "success" }
    if ((Test-Path $lck) -or (Test-AbaqusJobProcessRunning -JobName $Slug -JobDir $jobDir)) {
        return "running"
    }
    if ((Test-Path $sta) -and -not (Test-Path $lck)) {
        $staText = Get-Content $sta -Raw -ErrorAction SilentlyContinue
        if ($staText -match 'THE ANALYSIS HAS NOT BEEN COMPLETED') { return "failed" }
        if ($staText -match 'deformation speed/wave speed') { return "failed" }
        if ($staText -notmatch 'SOLUTION PROGRESS') { return "failed" }
        if ($staText -match 'SOLUTION PROGRESS') { return "failed" }
    }
    return "pending"
}

function Wait-JobOutcome {
    param(
        [Parameter(Mandatory)][string]$Slug,
        [ValidateSet("success", "failed")][string]$Want = "success"
    )
    Write-Host "=== Waiting for $Slug -> $Want (poll ${PollSeconds}s) ===" -ForegroundColor Yellow
    while ($true) {
        $outcome = Get-JobOutcome -Slug $Slug
        if ($outcome -eq $Want) {
            Write-Host "  $Slug -> $outcome" -ForegroundColor Green
            return $outcome
        }
        if ($Want -eq "success" -and $outcome -eq "failed") {
            if ($ContinueOnFailure) {
                Write-Host "  $Slug -> failed (ContinueOnFailure)" -ForegroundColor Red
                return 'failed'
            }
            throw "$Slug failed (see output\jobs\$Slug\$Slug.sta)"
        }
        if ($outcome -eq "pending") {
            Write-Host "  $(Get-Date -Format 'HH:mm:ss')  pending (packager/submit) ..." -ForegroundColor DarkYellow
            Start-Sleep -Seconds $PollSeconds
            continue
        }
        $sta = Join-Path $Root "output\jobs\$Slug\$Slug.sta"
        if (Test-Path $sta) {
            $tail = Get-Content $sta -Tail 1 -ErrorAction SilentlyContinue
            Write-Host "  $(Get-Date -Format 'HH:mm:ss')  $tail" -ForegroundColor DarkYellow
        } else {
            Write-Host "  $(Get-Date -Format 'HH:mm:ss')  waiting for .sta ..." -ForegroundColor DarkYellow
        }
        Start-Sleep -Seconds $PollSeconds
    }
}

function Archive-FailedVoxelJob {
    param(
        [Parameter(Mandatory)][string]$Slug,
        [string]$Reason = 'queue_continue_on_failure'
    )
    $jobDir = Join-Path $Root "output\jobs\$Slug"
    $metaPath = Join-Path $Root "output\export\$Slug\${Slug}_meta.json"
    $postDir = Join-Path $Root "output\post\$Slug"
    $lck = Join-Path $jobDir "$Slug.lck"
    if (Test-Path $lck) {
        Stop-AbaqusJobProcesses -JobName $Slug -JobDir $jobDir
    }
    $arch = Archive-FailedAbaqusJob -Root $Root -JobDir $jobDir -JobName $Slug `
        -Slug $Slug -PostDir $postDir -MetaPath $metaPath -Reason $Reason
    if ($arch) {
        Write-Host "  Archived failed job -> $arch" -ForegroundColor Yellow
    }
    return $arch
}

function Invoke-VoxelCase {
    param(
        [Parameter(Mandatory)][string]$Label,
        [Parameter(Mandatory)][double]$Q,
        [Parameter(Mandatory)][string]$Variant,
        [Parameter(Mandatory)][int]$CaseCpus,
        [switch]$SkipIfSuccess
    )
    $cad = Get-VerifiedCadStep -Root $Root -Variant $Variant -Cells 4
    $slug = "hu_bai_${Variant}_L20_4x4x4_solid_cad_f_${CaseSuffix}"
    $ProjectPy = Get-ProjectPython

    $prior = Get-JobOutcome -Slug $slug
    if ($SkipIfSuccess -and $prior -eq 'success') {
        Write-Host ""
        Write-Host "========== $Label : $slug already COMPLETED -> skip ==========" -ForegroundColor Green
        return 'success'
    }
    if ($prior -eq 'running') {
        Write-Host ""
        Write-Host "========== $Label : $slug already RUNNING -> wait ==========" -ForegroundColor Cyan
        $waited = Wait-JobOutcome -Slug $slug -Want "success"
        if ($waited -eq 'success') { return 'success' }
        if ($ContinueOnFailure) {
            Archive-FailedVoxelJob -Slug $slug -Reason 'not_completed' | Out-Null
            Write-QLog "FAILED (running->stop): $slug -> archived, continue queue"
            return 'failed'
        }
        throw "$slug failed while running"
    }
    if ($prior -eq 'failed') {
        if ($ContinueOnFailure) {
            Write-Host "  Prior failed state detected; archiving before re-run: $slug" -ForegroundColor Yellow
            Archive-FailedVoxelJob -Slug $slug -Reason 'queue_rerun_after_fail' | Out-Null
        }
    }

    Write-Host ""
    Write-Host "========== $Label : $slug (cpus=$CaseCpus, voxel=${VoxelPitch}mm, ${LoadRateMmMin}mm/min, ${Strain} strain) ==========" -ForegroundColor Cyan
    Write-Host "  CAD: $cad"

    Write-Host "[1/2] Export INP (voxel C3D8R$(if ($NoSelfContact) { ', no self-contact' })) ..."
    $exportArgs = @(
        "scripts\run_hu_bai_bcc_solid_cad_export.py",
        "--cells", "4",
        "--Q", "$Q",
        "--profile", "fast",
        "--case-suffix", $CaseSuffix,
        "--mesh-method", "voxel",
        "--voxel-pitch", "$VoxelPitch",
        "--strain", "$Strain",
        "--load-rate-mm-min", "$LoadRateMmMin",
        "--cad", $cad
    )
    if ($NoSelfContact) { $exportArgs += "--no-lattice-self-contact" }
    if ($ExplicitDt -gt 0) { $exportArgs += @("--explicit-dt", "$ExplicitDt") }
    if ($ProjectPy -eq "py") {
        & py -3 @exportArgs
    } else {
        & $ProjectPy @exportArgs
    }
    if ($LASTEXITCODE -ne 0) {
        if ($ContinueOnFailure) {
            Write-QLog "FAILED (export): $slug exit=$LASTEXITCODE -> continue queue"
            return 'export_failed'
        }
        throw "Export failed: $slug"
    }

    Write-Host "[2/2] Submit Abaqus (cpus=$CaseCpus) ..."
    $submitArgs = @(
        "-File", (Join-Path $ScriptDir "submit_hu_bai_bcc_solid_cad_compression.ps1"),
        "-SkipExport",
        "-Slug", $slug,
        "-MemoryMB", $MemoryMB,
        "-Cpus", $CaseCpus
    )
    if ($ForceRerun) { $submitArgs += "-ForceRerun" }
    & powershell @submitArgs
    if ($LASTEXITCODE -ne 0) {
        if ((Get-JobOutcome -Slug $slug) -eq 'success') {
            Write-Host "  [WARN] Submit exit code $LASTEXITCODE but job COMPLETED; continuing queue." -ForegroundColor Yellow
            return 'success'
        }
        if ($ContinueOnFailure) {
            Archive-FailedVoxelJob -Slug $slug -Reason 'submit_exit_error' | Out-Null
            Write-QLog "FAILED (submit): $slug exit=$LASTEXITCODE -> archived, continue queue"
            return 'submit_failed'
        }
        throw "Submit failed: $slug"
    }

    $waited = Wait-JobOutcome -Slug $slug -Want "success"
    if ($waited -eq 'success') { return 'success' }
    if ($ContinueOnFailure) {
        Archive-FailedVoxelJob -Slug $slug -Reason 'not_completed' | Out-Null
        Write-QLog "FAILED (solve): $slug -> archived, continue queue"
        return 'failed'
    }
    throw "$slug failed (see output\jobs\$slug\$slug.sta)"
}

$queueLog = Join-Path $Root "output\reports\voxel1mm80_25mmin_${CaseSuffix}_queue.log"
$logDir = Split-Path $queueLog -Parent
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir -Force | Out-Null }
function Write-QLog([string]$Msg) {
    $line = "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] $Msg"
    Add-Content -Path $queueLog -Value $line -Encoding UTF8
    Write-Host $line
}

Write-QLog "queue start: wait=$WaitSlug suffix=$CaseSuffix cases=$($CaseKeys -join ',') noself=$NoSelfContact pitch=${VoxelPitch}mm rate=${LoadRateMmMin}mm/min dt=$ExplicitDt strain=$Strain continueOnFail=$ContinueOnFailure"

if (-not $SkipWait -and $WaitSlug) {
    $waitOutcome = Get-JobOutcome -Slug $WaitSlug
    if ($waitOutcome -eq 'running') {
        Write-QLog "waiting for active job: $WaitSlug"
        try {
            Wait-JobOutcome -Slug $WaitSlug -Want "success" | Out-Null
        } catch {
            Write-QLog "wait slug FAILED: $WaitSlug -> continue downstream queue ($($_.Exception.Message))"
        }
    } elseif ($waitOutcome -eq 'success') {
        Write-QLog "wait slug already success: $WaitSlug"
    } elseif ($waitOutcome -eq 'failed') {
        Write-QLog "wait slug already FAILED: $WaitSlug -> continue downstream queue"
    } else {
        Write-QLog "wait slug outcome=$waitOutcome (not running); continuing queue"
    }
}

$skipDone = [bool]$SkipCompleted
$allCases = @(
    @{ Key = "bcc"; Label = "BCC Q=0"; Q = 0; Variant = "bcc_af2q0"; SkipIfSuccess = $skipDone },
    @{ Key = "q05"; Label = "SFBLS Q=0.5"; Q = 0.5; Variant = "sfbls_af2q0p5"; SkipIfSuccess = $skipDone },
    @{ Key = "q1"; Label = "SFBLS Q=1.0"; Q = 1.0; Variant = "sfbls_af2q1"; SkipIfSuccess = $skipDone },
    @{ Key = "q15"; Label = "SFBLS Q=1.5"; Q = 1.5; Variant = "sfbls_af2q1p5"; SkipIfSuccess = $skipDone }
)
$keys = @(
    foreach ($raw in $CaseKeys) {
        foreach ($part in ($raw -split ',')) {
            $k = $part.Trim().ToLower()
            if ($k) { $k }
        }
    }
)
$cases = @($allCases | Where-Object { $keys -contains $_.Key })
if ($cases.Count -eq 0) {
    throw "No cases matched -CaseKeys '$($CaseKeys -join ',')' (use bcc q05 q1 q15)"
}

$results = @{}
foreach ($case in $cases) {
    $status = Invoke-VoxelCase -Label ([string]$case.Label) -Q ([double]$case.Q) -Variant ([string]$case.Variant) `
        -CaseCpus $Cpus -SkipIfSuccess:([bool]$case.SkipIfSuccess)
    $results[[string]$case.Key] = $status
    Write-QLog "case $($case.Key): $status"
}

$ok = @($results.Values | Where-Object { $_ -eq 'success' }).Count
$bad = $results.Count - $ok
Write-QLog "queue finished: ok=$ok failed/skipped=$bad details=$($results | ConvertTo-Json -Compress)"
Write-Host ""
Write-Host "Queue finished: $ok success, $bad other (see $queueLog)." -ForegroundColor $(if ($bad -eq 0) { 'Green' } else { 'Yellow' })
