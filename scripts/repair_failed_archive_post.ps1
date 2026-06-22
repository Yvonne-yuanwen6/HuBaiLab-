# Re-extract stress-strain into output/failed/{slug}/{archive}/post from archived ODB.
param(
    [string]$Slug = 'hu_bai_sfbls_af2q1_L20_4x4x4_solid_cad_f_fast80',
    [string]$ArchivePath = '',
    [string]$MetaPath = '',
    [switch]$All
)

$ErrorActionPreference = 'Stop'
$ScriptDir = $PSScriptRoot
. (Join-Path $ScriptDir 'submit_helpers.ps1')
$Root = (Resolve-Path (Join-Path $ScriptDir '..')).Path

function Repair-OneArchive {
    param([string]$Path, [string]$MetaOverride)
    Write-Host "Repair post: $Path" -ForegroundColor Cyan
    $result = Repair-FailedArchivePost -Root $Root -ArchiveRoot $Path -MetaPath $MetaOverride
    Write-Host "  CSV: $($result.Csv)" -ForegroundColor Green
    if ($result.Png) { Write-Host "  PNG: $($result.Png)" -ForegroundColor Green }
}

if ($ArchivePath) {
    Repair-OneArchive -Path (Resolve-Path $ArchivePath).Path -MetaOverride $MetaPath
    exit 0
}

$failedRoot = Join-Path $Root "output\failed\$Slug"
if (-not (Test-Path $failedRoot)) {
    Write-Host "[ERROR] Not found: $failedRoot" -ForegroundColor Red
    exit 1
}

$archives = @(Get-ChildItem -Path $failedRoot -Directory | Sort-Object Name)
if (-not $All) {
    $archives = @($archives | Where-Object {
        Test-Path (Join-Path $_.FullName 'jobs\*.odb')
    } | Select-Object -Last 1)
    if ($archives.Count -eq 0) {
        Write-Host "[ERROR] No archive with ODB under $failedRoot" -ForegroundColor Red
        exit 1
    }
    Write-Host "Latest ODB archive only (use -All for every archive)." -ForegroundColor Yellow
}

$fail = 0
foreach ($arch in $archives) {
    $odb = Get-ChildItem (Join-Path $arch.FullName 'jobs') -Filter '*.odb' -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if (-not $odb) {
        Write-Host "Skip (no ODB): $($arch.Name)" -ForegroundColor DarkYellow
        continue
    }
    try {
        Repair-OneArchive -Path $arch.FullName -MetaOverride $MetaPath
    } catch {
        Write-Host "[ERROR] $($arch.Name): $_" -ForegroundColor Red
        $fail++
    }
}
exit $(if ($fail -gt 0) { 1 } else { 0 })
