# Poll server until both paper_box CAE tet jobs COMPLETED, then post-process and plot.
param(
    [string]$Server = "art@172.20.200.93",
    [string]$Remote = "/media/art/file/XiangLang/Lattice/LWY/HuBaiLab",
    [int]$PollSeconds = 120
)

$Suffix = "cae_tet0p6mm80_5mmin_paperbox"
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

Write-Host "=== Waiting for paper_box CAE tet jobs (BCC + SFBLS Q=0.5/1/1.5) ===" -ForegroundColor Cyan
while ($true) {
    $done = 0
    foreach ($s in $Slugs) {
        if (Test-SlugCompleted $s) {
            $done++
            Write-Host "  [OK] $s" -ForegroundColor Green
        } else {
            $line = ssh $Server "grep -E '^[[:space:]]+[1-9]' ${Remote}/output/jobs/${s}/${s}.sta 2>/dev/null | tail -1"
            $lck = ssh $Server "test -f ${Remote}/output/jobs/${s}/${s}.lck && echo RUN || echo idle"
            Write-Host "  [..] $s ($lck)  $line"
        }
    }
    if ($done -eq $Slugs.Count) { break }
    Write-Host "$(Get-Date -Format 'HH:mm:ss')  $done/$($Slugs.Count) done; sleep ${PollSeconds}s"
    Start-Sleep -Seconds $PollSeconds
}

Write-Host "=== All complete â€?post-process ===" -ForegroundColor Cyan
& "$PSScriptRoot\postpull_paperbox_cae_tet_batch.ps1" -Server $Server -Remote $Remote
