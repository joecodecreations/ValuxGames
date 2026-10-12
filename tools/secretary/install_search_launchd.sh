#!/usr/bin/env bash
# Google Search Console for the Valux sites into Secretary.
# The Secretary scheduler on the Mac runs it now: job `valux-search` in
# ~/projects/ios_secretary_notification_app/automation/jobs.json, hourly at :47.
# This script no longer writes a plist of its own. It hands over to the scheduler's
# installer, which also retires the old per-feed job com.codecreations.secretary.valux-search.
set -euo pipefail
echo "valux-search is scheduled by the Secretary scheduler (automation/jobs.json, job id valux-search)"
exec "$HOME/projects/ios_secretary_notification_app/automation/install_scheduler.sh"
