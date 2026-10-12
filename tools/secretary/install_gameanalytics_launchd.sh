#!/usr/bin/env bash
# GameAnalytics for Civic Watch and Mecca Gecko into Secretary.
# The Secretary scheduler on the Mac runs it now: job `gameanalytics` in
# ~/projects/ios_secretary_notification_app/automation/jobs.json, every 5 minutes.
# This script no longer writes a plist of its own. It hands over to the scheduler's
# installer, which also retires the old per-feed job com.codecreations.secretary.gameanalytics.
set -euo pipefail
echo "gameanalytics is scheduled by the Secretary scheduler (automation/jobs.json, job id gameanalytics)"
exec "$HOME/projects/ios_secretary_notification_app/automation/install_scheduler.sh"
