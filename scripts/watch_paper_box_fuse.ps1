# Monitor server-side paper box auto-fuse (safe runner).
param(
    [string]$RemoteHost = "art@172.20.200.93",
    [string]$RemoteRoot = "/home/art/Documents/Lattice/LWY/HuBaiLab",
    [int]$IntervalSec = 60
)

$log = "$RemoteRoot/output/logs/paperbox_fuse_auto.log"
$progress = "$RemoteRoot/output/logs/paperbox_fuse.progress"

Write-Host "Watching paper box fuse on $RemoteHost (Ctrl+C to stop monitor only)" -ForegroundColor Cyan
while ($true) {
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $block = ssh $RemoteHost @"
echo '--- $ts ---'
free -h | awk '/^Mem:/ {print \"mem avail=\" \$7 \" used=\" \$3 \" total=\" \$2}'
uptime
pgrep -af 'run_paper_box_fuse_safe|run_hu_bai_paper_box' || echo 'no fuse process'
tmux ls 2>/dev/null | grep paperbox_fuse || echo 'no paperbox_fuse tmux'
echo '-- progress --'
tail -n 3 '$progress' 2>/dev/null || echo '(no progress file)'
echo '-- log --'
tail -n 8 '$log' 2>/dev/null || echo '(no log yet)'
ls -lh '$RemoteRoot/output/cad/_paper_box_array_q1p0/'*.step 2>/dev/null || true
ls -lh '$RemoteRoot/output/cad/_paper_box_array_q1p5/'*.step 2>/dev/null || true
"@
    Write-Host $block
    Start-Sleep -Seconds $IntervalSec
}
