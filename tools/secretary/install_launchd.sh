#!/bin/bash
# The valuxgames.com feed no longer has its own launchd plist. The Secretary scheduler runs it
# from ~/projects/ios_secretary_notification_app/automation/jobs.json (job id valuxgames-site,
# every 1800 s at :27 and :57). This script installs or refreshes that scheduler.
set -euo pipefail
echo "valuxgames-site is scheduled by the Secretary scheduler (automation/jobs.json, job id valuxgames-site); installing the scheduler"
exec "$HOME/projects/ios_secretary_notification_app/automation/install_scheduler.sh"
