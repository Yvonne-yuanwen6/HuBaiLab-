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

function Get-AbaqusStaFailureSummary {
    param(
        [string]$StaPath = ''
    )
    if (-not $StaPath -or -not (Test-Path $StaPath)) { return 'incomplete' }
    $staText = Get-Content $StaPath -Raw -ErrorAction SilentlyContinue
    if (-not $staText) { return 'incomplete' }
    if ($staText -match 'deformation speed/wave speed') { return 'deformation_speed' }
    if ($staText -match 'THE ANALYSIS HAS NOT BEEN COMPLETED') { return 'not_completed' }
    if ($staText -match '\*\*\*ERROR') { return 'abaqus_error' }
    if ($staText -match 'SOLUTION PROGRESS') { return 'incomplete' }
    return 'unknown'
}

function Test-AbaqusJobWorthArchiving {
    param(
        [Parameter(Mandatory)][string]$JobDir,
        [Parameter(Mandatory)][string]$JobName,
        [string]$StaPath = '',
        [string]$OdbPath = ''
    )
    if (-not (Test-Path $JobDir)) { return $false }
    $sta = if ($StaPath) { $StaPath } else { Join-Path $JobDir ($JobName + '.sta') }
    $odb = if ($OdbPath) { $OdbPath } else { Join-Path $JobDir ($JobName + '.odb') }
    if (Test-AbaqusJobCompleted -StaPath $sta -OdbPath $odb) { return $false }
    if (Test-Path $odb) { return $true }
    if (Test-AbaqusJobIncomplete -StaPath $sta -OdbPath $odb) { return $true }
    $matches = @(Get-ChildItem -Path $JobDir -Force -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -like "$JobName*" -or $_.Name -like "${JobName}_cont*" })
    return ($matches.Count -gt 0)
}

function Resolve-ArchiveCompressionMeta {
    param(
        [Parameter(Mandatory)][string]$Root,
        [string]$Slug = '',
        [string]$MetaPath = ''
    )
    if ($MetaPath -and (Test-Path $MetaPath)) { return (Resolve-Path $MetaPath).Path }
    if (-not $Slug) { return $null }
    $direct = Join-Path $Root "output\export\$Slug\${Slug}_meta.json"
    if (Test-Path $direct) { return (Resolve-Path $direct).Path }
    $exportDir = Join-Path $Root "output\export\$Slug"
    if (Test-Path $exportDir) {
        $found = Get-ChildItem -Path $exportDir -Filter '*_meta.json' -ErrorAction SilentlyContinue |
            Select-Object -First 1
        if ($found) { return $found.FullName }
    }
    return $null
}

function Invoke-ArchiveStressStrainPost {
    param(
        [Parameter(Mandatory)][string]$Root,
        [Parameter(Mandatory)][string]$OdbPath,
        [Parameter(Mandatory)][string]$MetaPath,
        [Parameter(Mandatory)][string]$DestPost,
        [Parameter(Mandatory)][string]$JobName
    )
    $extract = Join-Path $Root 'scripts\extract_stress_strain_from_odb.py'
    if (-not (Test-Path $extract)) {
        return [PSCustomObject]@{ Ok = $false; Reason = 'extract_script_missing' }
    }
    if (-not (Get-Command abaqus -ErrorAction SilentlyContinue)) {
        return [PSCustomObject]@{ Ok = $false; Reason = 'abaqus_not_in_path' }
    }
    New-Item -ItemType Directory -Force -Path $DestPost | Out-Null
    $csv = Join-Path $DestPost ($JobName + '_stress_strain.csv')
    $raw = Join-Path $DestPost ($JobName + '_stress_strain_raw.csv')
    $yield = Join-Path $DestPost ($JobName + '_yield.json')
    $png = Join-Path $DestPost ($JobName + '_stress_strain.png')

    $extractArgs = @(
        $extract, '--odb', $OdbPath, '--meta', $MetaPath, '--csv', $csv,
        '--raw-csv', $raw, '--force-mode', 'paper', '--curve-method', 'paper', '--yield-json', $yield, '--no-raw'
    )
    $null = & abaqus python @extractArgs 2>&1
    $code = $LASTEXITCODE
    if ($null -eq $code) { $code = 0 }
    if ($code -ne 0) {
        $extractArgs = @(
            $extract, '--odb', $OdbPath, '--meta', $MetaPath, '--csv', $csv,
            '--raw-csv', $raw, '--force-mode', 'fixed_bottom_ref', '--curve-method', 'paper', '--yield-json', $yield, '--no-raw'
        )
        $null = & abaqus python @extractArgs 2>&1
        $code = $LASTEXITCODE
        if ($null -eq $code) { $code = 0 }
    }
    if ($code -ne 0 -or -not (Test-Path $csv)) {
        return [PSCustomObject]@{ Ok = $false; Reason = "extract_exit_$code"; Csv = $csv }
    }
    $null = Invoke-PlotStressStrain -Root $Root -Csv $csv -Png $png
    return [PSCustomObject]@{
        Ok = $true
        Reason = 'extracted_from_odb'
        Csv = $csv
        Png = $png
        YieldJson = $yield
    }
}

function Archive-FailedAbaqusJob {
    param(
        [Parameter(Mandatory)][string]$Root,
        [Parameter(Mandatory)][string]$JobDir,
        [Parameter(Mandatory)][string]$JobName,
        [string]$Slug = '',
        [string]$PostDir = '',
        [string]$MetaPath = '',
        [string]$Reason = '',
        [string]$StaPath = ''
    )
    if (-not (Test-AbaqusJobWorthArchiving -JobDir $JobDir -JobName $JobName -StaPath $StaPath)) {
        return $null
    }

    if (-not $Slug) { $Slug = $JobName }
    $sta = if ($StaPath) { $StaPath } else { Join-Path $JobDir ($JobName + '.sta') }
    $reasonTag = if ($Reason) { $Reason } else { Get-AbaqusStaFailureSummary -StaPath $sta }
    $safeReason = ($reasonTag -replace '[^\w\-.]+', '_').Trim('_')
    if ($safeReason.Length -gt 48) { $safeReason = $safeReason.Substring(0, 48) }
    $archiveId = (Get-Date -Format 'yyyyMMdd_HHmmss') + '_' + $safeReason

    $destRoot = Join-Path $Root "output\failed\$Slug\$archiveId"
    $destJobs = Join-Path $destRoot 'jobs'
    if (Test-Path $destRoot) {
        throw "Archive target already exists: $destRoot"
    }
    New-Item -ItemType Directory -Force -Path $destJobs | Out-Null

    $staTail = @()
    if (Test-Path $sta) {
        $staTail = @(Get-Content $sta -Tail 8 -ErrorAction SilentlyContinue)
    }

    $moved = @()
    Get-ChildItem -Path $JobDir -Force -ErrorAction SilentlyContinue |
        Where-Object {
            ($_.Name -like "$JobName*" -or $_.Name -like "${JobName}_cont*") -and
            ($_.Extension -ne '.inp')
        } |
        ForEach-Object {
            Move-Item -LiteralPath $_.FullName -Destination $destJobs -Force
            $moved += $_.Name
        }

    $destPost = Join-Path $destRoot 'post'
    $metaResolved = Resolve-ArchiveCompressionMeta -Root $Root -Slug $Slug -MetaPath $MetaPath
    $metaSnapshot = Join-Path $destRoot 'compression_meta.json'
    if ($metaResolved) {
        Copy-Item -LiteralPath $metaResolved -Destination $metaSnapshot -Force
    }

    $archivedOdb = Join-Path $destJobs ($JobName + '.odb')
    $postExtract = [ordered]@{
        status = 'skipped'
        reason = 'no_odb'
        csv = $null
        png = $null
    }
    if (Test-Path $archivedOdb) {
        if (-not (Test-Path $metaSnapshot)) {
            $postExtract.reason = 'meta_not_found'
        } else {
            $extractResult = Invoke-ArchiveStressStrainPost -Root $Root -OdbPath $archivedOdb `
                -MetaPath $metaSnapshot -DestPost $destPost -JobName $JobName
            if ($extractResult.Ok) {
                $postExtract.status = 'extracted_from_odb'
                $postExtract.reason = $extractResult.Reason
                $postExtract.csv = $extractResult.Csv
                $postExtract.png = $extractResult.Png
            } else {
                $postExtract.status = 'extract_failed'
                $postExtract.reason = $extractResult.Reason
            }
        }
    }

    $manifest = [ordered]@{
        slug = $Slug
        job_name = $JobName
        archived_at = (Get-Date).ToString('o')
        reason = $reasonTag
        source_job_dir = $JobDir
        compression_meta = $(if (Test-Path $metaSnapshot) { $metaSnapshot } else { $null })
        post_extract = $postExtract
        moved_job_files = $moved
        sta_tail = $staTail
    }
    $manifestPath = Join-Path $destRoot 'failure_manifest.json'
    $manifest | ConvertTo-Json -Depth 6 | Set-Content -Path $manifestPath -Encoding UTF8

    Write-Host "  Archived failed run -> output\failed\$Slug\$archiveId" -ForegroundColor Cyan
    Write-Host "    jobs: $($moved.Count) file(s), manifest: failure_manifest.json" -ForegroundColor DarkCyan
    if ($postExtract.status -eq 'extracted_from_odb') {
        Write-Host "    post: extracted from archived ODB -> $destPost" -ForegroundColor DarkCyan
    } elseif ($postExtract.status -eq 'extract_failed') {
        Write-Host "    post: extract failed ($($postExtract.reason)); see jobs/*.odb" -ForegroundColor Yellow
    } else {
        Write-Host "    post: skipped ($($postExtract.reason))" -ForegroundColor DarkYellow
    }
    return $destRoot
}

function Repair-FailedArchivePost {
    param(
        [Parameter(Mandatory)][string]$Root,
        [Parameter(Mandatory)][string]$ArchiveRoot,
        [string]$MetaPath = ''
    )
    if (-not (Test-Path $ArchiveRoot)) {
        throw "Archive not found: $ArchiveRoot"
    }
    $manifestPath = Join-Path $ArchiveRoot 'failure_manifest.json'
    $slug = ''
    $jobName = ''
    if (Test-Path $manifestPath) {
        try {
            $manifest = Get-Content $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
            $slug = [string]$manifest.slug
            $jobName = [string]$manifest.job_name
        } catch { }
    }
    $jobsDir = Join-Path $ArchiveRoot 'jobs'
    if (-not $jobName) {
        $odbGuess = Get-ChildItem -Path $jobsDir -Filter '*.odb' -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($odbGuess) { $jobName = [System.IO.Path]::GetFileNameWithoutExtension($odbGuess.Name) }
    }
    if (-not $jobName) { throw "Cannot determine job name under $ArchiveRoot" }
    if (-not $slug) { $slug = $jobName }

    $odb = Join-Path $jobsDir ($jobName + '.odb')
    if (-not (Test-Path $odb)) { throw "No ODB in archive: $odb" }

    $metaSnapshot = Join-Path $ArchiveRoot 'compression_meta.json'
    $metaUse = $MetaPath
    if (-not $metaUse -and (Test-Path $metaSnapshot)) { $metaUse = $metaSnapshot }
    if (-not $metaUse) {
        $metaUse = Resolve-ArchiveCompressionMeta -Root $Root -Slug $slug -MetaPath $MetaPath
    }
    if (-not $metaUse) { throw "No compression meta for slug $slug" }
    if (-not (Test-Path $metaSnapshot)) {
        Copy-Item -LiteralPath $metaUse -Destination $metaSnapshot -Force
    }

    $destPost = Join-Path $ArchiveRoot 'post'
    $result = Invoke-ArchiveStressStrainPost -Root $Root -OdbPath $odb -MetaPath $metaUse `
        -DestPost $destPost -JobName $jobName
    if (-not $result.Ok) { throw "Extract failed: $($result.Reason)" }

    if (Test-Path $manifestPath) {
        try {
            $manifestObj = Get-Content $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
            $manifestObj | Add-Member -NotePropertyName compression_meta -NotePropertyValue $metaSnapshot -Force
            $manifestObj | Add-Member -NotePropertyName post_extract -NotePropertyValue ([ordered]@{
                status = 'extracted_from_odb'
                reason = 'repair_script'
                repaired_at = (Get-Date).ToString('o')
                csv = $result.Csv
                png = $result.Png
            }) -Force
            $manifestObj | ConvertTo-Json -Depth 8 | Set-Content -Path $manifestPath -Encoding UTF8
        } catch { }
    }
    return $result
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
    $allArgs = @($cmd.Prefix + @($plotScript, "--csv", $Csv, "--png", $Png, "--paper-style", "--no-show"))

    # Do NOT pipe stdout into another cmdlet; that breaks $LASTEXITCODE on Windows PowerShell.
    # Assign to $null so Python "Saved: ..." lines do not pollute the function return value.
    $plotOut = & $cmd.Exe @allArgs 2>&1
    $code = $LASTEXITCODE
    if ($null -eq $code) { $code = 0 }

    if ($code -ne 0 -and (Test-Path $Png)) {
        Write-Host "[WARN] plot_stress_strain.py exit code $code but PNG exists: $Png" -ForegroundColor Yellow
        return 0
    }
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
        Write-Host "[WARN] Missing $checkScript �?penetration precheck skipped." -ForegroundColor Yellow
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
        Write-Host "[WARN] Python not found �?penetration precheck skipped." -ForegroundColor Yellow
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
        if ($ext -eq 'inp') { continue }
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
        [string]$Root = '',
        [string]$PostDir = '',
        [string]$MetaPath = '',
        [string]$Slug = '',
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

    if ($Root) {
        $archiveReason = if ($Force) { 'force_rerun' } else { 'rerun' }
        Archive-FailedAbaqusJob -Root $Root -JobDir $JobDir -JobName $JobName `
            -Slug $Slug -PostDir $PostDir -MetaPath $MetaPath -Reason $archiveReason
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
