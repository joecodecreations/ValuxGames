#!/usr/bin/env python3
"""Google Search Console for valuxgames.com, civicwatchgame.com, and meccagecko.com into Secretary.

Hourly at :47 and at login (launchd, install_search_launchd.sh):
  - reads each property with the Search Console API as the Valux Secretary reader
    (secretary-reader@valux-secretary, key ~/.config/valux-games/secretary-google.json),
    a Restricted user on each property. The properties belong to weboaster@gmail.com
  - clicks, impressions, position by day; top searches, pages, countries, devices;
    sitemaps; and which sitemap pages Google has indexed (URL inspection)
  - upserts the `search` node in `valux-games`: Overview plus one tab per site
  - alerts on a finished day with clicks, pages Google newly indexed or dropped, new
    sitemap errors, and a site not read for 3 hours
The first good read of each site records what is there and stays quiet. Read only.

The reading, alert, and page code is shared with Firm Binder's feed
(automation/search_console.py in the Secretary repo).

    python3 tools/secretary/gather_search.py --self-test
    python3 tools/secretary/gather_search.py --check      # what the reader can see
    python3 tools/secretary/gather_search.py --dry-run
    python3 tools/secretary/gather_search.py
"""

from __future__ import annotations

import sys
from pathlib import Path

AUTOMATION = Path.home() / "projects" / "ios_secretary_notification_app" / "automation"
sys.path.insert(0, str(AUTOMATION))

import search_console as sc  # noqa: E402

LAUNCHD_LABEL = "com.codecreations.secretary.valux-search"
SCHEDULE_MINUTE = 47


def _site(key: str, title: str, home: str) -> sc.Site:
    return sc.Site(key=key, title=title, property=home, home=home, sitemap=home + "sitemap.xml")


FEED = sc.Feed(
    short="Valux",
    company="Valux Games LLC",
    section_id="valux-games",
    node_id="search",
    node_title="Google Search",
    node_order=45,
    alert_prefix="valux-search",
    state_path=Path.home() / ".config" / "valux-games" / "secretary" / "search.json",
    launchd_label=LAUNCHD_LABEL,
    schedule_minute=SCHEDULE_MINUTE,
    script="~/projects/ValuxGames/tools/secretary/gather_search.py",
    log_path="~/.config/valux-games/secretary/search.log",
    reader="secretary-reader@valux-secretary.iam.gserviceaccount.com",
    token=sc.key_file_token(),
    token_help="The Valux reader key at ~/.config/valux-games/secretary-google.json is missing or is not the Valux Secretary reader.",
    api_help=(
        "The Search Console API is off in Google Cloud project valux-secretary, which belongs to support@valuxgames.com. "
        "Sign in to Google Cloud as support@valuxgames.com and click Enable: "
        "https://console.cloud.google.com/apis/library/searchconsole.googleapis.com?project=valux-secretary"
    ),
    sites=(
        _site("valuxgames", "Valux Games", "https://valuxgames.com/"),
        _site("civic-watch", "Civic Watch", "https://civicwatchgame.com/"),
        _site("mecca-gecko", "Mecca Gecko", "https://www.meccagecko.com/"),
    ),
)


def self_test() -> None:
    installer = Path(__file__).resolve().parent / "install_search_launchd.sh"
    sc.self_test(FEED, installer=installer)
    # The Secretary scheduler runs this feed (automation/jobs.json); the installer only hands over to it.
    text = installer.read_text(encoding="utf-8")
    assert "valux-search" in text and "install_scheduler.sh" in text and "<plist" not in text, "installer drifted"
    assert FEED.alert_prefix == "valux-search" and FEED.node_id == "search"
    assert [s.host for s in FEED.sites] == ["valuxgames.com", "civicwatchgame.com", "www.meccagecko.com"]
    # Each site tab's search-series block names the product by the site's title, the same names
    # the product and site series blocks use.
    assert [s.title for s in FEED.sites] == ["Valux Games", "Civic Watch", "Mecca Gecko"] and FEED.company == "Valux Games LLC"
    mecca = sc.search_series_block(FEED, FEED.sites[2], {"daily": [{"date": "2026-10-05", "clicks": 1, "impressions": 3, "position": 5.0}], "final_through": "2026-10-05"})
    assert (mecca["product"], mecca["site"], mecca["company"]) == ("Mecca Gecko", "meccagecko.com", "Valux Games LLC"), mecca


if __name__ == "__main__":
    raise SystemExit(sc.main(FEED, sys.argv, self_test))
