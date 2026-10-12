#!/usr/bin/env python3
"""Valux Games social accounts (TikTok, Instagram, Facebook, YouTube) into Secretary.

Every 15 minutes (launchd, install_social_launchd.sh):
  - read each account through logged-in Chrome on the machine the Secretary repo's
    automation/browser_hosts.json names for brand `valux` (the Mac mini since 2026-10-11,
    TikTok still on the MacBook; window `secretary-social`): the inbox or notifications,
    post stats, follower counts, and who is signed in
  - keep a rolling activity log, so items stay on the phone after a site drops them
  - upsert the `social` node in `valux-games`: Overview plus one tab per platform
  - alert on each new comment, reply, mention, message, or moderation warning, and once
    per run for new likes, follows, shares, and milestones together
  - alert once a day when an account is signed out, acting as the wrong profile, or has
    not answered for 3 hours
The first good read of each source records what is already there and stays quiet.
Nothing here clicks, likes, replies, follows, switches accounts, or marks anything read.

The merge, alert, and page code is shared with Custody Commander's feed
(automation/social_feed.py). Custody Commander reads from its own Chrome profile
(Firmbinder, bridge 127.0.0.1:9877), so the two feeds never touch each other's logins.

    python3 tools/secretary/gather_social.py --self-test
    python3 tools/secretary/gather_social.py --check      # who each platform is signed in as
    python3 tools/secretary/gather_social.py --dry-run
    python3 tools/secretary/gather_social.py
"""

from __future__ import annotations

import sys
from pathlib import Path

AUTOMATION = Path.home() / "projects" / "ios_secretary_notification_app" / "automation"
sys.path.insert(0, str(AUTOMATION))

import social_feed as sf  # noqa: E402
import social_reader as sr  # noqa: E402

LAUNCHD_LABEL = "com.codecreations.secretary.social"
INTERVAL_SECONDS = 900

FEED = sf.Feed(
    brand=sr.VALUX,
    short="Valux",
    section_id="valux-games",
    node_id="social",
    node_title="Social",
    node_order=40,
    alert_prefix="valux-social",
    state_path=Path.home() / ".config" / "valux-games" / "secretary" / "social.json",
    launchd_label=LAUNCHD_LABEL,
    interval_seconds=INTERVAL_SECONDS,
    script="~/projects/ValuxGames/tools/secretary/gather_social.py",
    log_path="~/.config/valux-games/secretary/social.log",
)


def self_test() -> None:
    installer = Path(__file__).resolve().parent / "install_social_launchd.sh"
    sf.self_test(FEED, installer=installer)
    # The Secretary scheduler runs this feed (automation/jobs.json); the installer only hands over to it.
    text = installer.read_text(encoding="utf-8")
    assert "valux-social" in text and "install_scheduler.sh" in text and "<plist" not in text, "installer drifted"
    # Valux's own ids and state, unchanged since the feed went live, so nothing re-alerts.
    assert FEED.alert_prefix == "valux-social" and FEED.state_path.name == "social.json"
    assert FEED.lock_path.name == "social.lock"
    # Where Valux reads (machine, bridge, per-platform hosts) is automation/browser_hosts.json's call, not this file's.
    assert FEED.brand.key == "valux" and FEED.brand.session == "secretary-social"
    assert FEED.platforms == ("tiktok", "instagram", "facebook", "youtube")


if __name__ == "__main__":
    raise SystemExit(sf.main(FEED, sys.argv, self_test))
