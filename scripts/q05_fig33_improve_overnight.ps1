# Overnight: sync, start server supervisor, poll/pull/eval/plot until morning report ready.
param(
    [int]$PollSeconds = 300,
    [int]$MaxHours = 14
)

$ErrorActionPreference = "Continue"
. (Join-Path $PSScriptRoot "remote_config.ps1")

$LocalRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Base = "hu_bai_sfbls_af2q0p5_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox"
$Variants = @("fig33_v2_paper", "fig33_v2_ep", "paperbox_settle5p", "fig33_v2_paper_dt1e4")
$AllSlugs = @("${Base}_fig33_v2_el") + ($Variants | ForEach-Object { "${Base}_$_" })

$Log = Join-Path $LocalRoot "output\logs\q05_fig33_improve_overnight.log"
$ReportJson = Join-Path $LocalRoot "output\logs\q05_fig33_improve_morning_report.json"
$ReportMd = Join-Path $LocalRoot "output\reports\fig33_v2_improve\morning_report.md"
$ReadyRemote = "$HuBaiRemoteRoot/output/logs/q05_fig33_improve_ready.json"
$ReadyLocal = Join-Path $LocalRoot "output\logs\q05_fig33_improve_ready.json"
$StepTimeS = 768.0

function Log([string]$Msg) {
    $line = "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] $Msg"
    Write-Host $line
    Add-Content -Path $Log -Value $line -ErrorAction SilentlyContinue
}

New-Item -ItemType Directory -Force -Path (Split-Path $Log) | Out-Null
New-Item -ItemType Directory -Force -Path (Split-Path $ReportMd) | Out-Null

Log "=== overnight start poll=${PollSeconds}s maxHours=${MaxHours} ==="

Log "sync scripts+src -> server"
& (Join-Path $PSScriptRoot "sync_to_server.ps1")
if ($LASTEXITCODE -ne 0) { Log "WARN sync exit=$LASTEXITCODE" }

Log "start server supervisor (48c improve sweep)"
$startCmd = @"
cd '$HuBaiRemoteRoot' && \
mkdir -p output/logs && \
chmod +x scripts/linux/paperbox_q05_fig33_improve_supervise.sh scripts/linux/run_paperbox_q05_fig33_improve.sh && \
pgrep -af paperbox_q05_fig33_improve_supervise || \
nohup bash scripts/linux/paperbox_q05_fig33_improve_supervise.sh >> output/logs/paperbox_q05_fig33_improve_supervise.log 2>&1 &
"@
ssh $HuBaiRemoteHost $startCmd
Log "supervisor launch sent"

$deadline = (Get-Date).AddHours($MaxHours)
$cycle = 0

while ((Get-Date) -lt $deadline) {
    $cycle++
    Log "--- cycle $cycle ---"

    scp "${HuBaiRemoteHost}:${ReadyRemote}" $ReadyLocal 2>$null | Out-Null
    scp "${HuBaiRemoteHost}:${HuBaiRemoteRoot}/output/logs/paperbox_q05_fig33_improve_supervise.log" `
        (Join-Path $LocalRoot "output\logs\paperbox_q05_fig33_improve_supervise.log") 2>$null | Out-Null

    foreach ($slug in $AllSlugs) {
        $jobDir = Join-Path $LocalRoot "output\jobs\$slug"
        New-Item -ItemType Directory -Force -Path $jobDir | Out-Null
        scp "${HuBaiRemoteHost}:${HuBaiRemoteRoot}/output/jobs/$slug/${slug}.sta" $jobDir 2>$null | Out-Null
        scp "${HuBaiRemoteHost}:${HuBaiRemoteRoot}/output/jobs/$slug/${slug}.lck" $jobDir 2>$null | Out-Null

        $postDir = Join-Path $LocalRoot "output\post\$slug"
        New-Item -ItemType Directory -Force -Path $postDir | Out-Null
        scp "${HuBaiRemoteHost}:${HuBaiRemoteRoot}/output/post/$slug/${slug}_stress_strain.csv" $postDir 2>$null | Out-Null
        scp "${HuBaiRemoteHost}:${HuBaiRemoteRoot}/output/post/$slug/${slug}_stress_strain_partial.csv" $postDir 2>$null | Out-Null

        $evalRemote = "$HuBaiRemoteRoot/output/logs/eval_q05_*.json"
        scp "${HuBaiRemoteHost}:${HuBaiRemoteRoot}/output/logs/eval_q05_*.json" `
            (Join-Path $LocalRoot "output\logs\") 2>$null | Out-Null
    }

    foreach ($v in $Variants) {
        $slug = "${Base}_$v"
        $sta = Join-Path $LocalRoot "output\jobs\$slug\$slug.sta"
        $st = "WAIT"
        if ((Test-Path $sta) -and (Select-String -Path $sta -Pattern 'COMPLETED SUCCESSFULLY' -Quiet)) { $st = "DONE" }
        elseif (Test-Path (Join-Path $LocalRoot "output\jobs\$slug\$slug.lck")) { $st = "RUN" }
        elseif (Test-Path $sta) { $st = "STOP" }
        Log "  $v : $st"
    }

    py -3 (Join-Path $LocalRoot "scripts\plot_q05_fig33_improve_compare.py") `
        --per-variant `
        --png (Join-Path $LocalRoot "output\reports\fig33_v2_improve\af2q05_exp_vs_sim_all.png") `
        --write-summary-json (Join-Path $LocalRoot "output\logs\q05_fig33_improve_plot_summary.json") 2>$null

    if ((Test-Path $ReadyLocal) -and (Get-Content $ReadyLocal -Raw | Select-String '"all_ready"\s*:\s*true' -Quiet)) {
        Log "all_ready=true — finishing"
        break
    }

    Start-Sleep -Seconds $PollSeconds
}

Log "build morning report"
$evalRows = @()
foreach ($v in $Variants) {
    $slug = "${Base}_$v"
    $evalPath = Join-Path $LocalRoot "output\logs\eval_q05_$v.json"
    if (Test-Path $evalPath) {
        $evalRows += Get-Content $evalPath -Raw | ConvertFrom-Json
    } else {
        $csv = Join-Path $LocalRoot "output\post\$slug\${slug}_stress_strain.csv"
        if (Test-Path $csv) {
            py -3 (Join-Path $LocalRoot "scripts\evaluate_paperbox_q05_trend.py") `
                --slug $slug --write-json $evalPath 2>$null | Out-Null
            if (Test-Path $evalPath) { $evalRows += Get-Content $evalPath -Raw | ConvertFrom-Json }
        }
    }
}

$baselineEval = Join-Path $LocalRoot "output\logs\eval_q05_fig33_v2_el.json"
if (-not (Test-Path $baselineEval)) {
    py -3 (Join-Path $LocalRoot "scripts\evaluate_paperbox_q05_trend.py") `
        --slug "${Base}_fig33_v2_el" --write-json $baselineEval 2>$null | Out-Null
}
$baseline = $null
if (Test-Path $baselineEval) { $baseline = Get-Content $baselineEval -Raw | ConvertFrom-Json }

$report = [ordered]@{
    generated_at = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
    baseline_el = $baseline
    variants = $evalRows
    ready_json = if (Test-Path $ReadyLocal) { Get-Content $ReadyLocal -Raw | ConvertFrom-Json } else { $null }
    plots = @(
        "output/reports/fig33_v2_improve/af2q05_exp_vs_sim_all.png"
    )
}
$report | ConvertTo-Json -Depth 8 | Set-Content -Path $ReportJson -Encoding UTF8

$md = @"
# Q0.5 Fig.3.3 Improve Sweep - Morning Report

Generated: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')

## Baseline (fig33_v2_el)

"@

if ($baseline) {
    $md += "- peak: $($baseline.peak_stress_MPa) MPa @ eps=$($baseline.peak_strain)`n"
    $md += "- hard_pass: $($baseline.hard_pass)`n"
    $md += "- reason: $($baseline.reason)`n"
} else {
    $md += "- no eval data`n"
}

$md += @"

## Variants

| variant | peak MPa | eps_peak | snap | hard_pass | reason |
|---------|----------|----------|------|-----------|--------|
"@

foreach ($row in $evalRows) {
    $suffix = ($row.slug -replace [regex]::Escape("${Base}_"), "")
    $snap = if ($row.has_snapthrough) { "Y" } else { "N" }
    $md += "| $suffix | $($row.peak_stress_MPa) | $($row.peak_strain) | $snap | $($row.hard_pass) | $($row.reason) |`n"
}

$md += @"

## Plots

- output/reports/fig33_v2_improve/af2q05_exp_vs_sim_all.png
- per-variant: output/reports/fig33_v2_improve/af2q05_*.png

## Logs

- local: output/logs/q05_fig33_improve_overnight.log
- server orchestrator: output/logs/paperbox_q05_fig33_improve.log
- server supervisor: output/logs/paperbox_q05_fig33_improve_supervise.log
"@

Set-Content -Path $ReportMd -Value $md -Encoding UTF8
Log "=== done report -> $ReportMd ==="
