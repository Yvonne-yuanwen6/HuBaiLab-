# Live monitor: local param_batch Explicit solve (ASCII paths).
#   powershell -File scripts/watch_param_batch_cae_sim_local.ps1
#   powershell -File scripts/watch_param_batch_cae_sim_local.ps1 -IntervalSec 10
param(
    [int]$IntervalSec = 10,
    [string[]]$Cases = @("af2q1_deq2_k1", "af2q1_deq2_k1p5")
)

$ErrorActionPreference = "Continue"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Slug = "cae_tet0p6mm80_5mmin_paperbox"
$SimBatch = "param_batch"
# settle 0.15*768 + compression 768
$TargetTotalS = 883.2

function Get-Bar([double]$frac, [int]$width = 28) {
    if ($frac -lt 0) { $frac = 0 }
    if ($frac -gt 1) { $frac = 1 }
    $n = [int][math]::Round($frac * $width)
    return ("[{0}{1}] {2,3}%" -f ("#" * $n), ("-" * ($width - $n)), [int](100 * $frac))
}

function Get-CaseSnap([string]$cid) {
    $jd = Join-Path $Root "output\jobs\$SimBatch\$cid\$Slug"
    $o = [ordered]@{
        cid = $cid; exists = $false; running = $false; done = $false
        total_t = $null; wall = $null; inc = $null; odb_mb = 0; last = ""
    }
    if (-not (Test-Path -LiteralPath $jd)) { return $o }
    $o.exists = $true
    $o.running = Test-Path -LiteralPath (Join-Path $jd "$Slug.lck")
    $odb = Join-Path $jd "$Slug.odb"
    if (Test-Path -LiteralPath $odb) { $o.odb_mb = [math]::Round((Get-Item -LiteralPath $odb).Length / 1MB, 1) }
    $sta = Join-Path $jd "$Slug.sta"
    if (-not (Test-Path -LiteralPath $sta)) { return $o }
    $lines = Get-Content -LiteralPath $sta -ErrorAction SilentlyContinue
    if (-not $lines) { return $o }
    $o.done = [bool]($lines | Where-Object { $_ -match "THE ANALYSIS HAS COMPLETED SUCCESSFULLY" })
    $prog = $lines | Where-Object { $_ -match '^\s*(\d+)\s+(\S+)\s+(\S+)\s+(\S+)\s+' } | Select-Object -Last 1
    if ($prog -match '^\s*(\d+)\s+(\S+)\s+(\S+)\s+(\S+)\s+') {
        $o.inc = [int]$Matches[1]
        $o.total_t = $Matches[3]
        $o.wall = $Matches[4]
        $o.last = $prog.Trim()
    }
    return $o
}

Write-Host "Local Explicit monitor  sim_batch=$SimBatch  target~${TargetTotalS}s  Ctrl+C stops monitor only" -ForegroundColor Cyan
Write-Host ""

while ($true) {
    Clear-Host
    $now = Get-Date -Format "HH:mm:ss"
    $os = Get-CimInstance Win32_OperatingSystem
    $free = [math]::Round($os.FreePhysicalMemory / 1MB, 1)
    $ex = @(Get-Process -Name explicit -ErrorAction SilentlyContinue)
    $ws = ($ex | Measure-Object WorkingSet64 -Sum).Sum / 1MB
    Write-Host ("===== CAE solve monitor  {0}  batch={1} =====" -f $now, $SimBatch)
    Write-Host ("explicit procs={0}  RSS~{1:N0} MB  RAM free={2} GB" -f $ex.Count, $ws, $free)
    Write-Host ""

    foreach ($cid in $Cases) {
        $s = Get-CaseSnap $cid
        Write-Host ("--- {0} ---" -f $cid)
        if (-not $s.exists) {
            Write-Host "  waiting (no job dir yet)"
            Write-Host ""
            continue
        }
        $status = if ($s.done) { "DONE" } elseif ($s.running) { "RUNNING" } else { "IDLE/STOPPED" }
        $frac = 0.0
        $tot = $null
        if ($s.total_t -and ($s.total_t -as [double]) -ne $null) {
            $tot = [double]$s.total_t
            $frac = [math]::Min(1.0, $tot / $TargetTotalS)
        }
        Write-Host ("  status:  {0}" -f $status)
        Write-Host ("  progress:{0}  TOTAL_TIME={1} / {2}s" -f (Get-Bar $frac), $s.total_t, $TargetTotalS)
        Write-Host ("  wall:    {0}   inc={1}   odb={2} MB" -f $s.wall, $s.inc, $s.odb_mb)
        if ($s.last) { Write-Host ("  sta:     {0}" -f $s.last) }
        if ($s.running -and $tot -and $tot -gt 0.5 -and $s.wall -match '(\d+):(\d+):(\d+)') {
            $wallSec = [int]$Matches[1] * 3600 + [int]$Matches[2] * 60 + [int]$Matches[3]
            if ($wallSec -gt 0) {
                $rate = $tot / $wallSec
                $etaSec = ($TargetTotalS - $tot) / $rate
                $etaH = [math]::Round($etaSec / 3600.0, 1)
                Write-Host ("  ETA:     ~{0} h (rough, from current rate)" -f $etaH)
            }
        }
        Write-Host ""
    }

    $ql = Join-Path $Root "output\logs\param_batch_cae_sim_local.log"
    if (Test-Path -LiteralPath $ql) {
        Write-Host "queue log tail:"
        Get-Content -LiteralPath $ql -Tail 4 | ForEach-Object { Write-Host ("  {0}" -f $_) }
    }
    Start-Sleep -Seconds $IntervalSec
}
