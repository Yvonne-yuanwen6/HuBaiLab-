# Monitor q05 export (CAE mesh) + Abaqus solve in one terminal.
param(
    [string]$Slug = "q05_c10m_s05r4_el_s78",
    [string]$RemoteHost = "art@172.20.200.93",
    [string]$RemoteRoot = "/media/art/file/XiangLang/Lattice/LWY/HuBaiLab",
    [int]$PollSeconds = 30
)

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$JobDir = Join-Path $Root "output\jobs\$Slug"
$ExportDir = Join-Path $Root "output\export\$Slug"
New-Item -ItemType Directory -Force -Path $JobDir, $ExportDir | Out-Null

function Get-RemoteStatus {
    $bash = @"
cd '$RemoteRoot' || exit 1
PHASE=export
pgrep -f 'ABQcaeK.*cae_hex_mesh_pilot' >/dev/null 2>&1 && PHASE=meshing
test -f output/export/$Slug/${Slug}_cae_mesh.inp && PHASE=mesh_done
test -f output/export/$Slug/${Slug}.inp && PHASE=export_done
test -f output/jobs/$Slug/${Slug}.lck && PHASE=solving
grep -q 'COMPLETED SUCCESSFULLY' output/jobs/$Slug/${Slug}.sta 2>/dev/null && PHASE=done
grep -qE 'NOT BEEN COMPLETED|exited with errors' output/jobs/$Slug/${Slug}.sta 2>/dev/null && PHASE=failed
CAE_ET=`$(ps -o etime= -C ABQcaeK 2>/dev/null | head -1 | xargs)
CAE_CPU=`$(ps -o pcpu= -C ABQcaeK 2>/dev/null | head -1 | xargs)
PILOT=`$(tail -n 1 output/export/$Slug/cae_hex_pilot.log 2>/dev/null)
MESH_MB=`$(du -m output/export/$Slug/${Slug}_cae_mesh.inp 2>/dev/null | cut -f1)
INP_MB=`$(du -m output/export/$Slug/${Slug}.inp 2>/dev/null | cut -f1)
STA=`$(tail -n 1 output/jobs/$Slug/${Slug}.sta 2>/dev/null)
echo PHASE=`$PHASE
echo CAE_ET=`$CAE_ET
echo CAE_CPU=`$CAE_CPU
echo PILOT=`$PILOT
echo MESH_MB=`$MESH_MB
echo INP_MB=`$INP_MB
echo STA=`$STA
"@
    ssh -o BatchMode=yes $RemoteHost $bash 2>$null
}

Write-Host "=== $Slug pipeline watcher ===" -ForegroundColor Cyan
Write-Host "  remote: ${RemoteHost}:${RemoteRoot}"
Write-Host "  poll=${PollSeconds}s"
Write-Host ""

while ($true) {
    $now = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
    $lines = @(Get-RemoteStatus)

    $phase = "unknown"
    $caeEt = ""
    $caeCpu = ""
    $pilot = ""
    $meshMb = ""
    $inpMb = ""
    $sta = ""
    foreach ($line in $lines) {
        if ($line -match '^PHASE=(.+)$') { $phase = $Matches[1].Trim() }
        elseif ($line -match '^CAE_ET=(.*)$') { $caeEt = $Matches[1].Trim() }
        elseif ($line -match '^CAE_CPU=(.*)$') { $caeCpu = $Matches[1].Trim() }
        elseif ($line -match '^PILOT=(.*)$') { $pilot = $Matches[1].Trim() }
        elseif ($line -match '^MESH_MB=(.*)$') { $meshMb = $Matches[1].Trim() }
        elseif ($line -match '^INP_MB=(.*)$') { $inpMb = $Matches[1].Trim() }
        elseif ($line -match '^STA=(.*)$') { $sta = $Matches[1].Trim() }
    }

    scp "${RemoteHost}:${RemoteRoot}/output/jobs/${Slug}/${Slug}.sta" $JobDir 2>$null | Out-Null
    scp "${RemoteHost}:${RemoteRoot}/output/jobs/${Slug}/${Slug}.lck" $JobDir 2>$null | Out-Null
    scp "${RemoteHost}:${RemoteRoot}/output/export/${Slug}/${Slug}_meta.json" $ExportDir 2>$null | Out-Null

    $color = switch ($phase) {
        'done' { 'Green' }
        'failed' { 'Red' }
        'solving' { 'Yellow' }
        'meshing' { 'Cyan' }
        default { 'Gray' }
    }

    Write-Host "[$now] phase=$phase" -ForegroundColor $color
    if ($caeEt) { Write-Host "  CAE: elapsed=$caeEt  CPU=${caeCpu}%" }
    if ($pilot) { Write-Host "  pilot: $pilot" }
    if ($meshMb) { Write-Host "  cae_mesh.inp: ${meshMb} MB" }
    if ($inpMb) { Write-Host "  compression.inp: ${inpMb} MB" }
    if ($sta) { Write-Host "  sta: $sta" }
    Write-Host ""

    if ($phase -in @('done', 'failed')) { break }
    Start-Sleep -Seconds $PollSeconds
}

Write-Host "=== watcher finished phase=$phase ===" -ForegroundColor Cyan
