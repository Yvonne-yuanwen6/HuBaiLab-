# Monitor param-batch CAE sim on remote (same style as STEP batch monitor).
# Usage:
#   powershell -File scripts/watch_param_batch_cae_sim.ps1
#   powershell -File scripts/watch_param_batch_cae_sim.ps1 -IntervalSec 30
param(
    [int]$IntervalSec = 30
)

$ErrorActionPreference = "Continue"
. (Join-Path $PSScriptRoot "remote_config.ps1")

$Remote = $HuBaiRemoteHost
$Root = $HuBaiRemoteRoot

Write-Host "SSH monitor: $Remote  INTERVAL=$IntervalSec  (Ctrl+C to stop)" -ForegroundColor Cyan
# Prefer /tmp/_mon.sh when NFS scripts/ is stalled by large ODBs under jobs/.
# -t allocates a TTY so clear / cursor hide work like the STEP batch monitor
$remoteCmd = @"
INTERVAL=$IntervalSec
if [ -f /tmp/_mon.sh ]; then
  bash /tmp/_mon.sh
elif [ -f $Root/scripts/linux/_tmp_monitor_param_batch_cae_sim.sh ]; then
  bash $Root/scripts/linux/_tmp_monitor_param_batch_cae_sim.sh
else
  echo 'monitor script missing' >&2
  exit 1
fi
"@
ssh -t -o BatchMode=yes -o ConnectTimeout=15 $Remote $remoteCmd
