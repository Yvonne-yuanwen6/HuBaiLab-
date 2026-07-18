# Monitor param-batch COMSOL on remote (same style as STEP batch monitor).
# Usage:
#   powershell -File scripts/watch_param_batch_comsol.ps1
#   powershell -File scripts/watch_param_batch_comsol.ps1 -IntervalSec 8
param(
    [int]$IntervalSec = 8
)

$ErrorActionPreference = "Continue"
. (Join-Path $PSScriptRoot "remote_config.ps1")

$Remote = $HuBaiRemoteHost
$Root = $HuBaiRemoteRoot
$Script = "$Root/scripts/linux/_tmp_monitor_param_batch_comsol.sh"

Write-Host "SSH monitor: $Remote  INTERVAL=$IntervalSec  (Ctrl+C to stop)" -ForegroundColor Cyan
# -t allocates a TTY so clear / cursor hide work like the STEP batch monitor
ssh -t -o BatchMode=yes -o ConnectTimeout=15 $Remote "INTERVAL=$IntervalSec bash $Script"
