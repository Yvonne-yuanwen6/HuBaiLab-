# Shared helpers for submit_lattice_compression*.ps1
# Dot-source: . (Join-Path $PSScriptRoot "submit_helpers.ps1")

function Read-ActiveCaseManifest {
    param(
        [Parameter(Mandatory)][string]$Root,
        [string]$ManifestPath = ''
    )
    if ([string]::IsNullOrWhiteSpace($ManifestPath)) {
        $ManifestPath = Join-Path $Root "output\active_case.json"
    }
    if (-not (Test-Path $ManifestPath)) {
        throw "Missing case manifest: $ManifestPath (run export script first)"
    }
    return (Get-Content $ManifestPath -Raw -Encoding UTF8 | ConvertFrom-Json)
}

function Test-AbaqusJobCompleted {
    param(
        [Parameter(Mandatory)][string]$StaPath,
        [Parameter(Mandatory)][string]$OdbPath
    )
    if (-not ((Test-Path $StaPath) -and (Test-Path $OdbPath))) { return $false }
    $staText = Get-Content $StaPath -Raw -ErrorAction SilentlyContinue
    return ($staText -match 'THE ANALYSIS HAS COMPLETED SUCCESSFULLY')
}

function Test-AbaqusJobIncomplete {
    param(
        [Parameter(Mandatory)][string]$StaPath,
        [Parameter(Mandatory)][string]$OdbPath
    )
    if (-not ((Test-Path $StaPath) -and (Test-Path $OdbPath))) { return $false }
    if (Test-AbaqusJobCompleted -StaPath $StaPath -OdbPath $OdbPath) { return $false }
    $staText = Get-Content $StaPath -Raw -ErrorAction SilentlyContinue
    if ($staText -match 'THE ANALYSIS HAS NOT BEEN COMPLETED') { return $true }
    return ($staText -match 'SOLUTION PROGRESS')
}

function Test-AbaqusRestartAvailable {
    param(
        [Parameter(Mandatory)][string]$JobDir,
        [Parameter(Mandatory)][string]$JobName,
        [string]$ManifestPath = '',
        [string]$ExportInpPath = ''
    )
    $stt = Join-Path $JobDir ($JobName + '.stt')
    $pac = Join-Path $JobDir ($JobName + '.pac')
    $odb = Join-Path $JobDir ($JobName + '.odb')
    if (-not ((Test-Path $stt) -and (Test-Path $pac) -and (Test-Path $odb))) { return $false }

    $inpCandidates = @(
        (Join-Path $JobDir ($JobName + '.inp'))
    )
    if ($ExportInpPath) { $inpCandidates += $ExportInpPath }
    if ($ManifestPath -and (Test-Path $ManifestPath)) {
        try {
            $manifest = Get-Content $ManifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
            if ($manifest.compression_inp) { $inpCandidates += [string]$manifest.compression_inp }
        } catch { }
    }
    foreach ($inpPath in ($inpCandidates | Select-Object -Unique)) {
        if (-not (Test-Path $inpPath)) { continue }
        if (Test-ExplicitRestartInpSafe -InpPath $inpPath) {
            return $true
        }
    }
    return $false
}

function Test-ExplicitRestartInpSafe {
    param(
        [Parameter(Mandatory)][string]$InpPath
    )
    if (-not (Test-Path $InpPath)) { return $true }
    $inpText = Get-Content $InpPath -Raw -ErrorAction SilentlyContinue
    if (-not ($inpText -match '(?m)^\*Restart,\s*write')) { return $true }
    if ($inpText -notmatch '(?m)^\*Restart,\s*write[^\r\n]*\boverlay\b') {
        Write-Host "[ERROR] Unsafe *Restart in INP (missing OVERLAY): $InpPath" -ForegroundColor Red
        return $false
    }
    if ($inpText -match '(?m)^\*Restart,\s*write[^\r\n]*number interval=(\d+)') {
        $n = [int]$Matches[1]
        if ($n -lt 1 -or $n -gt 50) {
            Write-Host "[ERROR] Unsafe *Restart NUMBER INTERVAL=$n in INP (must be 1..50 time slices, not increment count): $InpPath" -ForegroundColor Red
            return $false
        }
        return $true
    }
    Write-Host "[ERROR] Unsafe *Restart in INP (missing NUMBER INTERVAL): $InpPath" -ForegroundColor Red
    return $false
}

function Assert-ExplicitRestartInpSafe {
    param(
        [Parameter(Mandatory)][string]$Root,
        [Parameter(Mandatory)][string]$InpPath
    )
    if (-not (Test-ExplicitRestartInpSafe -InpPath $InpPath)) {
        Write-Host "  Re-export INP after updating HuBaiLab (overlay + number interval=8)." -ForegroundColor Yellow
        exit 1
    }
}

function Confirm-SkipCompletedSolve {
    param(
        [Parameter(Mandatory)][string]$JobName,
        [Parameter(Mandatory)][string]$JobDir,
        [Parameter(Mandatory)][string]$OdbPath,
        [Parameter(Mandatory)][string]$StaPath,
        [string]$InpJobPath = '',
        [switch]$ForceRerun,
        [switch]$ForceSkip
    )

    if ($ForceRerun) { return $false }
    if ($ForceSkip) { return $true }
    if (-not (Test-AbaqusJobCompleted -StaPath $StaPath -OdbPath $OdbPath)) {
        return $false
    }

    Write-Host ''
    Write-Host "[2/3] $JobName already completed (COMPLETED SUCCESSFULLY)." -ForegroundColor Cyan
    if ($InpJobPath -and (Test-Path $InpJobPath) -and (Test-Path $OdbPath)) {
        $odbTime = (Get-Item $OdbPath).LastWriteTime
        $inpTime = (Get-Item $InpJobPath).LastWriteTime
        $fmt = 'yyyy-MM-dd HH:mm:ss'
        Write-Host ('  ODB time: ' + $odbTime.ToString($fmt))
        Write-Host ('  INP time: ' + $inpTime.ToString($fmt) + ' (copy in jobs/)')
        if ($inpTime -gt $odbTime) {
            Write-Host '  >> INP is newer than ODB; re-solve is usually needed.' -ForegroundColor Yellow
        }
    }
    Write-Host '  [Y] Skip solve - post-process existing ODB only'
    Write-Host '  [N] Re-run solve - delete old results and submit'
    Write-Host ''

    do {
        $ans = Read-Host 'Skip solve? (Y/N, default N)'
        if ([string]::IsNullOrWhiteSpace($ans)) { $ans = 'N' }
        $ans = $ans.Trim()
        if ($ans -match '^(y|yes|Y)$') { return $true }
        if ($ans -match '^(n|no|N)$') { return $false }
        Write-Host '  Enter Y or N.' -ForegroundColor Yellow
    } while ($true)
}

function Test-AbaqusProcessRunning {
    foreach ($proc in Get-Process -ErrorAction SilentlyContinue) {
        $name = $proc.ProcessName
        if ($name -match '^(standard|explicit|ABQLauncher|ABQcaeK|abq\d*)$') {
            return $true
        }
    }
    return $false
}

function Test-AbaqusJobProcessRunning {
    param(
        [Parameter(Mandatory)][string]$JobName,
        [string]$JobDir = ''
    )
    $jobPat = [regex]::Escape($JobName)
    $dirPat = if ($JobDir) { [regex]::Escape($JobDir) } else { '' }
    foreach ($proc in Get-CimInstance Win32_Process -ErrorAction SilentlyContinue) {
        if ($proc.Name -notmatch '^(standard|explicit|ABQLauncher|ABQcaeK|abq\d*)\.exe$') { continue }
        $cmd = [string]$proc.CommandLine
        if ($cmd -match "job=$jobPat\b" -or $cmd -match $jobPat) { return $true }
        if ($dirPat -and $cmd -match $dirPat) { return $true }
    }
    return $false
}

function Stop-AbaqusJobProcesses {
    param(
        [Parameter(Mandatory)][string]$JobName,
        [Parameter(Mandatory)][string]$JobDir
    )
    $jobPat = [regex]::Escape($JobName)
    $dirPat = [regex]::Escape($JobDir)
    $stopped = 0
    foreach ($proc in Get-CimInstance Win32_Process -ErrorAction SilentlyContinue) {
        if ($proc.Name -notmatch '^(standard|explicit|ABQLauncher|ABQcaeK|abq\d*)\.exe$') { continue }
        $cmd = [string]$proc.CommandLine
        $exe = [string]$proc.ExecutablePath
        if ($cmd -notmatch "job=$jobPat\b" -and $cmd -notmatch $jobPat -and $cmd -notmatch $dirPat `
                -and $exe -notmatch $jobPat) { continue }
        try {
            Stop-Process -Id $proc.ProcessId -Force -ErrorAction Stop
            $stopped++
        } catch {
            Write-Host "  [WARN] Could not stop PID $($proc.ProcessId) ($($proc.Name))" -ForegroundColor Yellow
        }
    }
    $lck = Join-Path $JobDir ($JobName + '.lck')
    if (Test-Path $lck) { Remove-Item $lck -Force -ErrorAction SilentlyContinue }
    if ($stopped -gt 0) {
        Write-Host "  Stopped $stopped Abaqus process(es) for job $JobName" -ForegroundColor Yellow
        Start-Sleep -Seconds 3
    }
}

function Test-ProjectVenvPython {
    param([Parameter(Mandatory)][string]$Root)
    $VenvPy = Join-Path $Root ".venv\Scripts\python.exe"
    if (-not (Test-Path $VenvPy)) { return $false }

    $cfgPath = Join-Path $Root ".venv\pyvenv.cfg"
    if (Test-Path $cfgPath) {
        foreach ($line in Get-Content $cfgPath -ErrorAction SilentlyContinue) {
            if ($line -match '^\s*base-executable\s*=\s*(.+)\s*$') {
                if (-not (Test-Path $Matches[1].Trim())) { return $false }
                break
            }
        }
    }

    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $null = & $VenvPy -c "import sys; sys.exit(0)" 2>$null
        return ($LASTEXITCODE -eq 0)
    } catch {
        return $false
    } finally {
        $ErrorActionPreference = $prevEap
    }
}

function Get-PlotPythonCommand {
    param([Parameter(Mandatory)][string]$Root)
    $VenvPy = Join-Path $Root ".venv\Scripts\python.exe"
    if (Test-ProjectVenvPython -Root $Root) {
        return @{ Exe = $VenvPy; Prefix = @() }
    }
    if (Test-Path (Join-Path $Root ".venv\Scripts\python.exe")) {
        Write-Host "[WARN] .venv points to missing Python; using py -3 for plotting." -ForegroundColor Yellow
    }
    if (Get-Command py -ErrorAction SilentlyContinue) {
        return @{ Exe = "py"; Prefix = @("-3") }
    }
    return $null
}

function Invoke-PlotStressStrain {
    param(
        [Parameter(Mandatory)][string]$Root,
        [Parameter(Mandatory)][string]$Csv,
        [Parameter(Mandatory)][string]$Png
    )
    if (-not (Test-Path $Csv)) {
        Write-Host "[ERROR] CSV not found: $Csv" -ForegroundColor Red
        return 1
    }
    $cmd = Get-PlotPythonCommand -Root $Root
    if (-not $cmd) {
        Write-Host "[ERROR] Python not found for plotting." -ForegroundColor Red
        return 1
    }
    $plotScript = Join-Path $Root "scripts\plot_stress_strain.py"
    $allArgs = @($cmd.Prefix + @($plotScript, "--csv", $Csv, "--png", $Png, "--no-show"))

    # Do NOT pipe stdout into another cmdlet; that breaks $LASTEXITCODE on Windows PowerShell.
    # Assign to $null so Python "Saved: ..." lines do not pollute the function return value.
    $null = & $cmd.Exe @allArgs 2>&1
    $code = $LASTEXITCODE
    if ($null -eq $code) { $code = 0 }

    if ($code -ne 0) {
        Write-Host "[ERROR] plot_stress_strain.py exit code $code" -ForegroundColor Red
        return [int]$code
    }
    if (-not (Test-Path $Png)) {
        Write-Host "[ERROR] PNG not created: $Png" -ForegroundColor Red
        return 2
    }
    $pngTime = (Get-Item $Png).LastWriteTime
    $csvTime = (Get-Item $Csv).LastWriteTime
    if ($pngTime -lt $csvTime.AddSeconds(-1)) {
        Write-Host "[WARN] PNG is older than CSV; plot may not have refreshed." -ForegroundColor Yellow
        return 3
    }
    Write-Host "  Plot saved: $Png ($pngTime)" -ForegroundColor Green
    return [int]0
}

# Backward-compatible alias for other scripts
function Invoke-ProjectPython {
    param(
        [Parameter(Mandatory)][string]$Root,
        [Parameter(Mandatory)][string[]]$ScriptArgs
    )
    $cmd = Get-PlotPythonCommand -Root $Root
    if (-not $cmd) { return 1 }
    $null = & $cmd.Exe @($cmd.Prefix + $ScriptArgs) 2>&1
    $code = $LASTEXITCODE
    if ($null -eq $code) { return 0 }
    return [int]$code
}

function Invoke-PenetrationRiskCheck {
    param(
        [Parameter(Mandatory)][string]$Root,
        [Parameter(Mandatory)][string]$InpPath,
        [string]$ManifestPath = '',
        [string]$MetaPath = '',
        [switch]$SkipPenetrationCheck,
        [switch]$StrictPenetration
    )

    if ($SkipPenetrationCheck) {
        Write-Host "  Penetration precheck skipped (-SkipPenetrationCheck)." -ForegroundColor DarkGray
        return
    }

    $checkScript = Join-Path $Root "scripts\check_penetration_risk.py"
    if (-not (Test-Path $checkScript)) {
        Write-Host "[WARN] Missing $checkScript — penetration precheck skipped." -ForegroundColor Yellow
        return
    }

    if ([string]::IsNullOrWhiteSpace($ManifestPath)) {
        $ManifestPath = Join-Path $Root "output\active_case.json"
    }

    $pyArgs = @(
        $checkScript,
        "--manifest", $ManifestPath,
        "--inp", $InpPath
    )
    if ($MetaPath) {
        $pyArgs += @("--meta", $MetaPath)
    }

    Write-Host "[1b] Penetration risk precheck ..." -ForegroundColor Cyan
    $cmd = Get-PlotPythonCommand -Root $Root
    if (-not $cmd) {
        Write-Host "[WARN] Python not found — penetration precheck skipped." -ForegroundColor Yellow
        return
    }
    & $cmd.Exe @($cmd.Prefix + $pyArgs)
    $rc = $LASTEXITCODE
    if ($null -eq $rc) { $rc = 0 }

    if ($rc -eq 0) {
        Write-Host "  Penetration precheck OK" -ForegroundColor Green
        return
    }

    if ($rc -eq 1) {
        Write-Host "[穿模风险 ERROR] See messages above." -ForegroundColor Red
    } elseif ($rc -eq 2) {
        Write-Host "[穿模风险 WARN] High penetration risk detected." -ForegroundColor Yellow
    } else {
        Write-Host "[WARN] Penetration check exit code $rc" -ForegroundColor Yellow
    }

    if ($StrictPenetration) {
        Write-Host "  -StrictPenetration: aborting submit." -ForegroundColor Red
        exit 1
    }

    if ($rc -eq 0) { return }

    Write-Host "  Suggestions: enable lattice_self_contact, use coupling_nodes, or run a small-displacement pilot." -ForegroundColor Yellow
    if (-not [Environment]::UserInteractive -or [Console]::IsInputRedirected) {
        Write-Host "  Non-interactive session: continuing submit despite penetration WARN." -ForegroundColor Yellow
        return
    }
    do {
        $ans = Read-Host 'Continue Abaqus submit anyway? (Y/N, default N)'
        if ([string]::IsNullOrWhiteSpace($ans)) { $ans = 'N' }
        $ans = $ans.Trim()
        if ($ans -match '^(y|yes|Y)$') { return }
        if ($ans -match '^(n|no|N)$') {
            Write-Host "  Submit cancelled." -ForegroundColor Yellow
            exit 1
        }
        Write-Host '  Enter Y or N.' -ForegroundColor Yellow
    } while ($true)
}

function Remove-AbaqusJobArtifacts {
    param(
        [Parameter(Mandatory)][string]$JobDir,
        [Parameter(Mandatory)][string]$JobName
    )
    $exts = @(
        'odb', 'sta', 'dat', 'msg', 'com', 'prt', 'lck', 'sim', 'stb', 'res', 'mdl',
        'pac', 'sel', 'abq', 'stt', 'cid', 'simlog', '023', '024'
    )
    $paths = @()
    foreach ($ext in $exts) {
        $p = Join-Path $JobDir ($JobName + '.' + $ext)
        if (Test-Path $p) { $paths += $p }
    }
    Get-ChildItem -Path $JobDir -Filter ($JobName + '.msg.*') -ErrorAction SilentlyContinue |
        ForEach-Object { $paths += $_.FullName }
    $simdir = Join-Path $JobDir ($JobName + '.simdir')
    if (Test-Path $simdir) { $paths += $simdir }

    for ($attempt = 1; $attempt -le 5; $attempt++) {
        foreach ($p in $paths) {
            if (-not (Test-Path $p)) { continue }
            if ((Get-Item $p -Force).PSIsContainer) {
                Remove-Item $p -Recurse -Force -ErrorAction SilentlyContinue
            } else {
                Remove-Item $p -Force -ErrorAction SilentlyContinue
            }
        }
        $remaining = $paths | Where-Object { Test-Path $_ }
        if (-not $remaining) { return }
        if ($attempt -lt 5) { Start-Sleep -Seconds 2 }
    }
    Write-Host "  [WARN] Could not delete: $($remaining -join ', ')" -ForegroundColor Yellow
}

function Prepare-AbaqusJobRerun {
    param(
        [Parameter(Mandatory)][string]$JobDir,
        [Parameter(Mandatory)][string]$JobName,
        [switch]$Force
    )
    if ($Force) {
        Write-Host "  ForceRerun: stopping any Abaqus processes for $JobName ..." -ForegroundColor Yellow
        Stop-AbaqusJobProcesses -JobName $JobName -JobDir $JobDir
    }

    $lck = Join-Path $JobDir ($JobName + '.lck')
    $jobActive = (Test-Path $lck) -and (Test-AbaqusJobProcessRunning -JobName $JobName -JobDir $JobDir)

    if ($jobActive) {
        if ($Force) {
            Stop-AbaqusJobProcesses -JobName $JobName -JobDir $JobDir
        } else {
            Write-Host "[ERROR] Job $JobName is still running ($lck)." -ForegroundColor Red
            Write-Host "  Wait for completion, or re-run with -ForceRerun to stop and restart." -ForegroundColor Yellow
            exit 1
        }
    } elseif (Test-Path $lck) {
        Write-Host "  Removing stale lock: $lck" -ForegroundColor Yellow
        Remove-Item $lck -Force -ErrorAction SilentlyContinue
    }
    Remove-AbaqusJobArtifacts -JobDir $JobDir -JobName $JobName
}

function Prepare-AbaqusJobContinue {
    param(
        [Parameter(Mandatory)][string]$JobDir,
        [Parameter(Mandatory)][string]$JobName,
        [switch]$Force
    )
    if ($Force) {
        Write-Host "  Continue: stopping any Abaqus processes for $JobName ..." -ForegroundColor Yellow
        Stop-AbaqusJobProcesses -JobName $JobName -JobDir $JobDir
    }

    $lck = Join-Path $JobDir ($JobName + '.lck')
    $jobActive = (Test-Path $lck) -and (Test-AbaqusJobProcessRunning -JobName $JobName -JobDir $JobDir)

    if ($jobActive) {
        if ($Force) {
            Stop-AbaqusJobProcesses -JobName $JobName -JobDir $JobDir
        } else {
            Write-Host "[ERROR] Job $JobName is still running ($lck)." -ForegroundColor Red
            Write-Host "  Wait for completion, or re-run with -Force on -Continue." -ForegroundColor Yellow
            exit 1
        }
    } elseif (Test-Path $lck) {
        Write-Host "  Removing stale lock: $lck" -ForegroundColor Yellow
        Remove-Item $lck -Force -ErrorAction SilentlyContinue
    }
}

function Add-ExplicitRestartReadToInp {
    param(
        [Parameter(Mandatory)][string]$InpPath
    )
    if (-not (Test-Path $InpPath)) {
        throw "INP not found for restart read: $InpPath"
    }
    $text = Get-Content $InpPath -Raw -Encoding UTF8
    if ($text -match '(?m)^\*Restart,\s*read\b') {
        return
    }
    if ($text -notmatch '(?m)^\*Step,') {
        throw "INP missing *Step block: $InpPath"
    }
    $updated = [regex]::Replace(
        $text,
        '(?m)^(\*Step,)',
        "*Restart, read, step=1`r`n`$1",
        1
    )
    Set-Content -Path $InpPath -Value $updated -NoNewline -Encoding UTF8
}

function Clear-AbaqusJobDirectory {
    param([Parameter(Mandatory)][string]$JobDir)
    if (-not (Test-Path $JobDir)) { return }
    Get-ChildItem -Path $JobDir -Force -ErrorAction SilentlyContinue |
        Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
}

function Get-VerifiedCadDir {
    param([Parameter(Mandatory)][string]$Root)
    return (Join-Path $Root "output\cad\verified")
}

function Get-VerifiedCadStep {
    param(
        [Parameter(Mandatory)][string]$Root,
        [Parameter(Mandatory)][string]$Variant,
        [int]$Cells = 4,
        [string[]]$ExtraNames = @()
    )
    $verifiedDir = Get-VerifiedCadDir -Root $Root
    if (-not (Test-Path $verifiedDir)) {
        throw "Missing verified CAD folder: $verifiedDir"
    }
    $base = "hu_bai_${Variant}_L20_${Cells}x${Cells}x${Cells}"
    $names = @(
        "${base}_solid_array.step",
        "${base}_solid_array.STEP",
        "${base}_solid_merged.step",
        "${base}_solid_merged.STEP",
        "${base}_solid_layered.step",
        "${base}_solid.step"
    ) + $ExtraNames
    foreach ($name in $names) {
        $path = Join-Path $verifiedDir $name
        if (Test-Path $path) {
            return (Resolve-Path $path).Path
        }
    }
    $hint = Join-Path $verifiedDir "${base}_solid_array.step"
    throw "No verified CAD STEP for $base under $verifiedDir. Expected e.g. $hint"
}

function Test-VerifiedCadStepReady {
    param(
        [Parameter(Mandatory)][string]$Root,
        [Parameter(Mandatory)][string]$Variant,
        [int]$Cells = 4
    )
    try {
        $null = Get-VerifiedCadStep -Root $Root -Variant $Variant -Cells $Cells
        return $true
    } catch {
        return $false
    }
}
