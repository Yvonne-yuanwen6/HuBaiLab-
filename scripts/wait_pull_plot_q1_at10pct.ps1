# Wait until Q1 running job reaches ~10% engineering strain, then server readOnly extract + plot.
param(
    [string]$Server = "art@172.20.200.93",
    [string]$Remote = "/media/art/file/XiangLang/Lattice/LWY/HuBaiLab",
    [string]$Local = "D:\HuBaiLab",
    [string]$VariantSuffix = "paperbox_settle5p",
    [double]$TargetStrain = 0.10,
    [double]$StepTimeS = 768.0,
    [double]$TotalStrain = 0.80,
    [int]$PollSeconds = 60
)

$ErrorActionPreference = "Stop"
$Tag = "sfbls_af2q1"
$BaseSuffix = "cae_tet0p6mm80_5mmin_paperbox"
$Slug = "hu_bai_${Tag}_L20_4x4x4_solid_cad_f_${BaseSuffix}_${VariantSuffix}"
$BaselineSlug = "hu_bai_${Tag}_L20_4x4x4_solid_cad_f_${BaseSuffix}"

$Log = Join-Path $Local "output\logs\q1_${VariantSuffix}_wait10pct.log"
$RemoteLiveCsv = "$Remote/output/post/$Slug/${Slug}_stress_strain_live.csv"
$LocalPost = Join-Path $Local "output\post\$Slug"
$LocalCsv = Join-Path $LocalPost "${Slug}_stress_strain_live.csv"
$LocalPng = Join-Path $Local "output\reports\q1_${VariantSuffix}_partial10_stress_strain.png"

function Log([string]$Msg) {
    $line = "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] $Msg"
    Write-Host $line
    $line | Out-File -FilePath $Log -Append -Encoding utf8
}

function Get-SimSFromSta([string]$StaPath) {
    $simS = 0.0
    if (-not (Test-Path $StaPath)) { return $simS }
    foreach ($line in (Get-Content $StaPath -Tail 60 -ErrorAction SilentlyContinue)) {
        if ($line -match '^\s+\d+\s+[\d.E+-]+\s+([\d.E+-]+)\s+\d\d:\d\d:\d\d') {
            $v = [double]$Matches[1]
            if ($v -gt $simS) { $simS = $v }
        }
        if ($line -match 'at step time\s+([\d.E+-]+)') {
            $v = [double]$Matches[1]
            if ($v -gt $simS) { $simS = $v }
        }
    }
    return $simS
}

function Get-MaxStrainFromCsv([string]$CsvPath) {
    if (-not (Test-Path $CsvPath)) { return 0.0 }
    $max = 0.0
    Import-Csv $CsvPath | ForEach-Object {
        $e = [double]$_.engineering_strain
        if ($e -gt $max) { $max = $e }
    }
    return $max
}

Log "wait Q1 variant=$VariantSuffix slug=$Slug for strain>=$TargetStrain (readOnly server extract)"

$minSimS = [math]::Max(80, $TargetStrain * $StepTimeS / $TotalStrain)

while ($true) {
    $jobDir = Join-Path $Local "output\jobs\$Slug"
    New-Item -ItemType Directory -Force -Path $jobDir | Out-Null
    scp "${Server}:${Remote}/output/jobs/$Slug/$Slug.sta" (Join-Path $jobDir "$Slug.sta") 2>$null | Out-Null

    $simS = Get-SimSFromSta (Join-Path $jobDir "$Slug.sta")
    $lck = (ssh $Server "test -f '$Remote/output/jobs/$Slug/$Slug.lck' && echo 1 || echo 0").Trim()
    $odb = (ssh $Server "test -s '$Remote/output/jobs/$Slug/$Slug.odb' && echo 1 || echo 0").Trim()
    $estrEst = if ($StepTimeS -gt 0) { $TotalStrain * $simS / $StepTimeS } else { 0 }
    $settleHoldS = 0.05 * $StepTimeS * 2
    $loadingSimS = [math]::Max(0, $simS - $settleHoldS)
    $loadingStrainEst = if ($StepTimeS -gt 0) { $TotalStrain * $loadingSimS / $StepTimeS } else { 0 }

    $maxStrain = 0.0
    if ($simS -ge $minSimS -and $odb -eq "1") {
        $extractSh = @"
cd '$Remote' && export PATH=`$HOME/APP/abaqus2022/Commands:`$PATH && \
mkdir -p output/post/$Slug && \
abq python scripts/extract_live_odb_server_py2.py \
  output/jobs/$Slug/$Slug.odb \
  output/export/$Slug/${Slug}_meta.json \
  output/post/$Slug/${Slug}_stress_strain_live.csv && \
test -f output/jobs/$Slug/$Slug.lck && echo JOB_STILL_RUNNING
"@
        ssh $Server $extractSh 2>&1 | Tee-Object -FilePath $Log -Append | Out-Null
        scp "${Server}:${RemoteLiveCsv}" $LocalCsv 2>$null | Out-Null
        $maxStrain = Get-MaxStrainFromCsv $LocalCsv
    }

    Log ("simS={0:F1}s loading_est~{1:P1} curve_max={2:F4} lck={3} odb={4}" -f $simS, $loadingStrainEst, $maxStrain, $lck, $odb)

    if ($maxStrain -ge ($TargetStrain - 0.005) -or ($loadingStrainEst -ge ($TargetStrain - 0.01) -and $maxStrain -ge 0.005)) {
        Log "target strain reached (curve max=$maxStrain)"
        break
    }
    if ($lck -ne "1" -and $simS -gt 10) {
        Log "job stopped before 10% strain"
        exit 1
    }
    Start-Sleep -Seconds $PollSeconds
}

# baseline partial at same sim time for overlay
$baselinePartial = "$Remote/output/post/$BaselineSlug/${BaselineSlug}_stress_strain_partial.csv"
ssh $Server @"
cd '$Remote' && export PATH=`$HOME/APP/abaqus2022/Commands:`$PATH && \
mkdir -p output/post/$BaselineSlug && \
SIMT=`$(grep -E '^[[:space:]]+[0-9]+' output/jobs/$Slug/$Slug.sta | tail -1 | awk '{print `$3}') && \
abq python scripts/extract_live_odb_server_py2.py \
  output/jobs/$BaselineSlug/$BaselineSlug.odb \
  output/export/$BaselineSlug/${BaselineSlug}_meta.json \
  output/post/$BaselineSlug/${BaselineSlug}_stress_strain_partial.csv `$SIMT
"@ 2>&1 | Tee-Object -FilePath $Log -Append | Out-Null

$LocalBaselineCsv = Join-Path $Local "output\post\$BaselineSlug\${BaselineSlug}_stress_strain_partial.csv"
New-Item -ItemType Directory -Force -Path (Split-Path $LocalBaselineCsv), $LocalPost, (Split-Path $LocalPng) | Out-Null
scp "${Server}:${RemoteLiveCsv}" $LocalCsv
scp "${Server}:${baselinePartial}" $LocalBaselineCsv 2>$null | Out-Null

Log "plot -> $LocalPng"
py -3 -c @"
import csv, os, sys
sys.path.insert(0, r'$Local')
from scripts.plot_stress_strain import load_csv
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

fig, ax = plt.subplots(figsize=(9, 5.5))
for path, label, color in (
    (r'$LocalBaselineCsv', 'Q1 baseline settle15% (same sim time)', '#F48FB1'),
    (r'$LocalCsv', 'Q1 $VariantSuffix live readOnly', '#1565C0'),
):
    if os.path.isfile(path):
        s, st = load_csv(path)
        if s:
            ax.plot(s, st, color=color, lw=2, marker='o', ms=4, label=label)
            print(label, len(s), 'pts', f'last eps={s[-1]:.4f} sig={st[-1]:.4f}')
ax.axvline($TargetStrain, color='gray', ls=':', alpha=0.6, label='target 10% strain')
ax.set_xlabel('Engineering strain')
ax.set_ylabel('Engineering stress (MPa)')
ax.set_title('Q1 $VariantSuffix partial @ ~10% strain (readOnly ODB, job uninterrupted)')
ax.grid(True, alpha=0.35)
ax.legend(fontsize=9)
fig.tight_layout()
os.makedirs(os.path.dirname(r'$LocalPng'), exist_ok=True)
fig.savefig(r'$LocalPng', dpi=150)
print('Saved:', r'$LocalPng')
"@

Log "done"
