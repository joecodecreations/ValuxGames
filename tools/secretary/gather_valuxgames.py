#!/usr/bin/env python3
"""Push valuxgames.com Analytics into the Secretary valux-games section.

Owns the valuxgames node only. Civic Watch and Mecca Gecko keep their nodes.
Scheduled by the Secretary scheduler (automation/jobs.json, job id valuxgames-site).
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
AUTOMATION = Path.home() / "projects" / "ios_secretary_notification_app" / "automation"
STATE_PATH = Path.home() / ".config" / "valux-games" / "secretary" / "state.json"
SECTION_ID = "valux-games"
NODE_ID = "valuxgames"
JOB_ID = "valuxgames-site"
JOBS_FILE = AUTOMATION / "jobs.json"
# The Secretary scheduler runs this every SCHEDULE_EVERY seconds, SCHEDULE_OFFSET seconds past the
# hour (:27 and :57). `--self-test` checks automation/jobs.json says the same.
SCHEDULE_EVERY = 1800
SCHEDULE_OFFSET = 1620
PT = ZoneInfo("America/Los_Angeles")

sys.path.insert(0, str(AUTOMATION))

import secretary_blocks as sb  # noqa: E402
import valux_google  # noqa: E402

ICON_PATH = ROOT / "assets" / "icon-512.png"


def _checked(now: datetime) -> str:
    return now.strftime("%-d %b %Y, %-I:%M %p PT")


def _minutes() -> list[int]:
    return sorted({((SCHEDULE_OFFSET + k * SCHEDULE_EVERY) % 3600) // 60 for k in range(max(1, 3600 // SCHEDULE_EVERY))})


def _schedule_label() -> str:
    env = (os.environ.get("SECRETARY_SCHEDULE_LABEL") or "").strip()
    if env:
        return env
    marks = ", ".join(f":{minute:02d}" for minute in _minutes())
    return f"Every {SCHEDULE_EVERY // 60} min ({marks}), by the Secretary scheduler"


def _next_label(now: datetime) -> str:
    """SECRETARY_NEXT_RUN_AT when the scheduler gave one, else the next slot on the grid."""
    raw = (os.environ.get("SECRETARY_NEXT_RUN_AT") or "").strip()
    if raw:
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(PT).strftime("%-I:%M %p PT")
        except ValueError:
            pass
    slot = now.replace(minute=0, second=0, microsecond=0) + timedelta(seconds=SCHEDULE_OFFSET % SCHEDULE_EVERY)
    while slot <= now:
        slot += timedelta(seconds=SCHEDULE_EVERY)
    return slot.strftime("%-I:%M %p PT")


def _subtitle(site: dict, now: datetime) -> str:
    yesterday = valux_google.yesterday_iso(now)
    for day in site.get("days") or []:
        if day.get("date") == yesterday:
            return f"{int(day['users'])} people yesterday"[:80]
    if site.get("ok"):
        return "No Analytics row for yesterday"[:80]
    return "Analytics was not read"[:80]


def product_block(site: dict, now: datetime) -> dict:
    """valuxgames.com on the Secretary Home screen."""
    if site.get("ok"):
        headline, tone = _subtitle(site, now) + " on valuxgames.com.", "info"
    else:
        headline, tone = "Analytics was not read: " + str(site.get("error") or "no answer") + ".", "warning"
    return sb.product_block(
        kind="site",
        company="Valux Games LLC",
        headline=headline,
        tone=tone,
        checked_at=sb.iso(now),
        metrics=valux_google.site_product_metrics(site),
        links=[{"id": "site", "label": "valuxgames.com", "url": "https://valuxgames.com/"}],
    )


def build_node(google: dict, now: datetime, icon_url: str | None = None) -> dict:
    checked = _checked(now)
    site = google.get("site") or {}
    blocks = [product_block(site, now)] + valux_google.site_blocks(site, checked, series_after_kpis=True)
    blocks.append(
        {
            "type": "key_value",
            "id": "feed",
            "title": "How this page updates",
            "items": [
                {"label": "Schedule", "value": f"{_schedule_label()} on the Mac"},
                {"label": "Next check", "value": _next_label(now)},
                {"label": "Script", "value": "~/projects/ValuxGames/tools/secretary/gather_valuxgames.py"},
                {"label": "Job", "value": f"{(os.environ.get('SECRETARY_JOB_ID') or JOB_ID).strip()} in automation/jobs.json"},
                {"label": "Log", "value": "~/.config/valux-games/secretary/gather.log"},
                {"label": "Notifies on", "value": "A day with people on valuxgames.com"},
                {"label": "Reads", "value": "GA4 property 557364225: people, new people, sources, landing pages, countries, devices, outbound clicks"},
            ],
        }
    )
    node = {
        "id": NODE_ID,
        "title": "Valux Games",
        "subtitle": _subtitle(site, now),
        "icon": "globe",
        "order": 30,
        "layout": "page",
        "blocks": blocks,
        "tabs": [],
    }
    if icon_url:
        node["icon_image"] = icon_url
    return node


def _load_state() -> dict:
    if not STATE_PATH.is_file():
        return {}
    try:
        data = json.loads(STATE_PATH.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2) + "\n")


def _self_check(check_schedule: bool = False) -> None:
    valux_google.self_test()
    sb.self_test()
    sample = build_node({"site": {"ok": True, "host": "valuxgames.com", "days": []}}, datetime(2026, 10, 5, 9, tzinfo=PT), "/v1/media/x")
    assert sample["blocks"][0]["type"] == "product" and sample["blocks"][0]["kind"] == "site"
    assert sample["icon_image"] == "/v1/media/x"
    # The site-series block (Home and Analytics charts) sits right after the site-kpis tiles.
    # site_blocks reads "yesterday" from the clock, so the sample day is the real yesterday.
    read = {"site": {"ok": True, "host": "valuxgames.com", "product": "Valux Games", "days": [{"date": valux_google.yesterday_iso(), "users": 3, "sessions": 4, "new_users": 2, "views": 6}]}}
    blocks = build_node(read, datetime.now(PT))["blocks"]
    ids = [block["id"] for block in blocks]
    assert ids[:3] == ["product", "site-kpis", "site-series"], ids
    series = blocks[2]
    assert series["kind"] == "site" and series["site"] == "valuxgames.com" and series["company"] == "Valux Games LLC" and series["product"] == "Valux Games", series
    assert [metric["id"] for metric in series["metrics"]] == ["visitors", "new-visitors", "sessions", "views"], series["metrics"]
    feed = {item["label"]: item["value"] for item in sample["blocks"][-1]["items"]}
    assert "Secretary scheduler" in feed["Schedule"] and "launchd" not in json.dumps(feed), feed
    saved = {key: os.environ.pop(key, None) for key in ("SECRETARY_NEXT_RUN_AT",)}
    try:
        assert _next_label(datetime(2026, 10, 5, 9, 0, tzinfo=PT)) == "9:27 AM PT"
        assert _next_label(datetime(2026, 10, 5, 9, 27, tzinfo=PT)) == "9:57 AM PT"
        assert _next_label(datetime(2026, 10, 5, 9, 58, tzinfo=PT)) == "10:27 AM PT"
    finally:
        for key, value in saved.items():
            if value is not None:
                os.environ[key] = value
    if check_schedule:
        jobs = json.loads(JOBS_FILE.read_text(encoding="utf-8"))
        job = next((item for item in jobs.get("jobs") or [] if item.get("id") == JOB_ID), None)
        if not job:
            raise SystemExit(f"automation/jobs.json has no {JOB_ID} job")
        if int(job["every"]) != SCHEDULE_EVERY or int(job.get("offset") or 0) != SCHEDULE_OFFSET:
            raise SystemExit(f"jobs.json says every {job['every']} offset {job.get('offset')}; SCHEDULE_EVERY/SCHEDULE_OFFSET drifted")
        installer = (ROOT / "tools" / "secretary" / "install_launchd.sh").read_text()
        if "<plist" in installer or "install_scheduler.sh" not in installer:
            raise SystemExit("install_launchd.sh must hand off to the Secretary scheduler")


def main() -> int:
    _self_check(check_schedule="--self-test" in sys.argv)
    if "--self-test" in sys.argv:
        print("self-test ok")
        return 0
    dry_run = "--dry-run" in sys.argv
    from secretary_client import Secretary, SecretaryError

    now = datetime.now(PT)
    google = valux_google.fetch_google("valuxgames")
    node = build_node(google, now)
    previous = _load_state()
    alerts, patch = valux_google.plan(previous, google, now=now)
    state = dict(previous)
    state.update(patch)
    state["checked_at"] = now.isoformat(timespec="seconds")
    if dry_run:
        print(json.dumps({"subtitle": node["subtitle"], "alerts": alerts, "site_ok": google["site"].get("ok"), "days": len(google["site"].get("days") or []), "blocks": [block["id"] for block in node["blocks"]], "extras_error": google["site"].get("extras_error") or ""}, indent=2))
        return 0
    api = Secretary()
    review = api.review(SECTION_ID)
    blocked = [item for item in review.get("problems") or [] if item.get("code") == "not_rendered"]
    if blocked:
        print("review reported not_rendered", file=sys.stderr)
        return 1
    document = api.section(SECTION_ID)
    revision = document.get("revision")
    ops = [{"op": "upsert_node", "node": node}]
    # The company logo also marks the whole valux-games section. This job only sets icon_image there.
    try:
        icon_url = api.upload_icon(ICON_PATH)
        node["icon_image"] = icon_url
        if document.get("icon_image") != icon_url:
            ops.insert(0, {"op": "merge_section", "value": {"icon_image": icon_url}})
    except Exception as exc:
        print(f"icon: {exc}"[:240], file=sys.stderr)
        current = next((item for item in document.get("nodes") or [] if item.get("id") == NODE_ID), {})
        if current.get("icon_image"):
            node["icon_image"] = current["icon_image"]
    try:
        checked = api.validate(SECTION_ID, ops=ops, alerts=alerts or None, if_revision=revision)
    except SecretaryError as exc:
        print(exc, file=sys.stderr)
        return 1
    warnings = [item for item in checked.get("warnings") or [] if item.get("code") == "not_rendered"]
    if warnings:
        print("validate: phone would skip blocks", file=sys.stderr)
        return 1
    try:
        result = api.ops(SECTION_ID, ops=ops, alerts=alerts or None, if_revision=revision)
    except SecretaryError as exc:
        print(exc, file=sys.stderr)
        return 1
    _save_state(state)
    print(
        f"valuxgames pushed revision {result.get('revision')} "
        f"alerts {len(result.get('alert_ids') or [])} "
        f"days {len(google['site'].get('days') or [])}"
    )
    if not google["site"].get("ok"):
        print("source: " + str(google["site"].get("error") or "analytics unread"), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
