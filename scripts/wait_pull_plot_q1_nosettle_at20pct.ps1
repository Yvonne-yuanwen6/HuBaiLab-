# Wait until Q1 B nosettle reaches ~20% strain, then read-only extract on server + plot.
param(
    [string]$Server = "art@172.20.200.93",
    [string]$Remote = "/media/art/file/XiangLang/Lattice/LWY/HuBaiLab",
    [string]$Local = "D:\HuBaiLab",
    [double]$TargetStrain = 0.20,
    [double]$StepTimeS = 768.0,
    [double]$TotalStrain = 0.80,
    [int]$PollSeconds = 45
)

$ErrorActionPreference = "Stop"
$Slug = "hu_bai_sfbls_af2q1_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox_paperbox_nosettle"
$TargetSimS = $TargetStrain * $StepTimeS / $TotalStrain
$Log = Join-Path $Local "output\logs\q1_nosettle_wait20pct.log"
$RemotePost = "$Remote/output/post/$Slug"
$RemoteCsv = "$RemotePost/${Slug}_stress_strain_partial20.csv"
$LocalPost = Join-Path $Local "output\post\$Slug"
$LocalCsv = Join-Path $LocalPost "${Slug}_stress_strain_partial20.csv"
$LocalPng = Join-Path $Local "output\reports\q1_nosettle_partial20_stress_strain.png"

function Log([string]$Msg) {
    $line = "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] $Msg"
    Write-Host $line
    $line | Out-File -FilePath $Log -Append -Encoding utf8
}

Log "wait for Q1 nosettle simS>=$([math]::Round($TargetSimS,1)) s (~$($TargetStrain*100)% strain)"

while ($true) {
    $staRemote = "$Remote/output/jobs/$Slug/$Slug.sta"
    $jobDir = Join-Path $Local "output\jobs\$Slug"
    New-Item -ItemType Directory -Force -Path $jobDir | Out-Null
    scp "${Server}:${staRemote}" (Join-Path $jobDir "$Slug.sta") 2>$null | Out-Null

    $simS = 0.0
    $staLocal = Join-Path $jobDir "$Slug.sta"
    if (Test-Path $staLocal) {
        foreach ($line in (Get-Content $staLocal -Tail 50 -ErrorAction SilentlyContinue)) {
            if ($line -match '^\s+\d+\s+[\d.E+-]+\s+([\d.E+-]+)\s+\d\d:\d\d:\d\d') {
                $v = [double]$Matches[1]
                if ($v -gt $simS) { $simS = $v }
            }
            if ($line -match 'at step time\s+([\d.E+-]+)') {
                $v = [double]$Matches[1]
                if ($v -gt $simS) { $simS = $v }
            }
        }
    }

    $lck = ssh $Server "test -f '$Remote/output/jobs/$Slug/$Slug.lck' && echo 1 || echo 0"
    $odb = ssh $Server "test -s '$Remote/output/jobs/$Slug/$Slug.odb' && echo 1 || echo 0"
    $estr = if ($StepTimeS -gt 0) { $TotalStrain * $simS / $StepTimeS } else { 0 }
    Log ("simS={0:F1}/{1} s  strain~{2:P1}  lck={3}  odb={4}" -f $simS, $TargetSimS, $estr, $lck.Trim(), $odb.Trim())

    if ($simS -ge ($TargetSimS - 5) -and $odb.Trim() -eq "1") { break }
    if ($lck.Trim() -ne "1" -and $simS -gt 0) {
        Log "job stopped before 20%; abort partial pull"
        exit 1
    }
    Start-Sleep -Seconds $PollSeconds
}

Log "extract on server (readOnly ODB, no job interrupt)"
$extractCmd = @"
cd '$Remote' && export PATH=`$HOME/APP/abaqus2022/Commands:`$PATH && export PYTHONPATH=. && \
mkdir -p output/post/$Slug && \
abaqus python scripts/extract_stress_strain_from_odb.py \
  --odb output/jobs/$Slug/$Slug.odb \
  --meta output/export/$Slug/${Slug}_meta.json \
  --csv output/post/$Slug/${Slug}_stress_strain_partial20.csv \
  --raw-csv output/post/$Slug/${Slug}_stress_strain_partial20_raw.csv \
  --force-mode paper --curve-method paper
"@
ssh $Server $extractCmd 2>&1 | Tee-Object -FilePath $Log -Append

New-Item -ItemType Directory -Force -Path $LocalPost, (Split-Path $LocalPng) | Out-Null
Log "scp partial CSV"
scp "${Server}:${RemoteCsv}" $LocalCsv

Log "plot"
py -3 -c @"
import csv, os, sys
sys.path.insert(0, r'$Local')
from scripts.plot_stress_strain import load_csv
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
csv_path = r'$LocalCsv'
png_path = r'$LocalPng'
strains, stresses = load_csv(csv_path)
fig, ax = plt.subplots(figsize=(8, 5))
ax.plot(strains, stresses, color='#F48FB1', lw=1.8, label='Q1.0 B nosettle (partial ODB)')
if strains:
    ax.axvline($TargetStrain, color='gray', ls=':', alpha=0.7, label=f'target ~$TargetStrain strain')
ax.set_xlabel('Engineering strain')
ax.set_ylabel('Engineering stress (MPa)')
ax.set_title('SFBLS Q=1.0 paper_box nosettle — partial curve @ ~20% strain (job still running)')
ax.grid(True, alpha=0.35)
ax.legend(fontsize=9)
fig.tight_layout()
os.makedirs(os.path.dirname(png_path), exist_ok=True)
fig.savefig(png_path, dpi=150)
print('Saved:', png_path)
if strains:
    print(f'Points: {len(strains)}  last strain={strains[-1]:.4f} stress={stresses[-1]:.4f} MPa')
"@

Log "done -> $LocalPng"
