# Copy Fig.3.3 best-match ODBs into output/best/ (curated archive).
param(
    [string]$Local = (Split-Path $PSScriptRoot -Parent),
    [string]$Manifest = "",
    [switch]$FromServer,
    [switch]$Force
)

. (Join-Path $PSScriptRoot "remote_config.ps1")

$ErrorActionPreference = "Stop"
if (-not $Manifest) {
    $Manifest = Join-Path $Local "output\reports\fig33_best_exp_vs_sim_all.json"
}
$Dest = Join-Path $Local "output\best"
New-Item -ItemType Directory -Force -Path $Dest | Out-Null
Copy-Item $Manifest (Join-Path $Dest "manifest.json") -Force

$data = Get-Content $Manifest -Raw | ConvertFrom-Json
$slugs = @($data.picked | ForEach-Object { $_.slug })
Write-Host "Best ODB archive -> $Dest"
Write-Host "Cases: $($slugs.Count)"

foreach ($s in $slugs) {
    $odbName = "$s.odb"
    $destOdb = Join-Path $Dest $odbName
    if (-not $Force -and (Test-Path $destOdb) -and ((Get-Item $destOdb).Length -gt 1GB)) {
        Write-Host "[skip] $odbName already present ($([math]::Round((Get-Item $destOdb).Length/1GB,2)) GB)"
        continue
    }

    $localJobOdb = Join-Path $Local "output\jobs\$s\$odbName"
    if ((Test-Path $localJobOdb) -and ((Get-Item $localJobOdb).Length -gt 1GB)) {
        Write-Host "[copy] local jobs -> best: $odbName"
        Copy-Item $localJobOdb $destOdb -Force
        continue
    }

    if ($FromServer -or -not (Test-Path $localJobOdb)) {
        Write-Host "[scp] $($HuBaiRemoteHost):$HuBaiRemoteRoot/output/jobs/$s/$odbName"
        scp "${HuBaiRemoteHost}:${HuBaiRemoteRoot}/output/jobs/${s}/${odbName}" $Dest
        if ($LASTEXITCODE -ne 0) { throw "scp failed for $s" }
    }
}

Write-Host "Done. ODBs in $Dest"
