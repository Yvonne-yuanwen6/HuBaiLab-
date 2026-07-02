# Poll server until all four voxel0p6mm80_5mmin_autodt jobs finish; log progress overnight.
param(
    [string]$Server = "art@172.20.200.93",
    [string]$Remote = "/media/art/file/XiangLang/Lattice/LWY/HuBaiLab",
    [int]$PollSeconds = 180,
    [double]$StepTimeS = 768.0
)

$ErrorActionPreference = "SilentlyContinue"
$ScriptDir = $PSScriptRoot
$Root = (Resolve-Path (Join-Path $ScriptDir "..")).Path
$Suffix = "voxel0p6mm80_5mmin_autodt"
$Slugs = @(
    "hu_bai_bcc_af2q0_L20_4x4x4_solid_cad_f_$Suffix",
    "hu_bai_sfbls_af2q0p5_L20_4x4x4_solid_cad_f_$Suffix",
    "hu_bai_sfbls_af2q1_L20_4x4x4_solid_cad_f_$Suffix",
    "hu_bai_sfbls_af2q1p5_L20_4x4x4_solid_cad_f_$Suffix"
)
$LogDir = Join-Path $Root "output\logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$LogPath = Join-Path $LogDir "voxel0p6mm80_5mmin_autodt_watch.log"

function Write-Log([string]$Msg) {
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  $Msg"
    Add-Content -Path $LogPath -Value $line -Encoding UTF8
    Write-Host $line
}

function Get-SlugStatus([string]$Slug) {
    $remoteSta = "${Remote}/output/jobs/${Slug}/${Slug}.sta"
    $remoteLck = "${Remote}/output/jobs/${Slug}/${Slug}.lck"
    $lck = ssh $Server "test -f '$remoteLck' && echo 1 || echo 0" 2>$null
    $done = ssh $Server "grep -q 'COMPLETED SUCCESSFULLY' '$remoteSta' 2>/dev/null && echo 1 || echo 0" 2>$null
    if ($done -eq "1") {
        return [PSCustomObject]@{ State = "DONE"; Detail = "COMPLETED SUCCESSFULLY" }
    }
    if ($lck -eq "1") {
        $frame = ssh $Server "grep 'Output Field Frame' '$remoteSta' 2>/dev/null | tail -1" 2>$null
        if ($frame -match 'Frame Number\s+(\d+),\s+of\s+(\d+),\s+at step time\s+([\d.E+-]+)') {
            $pct = [math]::Round(100.0 * [double]$Matches[3] / $StepTimeS, 1)
            return [PSCustomObject]@{ State = "RUN"; Detail = "frame $($Matches[1])/$($Matches[2]) sim=$pct%" }
        }
        return [PSCustomObject]@{ State = "RUN"; Detail = "packager/pre (no frame yet)" }
    }
    if (ssh $Server "test -f '$remoteSta' && echo 1 || echo 0" 2>$null -eq "1") {
        return [PSCustomObject]@{ State = "FAIL?"; Detail = "sta exists, no lck, not completed" }
    }
    return [PSCustomObject]@{ State = "WAIT"; Detail = "not started" }
}

Write-Log "=== watch start: $($Slugs.Count) jobs, poll=${PollSeconds}s, step=${StepTimeS}s ==="
while ($true) {
    $done = 0
    foreach ($s in $Slugs) {
        $st = Get-SlugStatus $s
        $short = ($s -replace 'hu_bai_', '' -replace "_L20_4x4x4_solid_cad_f_$Suffix", '')
        Write-Log "[$($st.State)] $short â€?$($st.Detail)"
        if ($st.State -eq "DONE") { $done++ }
        if ($st.State -eq "FAIL?") { Write-Log "[ALERT] $s may have failed â€?check queue log on server" }
    }
    if ($done -eq $Slugs.Count) {
        Write-Log "=== ALL $($Slugs.Count) JOBS COMPLETED ==="
        break
    }
    Start-Sleep -Seconds $PollSeconds
}
