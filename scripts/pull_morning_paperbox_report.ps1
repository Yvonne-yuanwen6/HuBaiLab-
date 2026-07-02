# Pull latest morning report from server to local output/logs/
param(
    [string]$Server = "art@172.20.200.93",
    [string]$Remote = "/media/art/file/XiangLang/Lattice/LWY/HuBaiLab"
)
$Local = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
if (-not (Test-Path "$Local\output")) { $Local = "D:\HuBaiLab" }
New-Item -ItemType Directory -Force -Path "$Local\output\logs" | Out-Null
scp "${Server}:${Remote}/output/logs/paperbox_morning_report.txt" "$Local\output\logs\"
scp "${Server}:${Remote}/output/logs/paperbox_progress_snapshot.txt" "$Local\output\logs\" 2>$null
Get-Content "$Local\output\logs\paperbox_morning_report.txt"
