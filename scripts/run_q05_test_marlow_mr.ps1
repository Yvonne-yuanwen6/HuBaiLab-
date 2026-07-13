# Sync, launch Q=0.5 test_marlow + test_MR on server (parallel), wait, pull CSVs, overlay plot.
param(
    [switch]$LaunchOnly,
    [switch]$PullPlotOnly,
    [int]$PollSeconds = 180
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "remote_config.ps1")

$LocalRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Remote = $HuBaiRemoteRoot
$Server = $HuBaiRemoteHost
$RunSh = "scripts/linux/run_q05_test_marlow_mr_parallel.sh"
$LogLocal = Join-Path $LocalRoot "output\logs\q05_test_marlow_mr_local.log"
$ReadyRemote = "$Remote/output/logs/q05_test_marlow_mr_ready.json"
$ReadyLocal = Join-Path $LocalRoot "output\logs\q05_test_marlow_mr_ready.json"

$Slugs = @(
    "hu_bai_sfbls_af2q0p5_L20_4x4x4_solid_cad_f_test_marlow",
    "hu_bai_sfbls_af2q0p5_L20_4x4x4_solid_cad_f_test_MR"
)

function Log([string]$Msg) {
    $line = "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] $Msg"
    Write-Host $line
    New-Item -ItemType Directory -Force -Path (Split-Path $LogLocal) | Out-Null
    Add-Content -Path $LogLocal -Value $line
}

if (-not $PullPlotOnly) {
    Log "=== sync scripts/src + Fig.2.5 ==="
    & (Join-Path $PSScriptRoot "sync_to_server.ps1")
    scp (Join-Path $LocalRoot "data\hu_bai_tpu_fig25_tensile_traced.json") "${Server}:${Remote}/data/"
    ssh $Server "chmod +x '$Remote/$RunSh'"

    Log "=== launch Q05 parallel pipeline on server (background) ==="
    $cmd = "cd '$Remote' && nohup bash $RunSh >> output/logs/q05_test_marlow_mr_parallel.log 2>&1 & echo LAUNCHED"
    ssh $Server $cmd
    if ($LaunchOnly) {
        Log "LaunchOnly — monitor: ssh $Server tail -f $Remote/output/logs/q05_test_marlow_mr_parallel.log"
        exit 0
    }
}

Log "=== wait for server all_ready (poll ${PollSeconds}s) ==="
while ($true) {
    scp "${Server}:${ReadyRemote}" $ReadyLocal 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0 -and (Test-Path $ReadyLocal)) {
        $ready = Get-Content $ReadyLocal -Raw | ConvertFrom-Json
        if ($ready.all_ready) {
            Log "all_ready=true"
            break
        }
        $pending = @($ready.cases | Where-Object { -not ($_.completed -and $_.csv_ready) } | ForEach-Object { $_.slug })
        Log "waiting: $($pending -join ', ')"
    } else {
        Log "ready.json not ready yet..."
    }
    Start-Sleep -Seconds $PollSeconds
}

Log "=== pull CSVs ==="
$n = 0
foreach ($s in $Slugs) {
    $postDir = Join-Path $LocalRoot "output\post\$s"
    New-Item -ItemType Directory -Force -Path $postDir | Out-Null
    $remoteCsv = "${Remote}/output/post/${s}/${s}_stress_strain.csv"
    $localCsv = Join-Path $postDir "${s}_stress_strain.csv"
    scp "${Server}:${remoteCsv}" $localCsv
    if ($LASTEXITCODE -eq 0 -and (Test-Path $localCsv)) { $n++ }
}
Log "pulled $n / $($Slugs.Count) CSVs"

Log "=== overlay plot ==="
py -3 (Join-Path $LocalRoot "scripts\plot_q05_test_marlow_mr.py")
Log "=== done ==="
