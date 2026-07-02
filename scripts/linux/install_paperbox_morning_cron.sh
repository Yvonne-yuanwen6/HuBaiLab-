#!/usr/bin/env bash
# Install 08:00 daily morning report cron for user art.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
CRON_LINE="0 8 * * * cd $ROOT && bash scripts/linux/morning_paperbox_report.sh >> output/logs/paperbox_morning_cron.log 2>&1"
( crontab -l 2>/dev/null | grep -v morning_paperbox_report || true
  echo "$CRON_LINE"
) | crontab -
echo "Installed cron:"
crontab -l | grep morning_paperbox
