# Poll snap-through sweep on server; post-pull + analyze when all jobs done.
param(
    [string]$Server = "art@172.20.200.93",
    [string]$Remote = "/media/art/file/XiangLang/Lattice/LWY/HuBaiLab",
    [string]$Local = "D:\HuBaiLab",
    [int]$PollSeconds = 300
)

$ErrorActionPreference = "SilentlyContinue"
$Log = Join-Path $Local "output\logs\paperbox_snapthrough_watch.log"
$Suffixes = @(
    "cae_tet0p6mm80_5mmin_paperbox_paperbox_nosettle",
    "cae_tet0p6mm80_5mmin_paperbox_paperbox_settle5p",
    "cae_tet0p6mm80_5mmin_paperbox_paperbox_nosettle_dt1e4",
    "cae_tet0p6mm80_5mmin_paperbox_paperbox_nosettle_dt1e4_nohold"
)
$Tags = @("sfbls_af2q0p5")  # Q=0.5 only (BCC sweep paused per user)

function Get-Slugs {
    foreach ($tag in $Tags) {
        foreach ($suffix in $Suffixes) {
            "hu_bai_${tag}_L20_4x4x4_solid_cad_f_$suffix"
        }
    }
}

function Test-RemoteCompleted($slug) {
    $sta = "$Remote/output/jobs/$slug/$slug.sta"
    $out = ssh $Server "grep -c 'COMPLETED SUCCESSFULLY' '$sta' 2>/dev/null || echo 0"
    return ([int]$out.Trim()) -gt 0
}

function Test-RemoteRunning($slug) {
    $lck = "$Remote/output/jobs/$slug/$slug.lck"
    $out = ssh $Server "if [ -f '$lck' ]; then echo 1; else echo 0; fi"
    return $out.Trim() -eq "1"
}

"=== snapthrough watch start $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') ===" | Tee-Object -FilePath $Log -Append

while ($true) {
    $slugs = Get-Slugs
    $done = 0
    $running = 0
    $failed = 0
    $pending = 0
    foreach ($s in $slugs) {
        if (Test-RemoteCompleted $s) { $done++ }
        elseif (Test-RemoteRunning $s) { $running++ }
        else {
            $staExists = ssh $Server "test -f '$Remote/output/jobs/$s/$s.sta' && echo 1 || echo 0"
            if ($staExists.Trim() -eq "1") { $failed++ } else { $pending++ }
        }
    }
    $line = "[$(Get-Date -Format 'HH:mm:ss')] done=$done running=$running failed=$failed pending=$pending / $($slugs.Count)"
    Write-Host $line
    $line | Out-File -FilePath $Log -Append
    $tail = ssh $Server "tail -3 '$Remote/output/logs/paperbox_snapthrough_sweep.log' 2>/dev/null"
    if ($tail) { $tail | Out-File -FilePath $Log -Append }

    $sweepDone = ssh $Server "grep -c '^DONE ' '$Remote/output/logs/paperbox_snapthrough_sweep.log' 2>/dev/null || echo 0"
    if ([int]$sweepDone.Trim() -gt 0) {
        "=== sweep log DONE $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') done=$done failed=$failed running=$running ===" | Tee-Object -FilePath $Log -Append
        break
    }
    if ($running -eq 0 -and $pending -eq 0 -and ($done + $failed) -ge 3) {
        "=== no running jobs $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') done=$done failed=$failed ===" | Tee-Object -FilePath $Log -Append
        break
    }
    Start-Sleep -Seconds $PollSeconds
}

Set-Location $Local
powershell -NoProfile -File scripts\postpull_paperbox_snapthrough.ps1 -Server $Server -Remote $Remote -Local $Local 2>&1 | Tee-Object -FilePath $Log -Append
"=== watch complete $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') ===" | Out-File -FilePath $Log -Append
