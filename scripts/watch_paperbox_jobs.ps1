# Monitor BCC + SFBLS paper_box CAE tet jobs (remote poll).
param(
    [string]$RemoteHost = "art@172.20.200.93",
    [string]$RemoteRoot = "/media/art/file/XiangLang/Lattice/LWY/HuBaiLab",
    [double]$StepTimeS = 883.2,
    [double]$TargetStrain = 0.8,
    [int]$PollSeconds = 15
)

$ErrorActionPreference = "SilentlyContinue"
$Jobs = @(
    @{ Label = "BCC Q=0"; Slug = "hu_bai_bcc_af2q0_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox" },
    @{ Label = "SFBLS Q=0.5"; Slug = "hu_bai_sfbls_af2q0p5_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox" }
)

Write-Host "=== Paperbox dual monitor (poll=${PollSeconds}s) ===" -ForegroundColor Cyan
Write-Host "  Remote: ${RemoteHost}:${RemoteRoot}" -ForegroundColor Cyan
Write-Host ""

while ($true) {
    $now = Get-Date -Format "HH:mm:ss"
    Write-Host "========== [$now] ==========" -ForegroundColor DarkGray
    foreach ($j in $Jobs) {
        $slug = $j.Slug
        $sta = "$RemoteRoot/output/jobs/$slug/$slug.sta"
        $lck = "$RemoteRoot/output/jobs/$slug/$slug.lck"
        $line = ssh $RemoteHost "grep -E '^[[:space:]]+[1-9][0-9]*[[:space:]]+' '$sta' 2>/dev/null | tail -1"
        $completed = ssh $RemoteHost "grep -c 'COMPLETED SUCCESSFULLY' '$sta' 2>/dev/null"
        $hasLck = ssh $RemoteHost "if [ -f '$lck' ]; then echo 1; else echo 0; fi"
        if ([int]$completed -gt 0) { $st = "COMPLETED" }
        elseif ($hasLck -eq "1") { $st = "RUNNING" }
        elseif ($line) { $st = "STOPPED" }
        else { $st = "WAITING/MESH" }

        $simS = 0.0
        $wall = "--:--:--"
        if ($line -match '^\s+(\d+)\s+([\d.E+-]+)\s+([\d.E+-]+)\s+(\d\d:\d\d:\d\d)') {
            $simS = [double]$Matches[3]
            $wall = $Matches[4]
        }
        $pct = if ($StepTimeS -gt 0) { [math]::Min(100, 100 * $simS / $StepTimeS) } else { 0 }
        $estr = $TargetStrain * $simS / $StepTimeS * 100
        $filled = [int][math]::Floor(40 * $pct / 100)
        $bar = ("#" * $filled).PadRight(40, "-")
        $color = switch ($st) { "COMPLETED" { "Green" } "RUNNING" { "Yellow" } default { "Gray" } }
        Write-Host ("--- {0} [{1}] ---" -f $j.Label, $st) -ForegroundColor $color
        Write-Host ("  [{0}] {1,5:F1}%  sim {2,7:F1}/{3} s  strain~{4,5:F1}%  wall {5}" -f $bar, $pct, $simS, $StepTimeS, $estr, $wall)
        if ($st -eq "WAITING/MESH" -and $j.Label -like "SFBLS*") {
            $ml = ssh $RemoteHost "tail -2 '$RemoteRoot/output/export/$slug/cae_hex_pilot.log' 2>/dev/null"
            if ($ml) { Write-Host "  mesh: $ml" -ForegroundColor DarkYellow }
        }
        Write-Host ""
    }
    Start-Sleep -Seconds $PollSeconds
}
