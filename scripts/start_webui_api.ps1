# Start HuBaiLab Web UI API (FastAPI on :8000)
. (Join-Path $PSScriptRoot "local_config.ps1")
$Root = $HuBaiProjectRoot
Set-Location $Root

Write-Host "Stopping old API on port 8000..."
Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue |
    Select-Object -ExpandProperty OwningProcess -Unique |
    ForEach-Object {
        if ($_) {
            Write-Host "  Stop-Process -Id $_"
            Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue
        }
    }

# Also stop stray uvicorn workers
Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -match "uvicorn api\.main:app" } |
    ForEach-Object {
        Write-Host "  Stop uvicorn PID $($_.ProcessId)"
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }

Start-Sleep -Seconds 2

$still = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
if ($still) {
    Write-Host "WARNING: port 8000 still in use. Close other terminals or reboot, then retry." -ForegroundColor Yellow
    $still | Format-Table OwningProcess -AutoSize
}

$env:PYTHONPATH = $Root
Write-Host ""
Write-Host "Starting API: http://127.0.0.1:8000" -ForegroundColor Cyan
Write-Host "Docs:       http://127.0.0.1:8000/docs"
Write-Host "Health:     Invoke-RestMethod http://127.0.0.1:8000/api/health"
Write-Host "(should show features: sync-output ...)" -ForegroundColor Gray
Write-Host ""
python -m uvicorn api.main:app --reload --port 8000
