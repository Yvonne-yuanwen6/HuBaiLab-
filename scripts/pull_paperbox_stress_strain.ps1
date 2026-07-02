# Pull paperbox stress-strain CSVs from art workstation (no ODB).
param(
    [string]$Server = "art@172.20.200.93",
    [string]$Remote = "/media/art/file/XiangLang/Lattice/LWY/HuBaiLab",
    [string]$Local = (Split-Path $PSScriptRoot -Parent)
)

$Slugs = @(
    "hu_bai_bcc_af2q0_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox",
    "hu_bai_sfbls_af2q0p5_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox",
    "hu_bai_sfbls_af2q0p5_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox_paperbox_nosettle",
    "hu_bai_sfbls_af2q0p5_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox_paperbox_settle5p",
    "hu_bai_sfbls_af2q1_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox",
    "hu_bai_sfbls_af2q1_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox_paperbox_settle5p",
    "hu_bai_sfbls_af2q1p5_L20_4x4x4_solid_cad_f_cae_tet0p6mm80_5mmin_paperbox"
)

$n = 0
foreach ($s in $Slugs) {
    $postDir = Join-Path $Local "output\post\$s"
    New-Item -ItemType Directory -Force -Path $postDir | Out-Null
    $remoteCsv = "${Remote}/output/post/${s}/${s}_stress_strain.csv"
    $localCsv = Join-Path $postDir "${s}_stress_strain.csv"
    Write-Host "scp $s ..." -ForegroundColor Cyan
    scp "${Server}:${remoteCsv}" $localCsv
    if ($LASTEXITCODE -eq 0 -and (Test-Path $localCsv)) {
        $n++
    } else {
        Write-Host "[WARN] missing on server: $s" -ForegroundColor Yellow
    }
}
Write-Host "Pulled $n / $($Slugs.Count) CSVs -> output/post/" -ForegroundColor Green
