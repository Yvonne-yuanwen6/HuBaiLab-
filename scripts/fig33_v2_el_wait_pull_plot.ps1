# Wait for server fig33_v2_el jobs, pull CSVs, plot Fig.3.3 overlays (no densification markers).
param(
    [string]$Server = "art@172.20.200.93",
    [string]$Remote = "/media/art/file/XiangLang/Lattice/LWY/HuBaiLab",
    [string]$Local = (Split-Path $PSScriptRoot -Parent),
    [int]$PollSeconds = 300
)

$Log = Join-Path $Local "output\logs\fig33_v2_el_local_pull_plot.log"
$ReadyRemote = "$Remote/output/logs/fig33_v2_el_ready.json"
$ReadyLocal = Join-Path $Local "output\logs\fig33_v2_el_ready.json"

function Log([string]$Msg) {
    $line = "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] $Msg"
    Write-Host $line
    Add-Content -Path $Log -Value $line
}

New-Item -ItemType Directory -Force -Path (Split-Path $Log) | Out-Null
Log "=== fig33_v2_el wait/pull/plot start poll=${PollSeconds}s ==="

while ($true) {
    scp "${Server}:${ReadyRemote}" $ReadyLocal 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0 -and (Test-Path $ReadyLocal)) {
        $ready = Get-Content $ReadyLocal -Raw | ConvertFrom-Json
        if ($ready.all_ready) {
            Log "server all_ready=true"
            break
        }
        $pending = @($ready.structures | Where-Object { -not $_.csv_ready } | ForEach-Object { $_.key })
        Log "waiting: $($pending -join ', ')"
    } else {
        Log "ready.json not on server yet; waiting..."
    }
    Start-Sleep -Seconds $PollSeconds
}

$slugs = @(
    "hu_bai_bcc_af2q0_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox_fig33_v2_el",
    "hu_bai_sfbls_af2q0p5_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox_fig33_v2_el",
    "hu_bai_sfbls_af2q1_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox_fig33_v2_el",
    "hu_bai_sfbls_af2q1p5_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox_q15_v2_el"
)

$n = 0
foreach ($s in $slugs) {
    $postDir = Join-Path $Local "output\post\$s"
    New-Item -ItemType Directory -Force -Path $postDir | Out-Null
    $remoteCsv = "${Remote}/output/post/${s}/${s}_stress_strain.csv"
    $localCsv = Join-Path $postDir "${s}_stress_strain.csv"
    Log "scp $s"
    scp "${Server}:${remoteCsv}" $localCsv
    if ($LASTEXITCODE -eq 0 -and (Test-Path $localCsv)) { $n++ }
}

Log "pulled $n / $($slugs.Count) CSVs"

Log "plot combined + per-structure"
py -3 (Join-Path $Local "scripts\plot_fig33_v2_el_overlay.py") --per-structure `
    --png (Join-Path $Local "output\reports\fig33_v2_el_exp_vs_sim_all.png")
if ($LASTEXITCODE -ne 0) {
    Log "ERROR plot failed exit=$LASTEXITCODE"
    exit 1
}

Log "=== done -> output/reports/fig33_v2_el_exp_vs_sim_all.png ==="
