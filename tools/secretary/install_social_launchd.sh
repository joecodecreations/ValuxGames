#!/usr/bin/env bash
# Valux Games social accounts (TikTok, Instagram, Facebook, YouTube) into Secretary.
# The Secretary scheduler on the Mac runs it now: job `valux-social` in
# ~/projects/ios_secretary_notification_app/automation/jobs.json, every 15 minutes.
# This script no longer writes a plist of its own. It hands over to the scheduler's
# installer, which also retires the old per-feed job com.codecreations.secretary.social.
set -euo pipefail
echo "valux-social is scheduled by the Secretary scheduler (automation/jobs.json, job id valux-social)"
exec "$HOME/projects/ios_secretary_notification_app/automation/install_scheduler.sh"
