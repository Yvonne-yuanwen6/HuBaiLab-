# Poll server until all four autodt jobs COMPLETED, then post-process and plot.
param(
    [string]$Server = "art@172.20.200.93",
    [string]$Remote = "/home/art/Documents/Lattice/LWY/HuBaiLab",
    [int]$PollSeconds = 120
)

$Suffix = "voxel0p8mm80_15mmin_autodt"
$Slugs = @(
    "hu_bai_bcc_af2q0_L20_4x4x4_solid_cad_f_$Suffix",
    "hu_bai_sfbls_af2q0p5_L20_4x4x4_solid_cad_f_$Suffix",
    "hu_bai_sfbls_af2q1_L20_4x4x4_solid_cad_f_$Suffix",
    "hu_bai_sfbls_af2q1p5_L20_4x4x4_solid_cad_f_$Suffix"
)

function Test-SlugCompleted([string]$Slug) {
    $sta = ssh $Server "grep 'COMPLETED SUCCESSFULLY' ${Remote}/output/jobs/${Slug}/${Slug}.sta 2>/dev/null"
    return [bool]$sta
}

Write-Host "=== Waiting for 4 autodt jobs ===" -ForegroundColor Cyan
while ($true) {
    $done = 0
    foreach ($s in $Slugs) {
        if (Test-SlugCompleted $s) {
            $done++
            Write-Host "  [OK] $s" -ForegroundColor Green
        } else {
            $lck = ssh $Server "test -f ${Remote}/output/jobs/${s}/${s}.lck && echo RUN || echo idle"
            Write-Host "  [..] $s ($lck)"
        }
    }
    if ($done -eq $Slugs.Count) { break }
    Write-Host "$(Get-Date -Format 'HH:mm:ss')  $done/$($Slugs.Count) done; sleep ${PollSeconds}s"
    Start-Sleep -Seconds $PollSeconds
}

Write-Host "=== All complete — post-process ===" -ForegroundColor Cyan
& "$PSScriptRoot\postpull_voxel0p8mm80_autodt_batch.ps1"
