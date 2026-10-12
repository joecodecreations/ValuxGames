#!/usr/bin/env python3
"""GameAnalytics for Civic Watch and Mecca Gecko, iOS and Android, into Secretary.

The Secretary scheduler on the Mac runs this every 5 minutes (job `gameanalytics` in
~/projects/ios_secretary_notification_app/automation/jobs.json). Each run:
  - reads the last 24 hours from GameAnalytics through Joey's logged-in Chrome
    (automation/valux_gameanalytics.py in the Secretary repo)
  - posts realtime values to /v1/pulse: players this hour, players in 24 h, sessions,
    and in-game purchases per game. They show under Live now on the phone.
  - alerts on an in-game purchase, a new busiest hour, a burst of errors, first
    players on a platform, or a feed that stopped because Chrome is signed out.
Every 30 minutes it also reads 30 days (players, new and returning, D1/D3/D7 cohort
retention, payers, revenue, ARPDAU, ARPPU, session length, playtime, countries, top
design events, progression, event volume by type) and upserts the `players` tab on the
civic-watch and mecca-gecko nodes. This job owns that tab only.

    python3 tools/secretary/gather_gameanalytics.py --self-test
    python3 tools/secretary/gather_gameanalytics.py --dry-run
    python3 ~/projects/ios_secretary_notification_app/automation/scheduler.py --run gameanalytics --wait
"""

from __future__ import annotations

import fcntl
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

AUTOMATION = Path.home() / "projects" / "ios_secretary_notification_app" / "automation"
JOBS_FILE = AUTOMATION / "jobs.json"
STATE_PATH = Path.home() / ".config" / "valux-games" / "secretary" / "gameanalytics.json"
LOCK_PATH = STATE_PATH.with_name("gameanalytics.lock")
SECTION_ID = "valux-games"
TAB_ID = "players"
COMPANY = "Valux Games LLC"
JOB_ID = "gameanalytics"  # automation/jobs.json; the scheduler runs it, not launchd
INTERVAL_SECONDS = 300
OFFSET_SECONDS = 60
SCHEDULE_FALLBACK = "Every 5 min, by the Secretary scheduler"
FULL_EVERY = timedelta(minutes=30)
PULSE_TTL = 900  # three missed runs before the phone greys a value out
# Business events carry the price in cents, the way the SDKs send them. GameAnalytics'
# Metrics API docs show total_revenue 89664 beside arppu 896.64 for one payer.
# Unverified on this account until the first purchase arrives.
REVENUE_DIVISOR = 100.0
RECORD_MINIMUM = 3
ERROR_MINIMUM = 5

sys.path.insert(0, str(AUTOMATION))

import secretary_blocks as sb  # noqa: E402
import valux_gameanalytics as ga  # noqa: E402

# What each progression event id part means in each game (scripts/meta/*analytics*.gd).
PROGRESSION_PARTS = {
    "civic-watch": {1: "Type", 2: "Mode"},
    "mecca-gecko": {1: "Map", 2: "Mode"},
}
# The 30-day metrics the page needs, with the words for a "not returned" callout.
DEPTH_LABELS = {
    "returning_daily": "Returning players",
    "retention_daily": "Retention (D1, D3, D7)",
    "players_30d": "Players, 30 days",
    "payers_daily": "Paying players by day",
    "payers_30d": "Paying players, 30 days",
    "revenue_daily": "Revenue by day",
    "session_ends_30d": "Session count",
    "playtime_30d": "Playtime",
    "playtime_daily": "Playtime by day",
    "countries_30d": "Countries",
    "design_top_30d": "Design events",
    "progression1_30d": "Progression",
    "progression2_30d": "Progression",
    **{f"events_{key}_30d": f"{label} event count" for key, label in ga.EVENT_CATEGORIES.items()},
}
COUNTRIES = {
    "US": "United States", "CA": "Canada", "MX": "Mexico", "BR": "Brazil", "AR": "Argentina", "CL": "Chile",
    "CO": "Colombia", "PE": "Peru", "GB": "United Kingdom", "IE": "Ireland", "FR": "France", "DE": "Germany",
    "ES": "Spain", "PT": "Portugal", "IT": "Italy", "NL": "Netherlands", "BE": "Belgium", "CH": "Switzerland",
    "AT": "Austria", "SE": "Sweden", "NO": "Norway", "DK": "Denmark", "FI": "Finland", "PL": "Poland",
    "CZ": "Czechia", "RO": "Romania", "HU": "Hungary", "GR": "Greece", "TR": "Turkey", "UA": "Ukraine",
    "RU": "Russia", "IL": "Israel", "SA": "Saudi Arabia", "AE": "United Arab Emirates", "EG": "Egypt",
    "NG": "Nigeria", "ZA": "South Africa", "KE": "Kenya", "IN": "India", "PK": "Pakistan", "BD": "Bangladesh",
    "CN": "China", "HK": "Hong Kong", "TW": "Taiwan", "JP": "Japan", "KR": "South Korea", "VN": "Vietnam",
    "TH": "Thailand", "MY": "Malaysia", "SG": "Singapore", "ID": "Indonesia", "PH": "Philippines",
    "AU": "Australia", "NZ": "New Zealand",
}


def money(amount: float) -> str:
    return f"${amount:,.0f}" if abs(amount - round(amount)) < 0.005 else f"${amount:,.2f}"


def percent(rate: float) -> str:
    value = rate * 100
    return f"{value:.0f}%" if abs(value - round(value)) < 0.05 or value >= 10 else f"{value:.1f}%"


def duration(seconds: float) -> str:
    seconds = int(round(seconds))
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m {seconds % 60:02d}s"
    return f"{seconds // 3600}h {seconds % 3600 // 60:02d}m"


def whole(value: float) -> str:
    return f"{int(round(value)):,}"


def local_hour(key: str) -> str:
    try:
        moment = datetime.fromisoformat(key.replace("Z", "+00:00")).astimezone()
    except ValueError:
        return key[11:16]
    return moment.strftime("%-I %p")


def local_day(key: str) -> str:
    try:
        moment = datetime.fromisoformat(key.replace("Z", "+00:00"))
    except ValueError:
        return key[:10]
    return moment.strftime("%b %-d")


def local_time(iso: str) -> str:
    try:
        moment = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone()
    except ValueError:
        return iso
    return moment.strftime("%-I:%M %p %Z")


def schedule() -> tuple[str, str]:
    """The live schedule from the Secretary scheduler's environment, with the jobs.json values as fallback."""
    label = os.environ.get("SECRETARY_SCHEDULE_LABEL", "").strip() or SCHEDULE_FALLBACK
    upcoming = os.environ.get("SECRETARY_NEXT_RUN_AT", "").strip()
    return label, (local_time(upcoming) if upcoming else "")


def _metric(platforms: dict, platform: str, name: str) -> list[tuple[str, float]]:
    return ga.series((platforms.get(platform) or {}).get(name))


def _raw(platforms: dict, platform: str, name: str):
    return (platforms.get(platform) or {}).get(name)


def _sum(platforms: dict, platform: str, name: str, divisor: float = 1.0) -> float:
    return sum(value for _, value in _metric(platforms, platform, name)) / divisor


def _combined(platforms: dict, name: str, divisor: float = 1.0) -> list[tuple[str, float]]:
    by_key: dict[str, float] = {}
    for platform in ga.PLATFORMS:
        for key, value in _metric(platforms, platform, name):
            by_key[key] = by_key.get(key, 0.0) + value / divisor
    return sorted(by_key.items())


def _split(platforms: dict, name: str, fmt=lambda v: f"{int(v):,}", divisor: float = 1.0) -> str:
    return " · ".join(f"{ga.PLATFORM_NAMES[p]} {fmt(_sum(platforms, p, name, divisor))}" for p in ga.PLATFORMS)


def _answered(platforms: dict, name: str) -> bool:
    """Every platform answered this query (a failed one is not a zero)."""
    return bool(platforms) and all(not ga.failed(_raw(platforms, p, name)) for p in ga.PLATFORMS)


def _count(platforms: dict, platform: str, name: str) -> float:
    return ga.count(_raw(platforms, platform, name)) or 0.0


def _counts(platforms: dict, name: str) -> float:
    return sum(_count(platforms, p, name) for p in ga.PLATFORMS)


def missing(platforms: dict) -> list[str]:
    """'Retention (D1, D3, D7): iOS http 402 …' for every 30-day query GameAnalytics did not answer."""
    lines: dict[str, list[str]] = {}
    for name, label in DEPTH_LABELS.items():
        for platform in ga.PLATFORMS:
            reason = ga.failed(_raw(platforms, platform, name))
            if reason:
                lines.setdefault(label, []).append(f"{ga.PLATFORM_NAMES[platform]} {reason}"[:90])
    return [f"{label}: {'; '.join(reasons)}" for label, reasons in lines.items()]


def complete_days(points: list[tuple[str, float]], today: str) -> list[tuple[str, float]]:
    """Only whole UTC days: GameAnalytics' day buckets are UTC, and today is still running."""
    return [(key, value) for key, value in points if key[:10] < today]


def retention(platforms: dict, platforms_list=ga.PLATFORMS) -> dict[int, dict]:
    """Cohort retention, iOS and Android together. GameAnalytics answers a rate per install day; the
    cohort is that day's new players. Weighting each rate by its cohort gives exactly the dashboard's
    weighted mean (checked against /retention?granularity=all: Civic Watch iOS D1 1/19 = 5.3%).
    {days: {rate, retained, cohort, days: {day: [retained, cohort]}}}; rate None when no cohort is old enough."""
    result = {d: {"rate": None, "retained": 0.0, "cohort": 0.0, "days": {}} for d in ga.RETENTION_DAYS}
    for platform in platforms_list:
        new = {key[:10]: value for key, value in _metric(platforms, platform, "new_daily")}
        cohorts = ga.grouped(_raw(platforms, platform, "retention_daily"))
        for days in ga.RETENTION_DAYS:
            row = result[days]
            for key, rate in cohorts.get(str(days), []):
                size = new.get(key[:10], 0.0)
                if rate is None or size <= 0:
                    continue
                row["retained"] += rate * size
                row["cohort"] += size
                cell = row["days"].setdefault(key[:10], [0.0, 0.0])
                cell[0] += rate * size
                cell[1] += size
    for row in result.values():
        if row["cohort"] > 0:
            row["rate"] = row["retained"] / row["cohort"]
    return result


def depth(platforms: dict, today: str) -> dict:
    """The 30-day figures for one game, iOS and Android together, from real counts only."""
    players_30d = _counts(platforms, "players_30d")
    payers = _counts(platforms, "payers_30d")
    revenue = sum(_sum(platforms, p, "revenue_daily", REVENUE_DIVISOR) for p in ga.PLATFORMS)
    player_days = sum(_sum(platforms, p, "dau_daily") for p in ga.PLATFORMS)
    session_ends = _counts(platforms, "session_ends_30d")
    playtime = _counts(platforms, "playtime_30d")
    sessions = sum(_sum(platforms, p, "sessions_daily") for p in ga.PLATFORMS)
    week = complete_days(_combined(platforms, "dau_daily"), today)[-7:]
    week_by = {p: complete_days(_metric(platforms, p, "dau_daily"), today)[-7:] for p in ga.PLATFORMS}
    return {
        "players_30d": players_30d,
        "new_30d": sum(_sum(platforms, p, "new_daily") for p in ga.PLATFORMS),
        "payers_30d": payers,
        "revenue_30d": revenue,
        "purchases_30d": _counts(platforms, "events_business_30d"),
        "player_days": player_days,
        "arpdau": revenue / player_days if player_days else None,
        "arppu": revenue / payers if payers else None,
        "conversion": payers / players_30d if players_30d else None,
        "session_ends": session_ends,
        "playtime": playtime,
        "avg_session": playtime / session_ends if session_ends else None,
        "sessions_30d": sessions,
        "sessions_per_player": sessions / players_30d if players_30d else None,
        "dau7": sum(value for _, value in week) / len(week) if week else None,
        "dau7_by": {p: (sum(v for _, v in rows) / len(rows) if rows else None) for p, rows in week_by.items()},
        "retention": retention(platforms),
    }


def build_pulses(result: dict) -> list[dict]:
    at = result["checked_at"]
    items = []
    for game, spec in ga.GAMES.items():
        platforms = result["data"].get(game) or {}
        hourly = _combined(platforms, "active_hourly")
        now_value = hourly[-1][1] if hourly else 0.0
        common = {"section_id": SECTION_ID, "node_id": game, "source": "GameAnalytics", "at": at, "ttl_seconds": PULSE_TTL}
        last = {p: (_metric(platforms, p, "active_hourly") or [("", 0.0)])[-1][1] for p in ga.PLATFORMS}
        items.append(
            sb.pulse(
                f"ga.{game}.active-hour",
                label="Players this hour",
                value=now_value,
                detail=" · ".join(f"{ga.PLATFORM_NAMES[p]} {int(last[p])}" for p in ga.PLATFORMS),
                unit="players",
                order=10,
                series=hourly,
                **common,
            )
        )
        items.append(
            sb.pulse(
                f"ga.{game}.players-24h",
                label="Players, 24 h",
                value=sum(_sum(platforms, p, "active_total") for p in ga.PLATFORMS),
                detail=_split(platforms, "active_total"),
                unit="players",
                order=20,
                **common,
            )
        )
        items.append(
            sb.pulse(
                f"ga.{game}.sessions-24h",
                label="Sessions, 24 h",
                value=sum(_sum(platforms, p, "sessions_hourly") for p in ga.PLATFORMS),
                detail=_split(platforms, "sessions_hourly"),
                order=30,
                series=_combined(platforms, "sessions_hourly"),
                **common,
            )
        )
        revenue = sum(_sum(platforms, p, "revenue_hourly", REVENUE_DIVISOR) for p in ga.PLATFORMS)
        items.append(
            sb.pulse(
                f"ga.{game}.purchases-24h",
                label="Purchases, 24 h",
                value=revenue,
                display=money(revenue),
                detail="In-game report at list price",
                unit="USD",
                order=40,
                **common,
            )
        )
    return items


def _chart(block_id: str, title: str, caption: str, platforms: dict, name: str, label, chart: str = "line") -> dict | None:
    series = []
    for platform in ga.PLATFORMS:
        points = _metric(platforms, platform, name)
        if points:
            series.append({"name": ga.PLATFORM_NAMES[platform], "points": [{"x": label(key), "y": value} for key, value in points]})
    return _chart_block(block_id, title, caption, series, chart)


def _chart_block(block_id: str, title: str, caption: str, series: list[dict], chart: str, y_format: str = "number") -> dict | None:
    """A chart only when it has a line to draw: two points or more and something above zero."""
    series = [row for row in series if row["points"]]
    if not series or not any(point["y"] for s in series for point in s["points"]) or max(len(s["points"]) for s in series) < 2:
        return None
    return {"type": "chart", "id": block_id, "title": title, "caption": caption, "chart": chart, "y_format": y_format, "series": series}


def _tile(ident: str, label: str, value: str, caption: str = "") -> dict:
    return sb.metric(label, value, ident=ident, caption=caption)


def _rate_tile(ident: str, label: str, row: dict, days: int, answered: bool) -> dict:
    if not answered:
        return _tile(ident, label, "—", "GameAnalytics did not return retention")
    if row["rate"] is None:
        return _tile(ident, label, "—", f"No install day is {days} full days old yet")
    return _tile(ident, label, percent(row["rate"]), f"{whole(row['retained'])} of {whole(row['cohort'])} new players came back on day {days}")


def kpi_blocks(platforms: dict, figures: dict) -> list[dict]:
    answered = {name: _answered(platforms, name) for name in DEPTH_LABELS}
    ret = figures["retention"]
    revenue = sum(_sum(platforms, p, "revenue_hourly", REVENUE_DIVISOR) for p in ga.PLATFORMS)
    purchases = sum(_sum(platforms, p, "purchases_hourly") for p in ga.PLATFORMS)
    dau7_by = figures["dau7_by"]
    dau7 = figures["dau7"]
    tiles = [
        _tile("players", "Players, 24 h", whole(sum(_sum(platforms, p, "active_total") for p in ga.PLATFORMS)), _split(platforms, "active_total")),
        _tile(
            "dau7",
            "Daily players, 7-day avg",
            "—" if dau7 is None else f"{dau7:,.1f}",
            " · ".join(f"{ga.PLATFORM_NAMES[p]} {dau7_by[p]:,.1f}" for p in ga.PLATFORMS if dau7_by[p] is not None) or "No full day yet",
        ),
        _rate_tile("d1", "D1 retention", ret[1], 1, answered["retention_daily"]),
        _rate_tile("d7", "D7 retention", ret[7], 7, answered["retention_daily"]),
    ]
    if answered["payers_30d"] and answered["players_30d"]:
        conversion = figures["conversion"]
        tiles.append(_tile("payers", "Payers, 30 d", whole(figures["payers_30d"]), f"{percent(conversion)} of {whole(figures['players_30d'])} players" if conversion is not None else "No players in 30 days"))
    else:
        tiles.append(_tile("payers", "Payers, 30 d", "—", "GameAnalytics did not return paying players"))
    if answered["revenue_daily"] and figures["arpdau"] is not None:
        tiles.append(_tile("arpdau", "ARPDAU, 30 d", f"${figures['arpdau']:,.2f}", f"{money(figures['revenue_30d'])} over {whole(figures['player_days'])} player-days"))
    else:
        tiles.append(_tile("arpdau", "ARPDAU, 30 d", "—", "No players in 30 days" if answered["revenue_daily"] else "GameAnalytics did not return revenue"))
    if answered["playtime_30d"] and answered["session_ends_30d"] and figures["avg_session"] is not None:
        tiles.append(_tile("session", "Avg session", duration(figures["avg_session"]), f"Mean of {whole(figures['session_ends'])} sessions that ended, 30 d"))
    else:
        tiles.append(_tile("session", "Avg session", "—", "No session ended in 30 days" if answered["playtime_30d"] else "GameAnalytics did not return session length"))
    tiles += [
        _tile("new", "New, 24 h", whole(sum(_sum(platforms, p, "new_hourly") for p in ga.PLATFORMS)), _split(platforms, "new_hourly")),
        _tile("sessions", "Sessions, 24 h", whole(sum(_sum(platforms, p, "sessions_hourly") for p in ga.PLATFORMS)), _split(platforms, "sessions_hourly")),
        _tile("purchases", "Purchases, 24 h", money(revenue), f"{int(purchases)} reported in game"),
    ]
    month = [
        _tile("players-30d", "Players, 30 d", whole(figures["players_30d"]) if answered["players_30d"] else "—", _split_count(platforms, "players_30d")),
        _tile("new-30d", "New players, 30 d", whole(figures["new_30d"]), "Sum of each day's new: " + _split(platforms, "new_daily")),
        _rate_tile("d3", "D3 retention", ret[3], 3, answered["retention_daily"]),
        _tile(
            "sessions-per-player",
            "Sessions per player",
            "—" if figures["sessions_per_player"] is None else f"{figures['sessions_per_player']:,.1f}",
            f"{whole(figures['sessions_30d'])} sessions, 30 d",
        ),
        _tile("playtime", "Playtime, 30 d", duration(figures["playtime"]) if answered["playtime_30d"] else "—", "Sum of ended sessions"),
        _tile(
            "revenue-30d",
            "Purchases, 30 d",
            money(figures["revenue_30d"]) if answered["revenue_daily"] else "—",
            f"{whole(figures['purchases_30d'])} reported in game" if figures["purchases_30d"] else "No in-game purchase in 30 days",
        ),
        _tile(
            "conversion",
            "Conversion, 30 d",
            "—" if figures["conversion"] is None else percent(figures["conversion"]),
            "Paying players ÷ players",
        ),
        _tile("arppu", "ARPPU, 30 d", "—" if figures["arppu"] is None else money(figures["arppu"]), "Per paying player" if figures["arppu"] is not None else "No paying player in 30 days"),
    ]
    return [
        {"type": "metrics", "id": "players-kpis", "items": tiles},
        {"type": "heading", "id": "players-30d-heading", "text": "Last 30 days", "level": 3},
        {"type": "metrics", "id": "players-30d", "items": month},
    ]


# The players series: (metric id, label, stat, daily query, format). Days are UTC, iOS + Android.
SERIES_METRICS = (
    ("players", "Players", "players", "dau_daily", ""),
    ("new-players", "New players", "new_players", "new_daily", ""),
    ("sessions", "Sessions", "sessions", "sessions_daily", ""),
    ("playtime", "Playtime", "playtime", "playtime_daily", "duration"),
)


def series_block(game: str, platforms: dict, checked_at: str = "") -> dict | None:
    """The `series` block (id players-series, kind players) the phone's Analytics charts read.

    Each metric is iOS + Android by UTC day: the last 30 days plus today so far. GameAnalytics
    answers every day in the range (an empty day is 0, as the dashboard draws it). A metric is
    sent only when both platforms answered its query; half a game is not a total."""
    metrics = []
    for ident, label, stat, name, fmt in SERIES_METRICS:
        if not _answered(platforms, name):
            continue
        points = {key[:10]: value for key, value in _combined(platforms, name)}
        if points:
            metrics.append(sb.series_metric(ident, label, points, stat=stat, fmt=fmt))
    if not metrics:
        return None
    return sb.series_block(
        kind="players",
        company=COMPANY,
        product=ga.GAMES[game]["title"],
        block_id="players-series",
        title="Players, daily",
        caption="GameAnalytics, iOS and Android together, by UTC day. The last day is today so far. Players are daily unique players; playtime is the length of sessions that ended.",
        window=7,
        as_of=checked_at or None,
        metrics=metrics,
    )


def _split_count(platforms: dict, name: str) -> str:
    return " · ".join(f"{ga.PLATFORM_NAMES[p]} {whole(_count(platforms, p, name))}" for p in ga.PLATFORMS)


def chart_blocks(platforms: dict, figures: dict) -> list[dict]:
    dau = _combined(platforms, "dau_daily")
    new = dict(_combined(platforms, "new_daily"))
    returning = dict(_combined(platforms, "returning_daily"))
    retention_series = []
    cohort_days = sorted(figures["retention"][1]["days"])
    for days in ga.RETENTION_DAYS:
        cells = figures["retention"][days]["days"]
        retention_series.append(
            {
                "name": f"Day {days}",
                "points": [{"x": local_day(day), "y": round(cells[day][0] / cells[day][1], 4)} for day in cohort_days if day in cells and cells[day][1] > 0],
            }
        )
    revenue_series = []
    for platform in ga.PLATFORMS:
        points = _metric(platforms, platform, "revenue_daily")
        revenue_series.append({"name": ga.PLATFORM_NAMES[platform], "points": [{"x": local_day(key), "y": round(value / REVENUE_DIVISOR, 2)} for key, value in points]})
    charts = [
        _chart("players-hourly", "Players by hour", "Last 24 hours, local time. Unique players per hour.", platforms, "active_hourly", local_hour),
        _chart_block(
            "players-daily",
            "Daily players",
            "Last 30 days by UTC day, iOS and Android together. New = first day in the game.",
            [
                {"name": "Players", "points": [{"x": local_day(key), "y": value} for key, value in dau]},
                {"name": "New", "points": [{"x": local_day(key), "y": new.get(key, 0.0)} for key, _ in dau]},
            ],
            "line",
        ),
        _chart_block(
            "new-daily",
            "New and returning players",
            "Last 30 days by UTC day, iOS and Android together.",
            [
                {"name": "New", "points": [{"x": local_day(key), "y": new.get(key, 0.0)} for key, _ in dau]},
                {"name": "Returning", "points": [{"x": local_day(key), "y": returning.get(key, 0.0)} for key, _ in dau]},
            ],
            "bar",
        ),
        _chart_block(
            "retention-cohorts",
            "Retention by install day",
            "Share of each day's new players who played again 1, 3 and 7 days later. iOS and Android together. "
            "A day appears once its cohort is old enough.",
            retention_series,
            "line",
            y_format="percent",
        )
        if len(retention_series[0]["points"]) >= 2
        else None,
        _chart_block(
            "revenue-daily",
            "In-game purchases",
            "Last 30 days by UTC day, what the game reports at list price.",
            revenue_series,
            "bar",
            y_format="currency",
        ),
        _chart("sessions-daily", "Sessions", "Last 30 days", platforms, "sessions_daily", local_day, chart="bar"),
    ]
    return [chart for chart in charts if chart]


def _merge_ranked(platforms: dict, name: str) -> list[tuple[str, dict[str, float]]]:
    rows: dict[str, dict[str, float]] = {}
    for platform in ga.PLATFORMS:
        for key, value in ga.ranked(_raw(platforms, platform, name)):
            rows.setdefault(key, {})[platform] = value
    return sorted(rows.items(), key=lambda row: (-sum(row[1].values()), row[0]))


def _merge_matrix(platforms: dict, name: str) -> dict[str, dict[str, float]]:
    rows: dict[str, dict[str, float]] = {}
    for platform in ga.PLATFORMS:
        for key, subs in ga.matrix(_raw(platforms, platform, name)).items():
            target = rows.setdefault(key, {})
            for sub, value in subs.items():
                target[sub] = target.get(sub, 0.0) + value
    return rows


def table_blocks(game: str, platforms: dict, figures: dict) -> list[dict]:
    blocks: list[dict] = []
    per = {p: depth({p: platforms.get(p) or {}}, figures["today"]) for p in ga.PLATFORMS}

    def rate(row: dict) -> str:
        return "—" if row["rate"] is None else percent(row["rate"])

    def platform_row(name: str, f: dict, ret: dict, players_24h: float, errors_24h: float) -> list[str]:
        return [
            name,
            whole(players_24h),
            whole(f["players_30d"]),
            whole(f["new_30d"]),
            rate(ret[1]),
            rate(ret[7]),
            whole(f["sessions_30d"]),
            "—" if f["avg_session"] is None else duration(f["avg_session"]),
            whole(f["payers_30d"]),
            money(f["revenue_30d"]),
            whole(errors_24h),
        ]

    rows = [
        platform_row(
            ga.PLATFORM_NAMES[p],
            per[p],
            per[p]["retention"],
            _sum(platforms, p, "active_total"),
            _sum(platforms, p, "errors_hourly"),
        )
        for p in ga.PLATFORMS
    ]
    rows.append(
        platform_row(
            "Total",
            figures,
            figures["retention"],
            sum(_sum(platforms, p, "active_total") for p in ga.PLATFORMS),
            sum(_sum(platforms, p, "errors_hourly") for p in ga.PLATFORMS),
        )
    )
    blocks.append(
        {
            "type": "table",
            "id": "players-platforms",
            "title": "By platform",
            "columns": ["Platform", "Players 24 h", "Players 30 d", "New 30 d", "D1", "D7", "Sessions 30 d", "Avg session", "Payers 30 d", "Purchases 30 d", "Errors 24 h"],
            "rows": rows,
        }
    )
    countries = _merge_ranked(platforms, "countries_30d")
    if countries:
        blocks.append(
            {
                "type": "table",
                "id": "players-countries",
                "title": "Top countries, 30 days",
                "columns": ["Country", "Players", "iOS", "Android"],
                "rows": [
                    [COUNTRIES.get(code, code), whole(sum(split.values())), whole(split.get("ios", 0)), whole(split.get("android", 0))]
                    for code, split in countries[:10]
                ],
            }
        )
    events: dict[str, dict[str, float]] = {}
    for platform in ga.PLATFORMS:
        for first, subs in ga.matrix(_raw(platforms, platform, "design_top_30d")).items():
            for second, value in subs.items():
                key = f"{first}:{second}" if second and second != "null" else first
                events.setdefault(key, {})[platform] = events.get(key, {}).get(platform, 0.0) + value
    if events:
        ranked_events = sorted(events.items(), key=lambda row: (-sum(row[1].values()), row[0]))[:10]
        blocks.append(
            {
                "type": "table",
                "id": "players-events",
                "title": "Top design events, 30 days",
                "columns": ["Event", "Count", "iOS", "Android"],
                "rows": [[key, whole(sum(split.values())), whole(split.get("ios", 0)), whole(split.get("android", 0))] for key, split in ranked_events],
            }
        )
    levels = {part: _merge_matrix(platforms, f"progression{part}_30d") for part in (1, 2)}
    # The part of the progression id that tells runs apart: Civic Watch's first part is always
    # "match" (modes are part 2); Mecca Gecko's first part is the map.
    part = 2 if len(levels[2]) > len(levels[1]) else 1
    progression = levels[part]
    if progression:
        names = PROGRESSION_PARTS.get(game, {1: "Level", 2: "Sub-level"})
        rows = []
        for key, statuses in sorted(progression.items(), key=lambda row: (-sum(row[1].values()), row[0]))[:10]:
            starts, completes, fails = (statuses.get(s, 0.0) for s in ("Start", "Complete", "Fail"))
            rows.append([key, whole(starts), whole(completes), whole(fails), percent(completes / starts) if starts else "—"])
        blocks.append(
            {
                "type": "table",
                "id": "players-progression",
                "title": f"Progression by {names[part].lower()}, 30 days",
                "columns": [names[part], "Starts", "Completes", "Fails", "Completed"],
                "rows": rows,
            }
        )
    blocks.append(
        {
            "type": "table",
            "id": "players-event-types",
            "title": "Events the game sent, 30 days",
            "columns": ["Type", "iOS", "Android", "Total"],
            "rows": [
                [
                    label,
                    *(whole(_count(platforms, p, f"events_{key}_30d")) if not ga.failed(_raw(platforms, p, f"events_{key}_30d")) else "—" for p in ga.PLATFORMS),
                    whole(_counts(platforms, f"events_{key}_30d")),
                ]
                for key, label in ga.EVENT_CATEGORIES.items()
            ],
        }
    )
    return blocks


def build_tab(game: str, result: dict, checked_label: str) -> dict:
    spec = ga.GAMES[game]
    blocks: list[dict] = []
    if not result.get("ok"):
        blocks.append(status_callout(result))
    platforms = (result.get("data") or {}).get(game) or {}
    today = str(result.get("checked_at") or "")[:10]
    figures = {}
    if platforms:
        figures = depth(platforms, today)
        figures["today"] = today
        series = series_block(game, platforms, str(result.get("checked_at") or ""))
        if series:
            blocks.append(series)
        blocks += kpi_blocks(platforms, figures)
        gaps = missing(platforms)
        if gaps:
            blocks.append(
                {
                    "type": "callout",
                    "id": "players-unavailable",
                    "tone": "warning",
                    "title": "Some GameAnalytics figures were not returned",
                    "text": (
                        "Tiles that need them show —, never 0. "
                        + " ".join(f"{line}." for line in gaps[:6])
                        + " An http 402 or 403 means the free plan does not include it."
                    )[:900],
                }
            )
        blocks += chart_blocks(platforms, figures)
        blocks += table_blocks(game, platforms, figures)
        errors = sum(_sum(platforms, p, "errors_hourly") for p in ga.PLATFORMS)
        if errors:
            blocks.append(
                {
                    "type": "callout",
                    "id": "players-errors",
                    "tone": "warning",
                    "title": f"{int(errors):,} errors in the last 24 hours",
                    "text": "GameAnalytics recorded error events from the game. Open Health in GameAnalytics for the messages.",
                }
            )
    blocks.append(source_block(spec, checked_label, platforms))
    blocks.append(
        {
            "type": "buttons",
            "id": "players-links",
            "items": [
                {"id": "realtime-ios", "label": "iOS Realtime", "style": "secondary", "url": ga.dashboard_url(spec["ios"])},
                {"id": "realtime-android", "label": "Android Realtime", "style": "secondary", "url": ga.dashboard_url(spec["android"])},
            ],
        }
    )
    return {"id": TAB_ID, "title": "Players", "icon": "person.3.fill", "blocks": blocks}


def status_callout(result: dict) -> dict:
    return {
        "type": "callout",
        "id": "players-status",
        "tone": "warning",
        "title": "GameAnalytics was not read",
        "text": (
            f"{result.get('error') or 'No answer.'} The figures below are the last good read. "
            "This feed reads the GameAnalytics dashboard in Chrome on the MacBook. Chrome must be open, "
            "the Grok browser bridge must be running, and the dashboard must be signed in."
        ),
    }


def source_block(spec: dict, checked_label: str, platforms: dict) -> dict:
    label, upcoming = schedule()
    items = [
        {"label": "Checked", "value": checked_label},
        {"label": "Source", "value": "GameAnalytics dashboard, read in Chrome (free plan has no API key)"},
        {"label": "Live values", "value": f"{label}, under Live now on Home"},
        {"label": "This page", "value": "Every 30 minutes, on one of those runs"},
    ]
    if upcoming:
        items.append({"label": "Next check", "value": upcoming})
    items += [
        {"label": "Retention", "value": "Share of each install day's new players seen again 1, 3, 7 days later, weighted by cohort size (GameAnalytics' weighted mean)"},
        {"label": "Session length", "value": "Mean of sessions that sent an end event. GameAnalytics' query tool has no median for sessions"},
        {"label": "Purchases", "value": "What the game reports at list price (SDK cents ÷ 100). Store proceeds are on Revenue"},
        {"label": "Days", "value": "UTC days, as GameAnalytics buckets them. 30 days = the last 30 plus today so far"},
    ]
    if platforms and _answered(platforms, "events_ads_30d") and not _counts(platforms, "events_ads_30d"):
        items.append({"label": "Ads", "value": "No ad events in 30 days, so no ad impressions or ad revenue to show"})
    items += [
        {"label": "Job", "value": f"{JOB_ID} in Secretary's automation/jobs.json"},
        {"label": "iOS game", "value": str(spec["ios"])},
        {"label": "Android game", "value": str(spec["android"])},
    ]
    return {"type": "key_value", "id": "players-source", "title": "GameAnalytics", "items": items}


def stale_tab(game: str, result: dict, previous: list[dict], checked_label: str) -> dict:
    """A failed read keeps the last good figures under a status callout instead of blanking the page."""
    kept = [block for block in previous if block.get("id") != "players-status"]
    if not kept:
        return build_tab(game, result, checked_label)
    return {"id": TAB_ID, "title": "Players", "icon": "person.3.fill", "blocks": [status_callout(result), *kept]}


def _previous_blocks(document: dict, game: str) -> list[dict]:
    for node in document.get("nodes") or []:
        if node.get("id") == game:
            for tab in node.get("tabs") or []:
                if tab.get("id") == TAB_ID:
                    return list(tab.get("blocks") or [])
    return []


def _alert(ident: str, title: str, body: str, game: str, *, level: str = "active") -> dict:
    return {
        "schema": "secretary.alert.v1",
        "id": ident[:128],
        "kind": "event",
        "title": title[:80],
        "body": body[:180],
        "section_id": SECTION_ID,
        "node_id": game,
        "tab_id": TAB_ID,
        "sound": "default",
        "thread_id": f"valux-games-{game}",
        "interruption_level": level,
        "launch_url": f"secretary://open?section={SECTION_ID}&node={game}&tab={TAB_ID}",
    }


def plan_alerts(result: dict, state: dict, now: datetime) -> tuple[list[dict], dict]:
    """Alerts for this run, and the state to save. The first good read records and stays quiet."""
    prior = dict(state)
    alerts: list[dict] = []
    today = now.astimezone().strftime("%Y-%m-%d")
    if not result.get("ok"):
        failing_since = prior.get("failing_since") or result["checked_at"]
        prior["failing_since"] = failing_since
        started = datetime.fromisoformat(failing_since.replace("Z", "+00:00"))
        long_outage = now - started >= timedelta(hours=3)
        if (result.get("code") == "signed_out" or long_outage) and prior.get("outage_alerted") != today:
            prior["outage_alerted"] = today
            reason = "Chrome is signed out of GameAnalytics" if result.get("code") == "signed_out" else "it has not answered for 3 hours"
            alerts.append(
                {
                    **_alert(f"valux-ga-feed-{today}", "GameAnalytics feed stopped", f"Live player numbers paused because {reason}. {str(result.get('error'))[:90]}", "civic-watch"),
                    "node_id": "civic-watch",
                }
            )
        return alerts, prior
    prior.pop("failing_since", None)
    bootstrapped = bool(prior.get("bootstrapped"))
    alerted_hours = set(prior.get("purchase_hours") or [])
    error_hours = set(prior.get("error_hours") or [])
    seen_players = dict(prior.get("seen_players") or {})
    best_hour = dict(prior.get("best_hour") or {})
    for game, spec in ga.GAMES.items():
        platforms = result["data"].get(game) or {}
        title = spec["title"]
        for platform in ga.PLATFORMS:
            name = ga.PLATFORM_NAMES[platform]
            key = f"{game}:{platform}"
            players = _sum(platforms, platform, "active_total")
            if players > 0 and not seen_players.get(key):
                seen_players[key] = True
                if bootstrapped:
                    alerts.append(_alert(f"valux-ga-{game}-{platform}-first-players", f"{title} {name}: first players", f"GameAnalytics saw {int(players)} {'player' if players == 1 else 'players'} on {name} in the last 24 hours.", game))
            for hour, amount in _metric(platforms, platform, "revenue_hourly"):
                ident = f"{key}:{hour}"
                if amount > 0 and ident not in alerted_hours:
                    alerted_hours.add(ident)
                    if bootstrapped:
                        alerts.append(_alert(f"valux-ga-{game}-{platform}-buy-{hour[:13]}", f"{title} purchase", f"{money(amount / REVENUE_DIVISOR)} in-game purchase reported on {name} around {local_hour(hour)}.", game, level="timeSensitive"))
            errors = _metric(platforms, platform, "errors_hourly")
            if len(errors) >= 3:
                hour, latest = errors[-2]  # the last complete hour
                others = [value for _, value in errors[:-2]]
                mean = sum(others) / len(others) if others else 0.0
                ident = f"{key}:{hour}"
                if latest >= ERROR_MINIMUM and latest >= 3 * max(mean, 1) and ident not in error_hours:
                    error_hours.add(ident)
                    if bootstrapped:
                        alerts.append(_alert(f"valux-ga-{game}-{platform}-errors-{hour[:13]}", f"{title} {name} errors", f"{int(latest)} errors around {local_hour(hour)}, against about {mean:.0f} an hour before.", game))
        hourly = _combined(platforms, "active_hourly")
        peak = max((value for _, value in hourly), default=0.0)
        if peak > float(best_hour.get(game) or 0):
            if bootstrapped and peak >= RECORD_MINIMUM:
                alerts.append(_alert(f"valux-ga-{game}-record-{int(peak)}", f"{title}: busiest hour yet", f"{int(peak)} players in one hour across iOS and Android.", game))
            best_hour[game] = peak
    prior.update(
        {
            "bootstrapped": True,
            "purchase_hours": sorted(alerted_hours)[-500:],
            "error_hours": sorted(error_hours)[-200:],
            "seen_players": seen_players,
            "best_hour": best_hour,
        }
    )
    return alerts, prior


def load_state() -> dict:
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(STATE_PATH)


def _due_full(state: dict, now: datetime) -> bool:
    last = state.get("last_full")
    if not last:
        return True
    try:
        return now - datetime.fromisoformat(last.replace("Z", "+00:00")) >= FULL_EVERY - timedelta(seconds=30)
    except ValueError:
        return True


def run(dry_run: bool = False) -> int:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    state = load_state()
    full = _due_full(state, now) or (dry_run and "--full" in sys.argv)
    result = ga.fetch(now, full=full)
    alerts, new_state = plan_alerts(result, state, now)
    pulses = build_pulses(result) if result.get("ok") else []
    checked_label = now.astimezone().strftime("%-d %b %Y, %-I:%M %p %Z")
    write_tabs = (full and result.get("ok")) or (not result.get("ok") and state.get("last_status") == "ok")
    gaps = sum(len(missing((result.get("data") or {}).get(game) or {})) for game in ga.GAMES) if full and result.get("ok") else 0
    summary = f"gameanalytics ok={result.get('ok')} code={result.get('code') or '-'} full={full} pulses={len(pulses)} tabs={2 if write_tabs else 0} alerts={len(alerts)} gaps={gaps}"
    if dry_run:
        tabs = [build_tab(game, result, checked_label) for game in ga.GAMES] if write_tabs else []
        print(json.dumps({"pulses": pulses, "alerts": alerts, "tabs": [tab["blocks"] for tab in tabs]}, indent=2)[: int(os.environ.get("DRY_RUN_CHARS", "6000"))])
        print(summary)
        return 0
    from secretary_client import Secretary, SecretaryError

    api = Secretary()
    try:
        if pulses:
            api.pulse(pulses)
        if write_tabs:
            document = api.section(SECTION_ID)
            if result.get("ok"):
                tabs = {game: build_tab(game, result, checked_label) for game in ga.GAMES}
            else:
                tabs = {game: stale_tab(game, result, _previous_blocks(document, game), checked_label) for game in ga.GAMES}
            ops = [{"op": "upsert_tab", "node_id": game, "tab": tab} for game, tab in tabs.items()]
            api.ops(SECTION_ID, ops=ops, alerts=alerts or None, if_revision=document.get("revision"))
        elif alerts:
            api.alerts(alerts)
    except SecretaryError as exc:
        print(f"{summary}\n{exc}", file=sys.stderr)
        return 1
    if full and result.get("ok"):
        new_state["last_full"] = result["checked_at"]
    new_state["last_status"] = "ok" if result.get("ok") else "error"
    save_state(new_state)
    print(f"{now.isoformat()} {summary}")
    if not result.get("ok"):
        print(f"{now.isoformat()} source: {result.get('error')}", file=sys.stderr)
    return 0


def _sample(values, start_day: int = 1, hourly: bool = True):
    key = (lambda i: f"2026-10-05T{i:02d}:00:00.000Z") if hourly else (lambda i: f"2026-10-{start_day + i:02d}T00:00:00.000Z")
    return {"items": [{"key": "time", "items": [{"key": key(i), "value": v} for i, v in enumerate(values)]}]}


def _all(value):
    return {"items": [{"key": "time", "items": [{"key": "2026-09-11T00:00:00.000Z", "value": value}]}], "summary": {"total": value}}


def self_test() -> None:
    sb.self_test()
    ga.self_test()
    resp = _sample
    day = lambda values: _sample(values, start_day=5, hourly=False)  # Oct 5..
    data = {
        game: {
            platform: {
                "active_hourly": resp([0, 1, 2]),
                "active_total": resp([2]),
                "sessions_hourly": resp([0, 3, 1]),
                "revenue_hourly": resp([0, 0, 0]),
                "new_hourly": resp([0, 1, 0]),
                "purchases_hourly": resp([0, 0, 0]),
                "errors_hourly": resp([0, 0, 0]),
                "dau_daily": day([1, 7, 5, 3, 5, 1, 1]),
                "new_daily": day([1, 6, 4, 3, 5, 1, 1]),
                "returning_daily": day([0, 1, 1, 0, 0, 0, 0]),
                "sessions_daily": day([3, 4, 2, 2, 3, 1, 1]),
                # Captured shape: one group per days-ahead, null until the cohort is old enough.
                "retention_daily": {
                    "items": [
                        {"key": "1", "items": [{"key": f"2026-10-{d:02d}T00:00:00.000Z", "value": v} for d, v in zip(range(5, 12), [1, 0, 0, 0, 0, None, None])]},
                        {"key": "3", "items": [{"key": f"2026-10-{d:02d}T00:00:00.000Z", "value": v} for d, v in zip(range(5, 12), [0, 0, 0, None, None, None, None])]},
                        {"key": "7", "items": [{"key": f"2026-10-{d:02d}T00:00:00.000Z", "value": None} for d in range(5, 12)]},
                    ]
                },
                "players_30d": _all(20),
                "payers_daily": day([0] * 7),
                "payers_30d": _all(None),
                "revenue_daily": day([0] * 7),
                "session_ends_30d": _all(31),
                "playtime_30d": _all(8852),
                "playtime_daily": day([0, 600, 1200, 300, 900, 60, 0]),
                "countries_30d": ga.SAMPLE_COUNTRIES,
                "design_top_30d": ga.SAMPLE_DESIGN,
                "progression1_30d": ga.SAMPLE_PROGRESSION,
                "progression2_30d": {"items": [{"key": "zombie_coop", "items": [{"key": "Start", "value": 5}, {"key": "Fail", "value": 2}]}, {"key": "range_event", "items": [{"key": "Start", "value": 2}, {"key": "Complete", "value": 1}]}]},
                **{f"events_{key}_30d": _all(6 if key == "design" else None) for key in ga.EVENT_CATEGORIES},
            }
            for platform in ga.PLATFORMS
        }
        for game in ga.GAMES
    }
    result = {"ok": True, "code": "", "error": "", "checked_at": "2026-10-11T03:05:00Z", "data": data}
    pulses = build_pulses(result)
    first = next(item for item in pulses if item["key"] == "ga.civic-watch.active-hour")
    assert first["value"] == 4 and first["detail"] == "iOS 2 · Android 2", first
    assert next(item for item in pulses if item["key"] == "ga.mecca-gecko.players-24h")["value"] == 4
    # Retention weighting: iOS + Android, D1 cohorts Oct 5-9 = 2 × 19 new, 2 retained.
    figures = depth(data["civic-watch"], "2026-10-11")
    assert abs(figures["retention"][1]["rate"] - 2 / 38) < 1e-9 and figures["retention"][1]["cohort"] == 38, figures["retention"][1]
    assert figures["retention"][3]["rate"] == 0.0 and figures["retention"][7]["rate"] is None
    assert figures["avg_session"] == 8852 / 31 and figures["players_30d"] == 40 and figures["payers_30d"] == 0
    assert figures["arpdau"] == 0.0 and figures["arppu"] is None and figures["conversion"] == 0.0
    assert figures["dau7"] == (2 + 14 + 10 + 6 + 10 + 2) / 6, figures["dau7"]  # Oct 11 is today, not a full day
    assert duration(285.5) == "4m 46s" and duration(8852) == "2h 27m" and duration(42) == "42s"
    assert percent(2 / 38) == "5.3%" and percent(0.5) == "50%" and percent(0) == "0%"
    tab = build_tab("civic-watch", result, "now")
    ids = [block["id"] for block in tab["blocks"]]
    assert ids[0] == "players-series" and ids[1] == "players-kpis" and ids[2:4] == ["players-30d-heading", "players-30d"], ids
    by_id = {block["id"]: block for block in tab["blocks"]}
    series = by_id["players-series"]
    assert (series["type"], series["kind"], series["company"], series["product"], series["window"]) == ("series", "players", "Valux Games LLC", "Civic Watch", 7), series
    assert [(m["id"], m.get("stat"), m.get("format")) for m in series["metrics"]] == [("players", "players", None), ("new-players", "new_players", None), ("sessions", "sessions", None), ("playtime", "playtime", "duration")], series["metrics"]
    assert series["metrics"][0]["points"][:2] == [{"x": "2026-10-05", "y": 2}, {"x": "2026-10-06", "y": 14}], series["metrics"][0]["points"]  # iOS + Android
    assert series["metrics"][3]["points"][1] == {"x": "2026-10-06", "y": 1200} and series["as_of"] == "2026-10-11T03:05:00Z"
    for needed in ("players-hourly", "players-daily", "new-daily", "retention-cohorts", "sessions-daily", "players-platforms", "players-countries", "players-events", "players-progression", "players-event-types", "players-source", "players-links"):
        assert needed in ids, (needed, ids)
    assert "revenue-daily" not in ids and "players-unavailable" not in ids, ids  # no purchases: no empty chart, no gap callout
    assert ids.index("players-30d") < ids.index("players-hourly") < ids.index("players-platforms"), ids
    kpis = {tile["id"]: tile for tile in by_id["players-kpis"]["items"]}
    assert [tile["id"] for tile in by_id["players-kpis"]["items"]][:7] == ["players", "dau7", "d1", "d7", "payers", "arpdau", "session"], kpis
    assert kpis["d1"]["value"] == "5.3%" and "2 of 38" in kpis["d1"]["caption"], kpis["d1"]
    assert kpis["d7"]["value"] == "—" and "7 full days" in kpis["d7"]["caption"]
    assert kpis["session"]["value"] == "4m 46s" and kpis["arpdau"]["value"] == "$0.00"
    assert len(by_id["players-kpis"]["items"]) <= 12 and len(by_id["players-30d"]["items"]) <= 12
    blocks = {block["id"]: block for block in tab["blocks"]}
    assert blocks["players-platforms"]["rows"][-1][0] == "Total" and blocks["players-platforms"]["rows"][0][4] == "5.3%", blocks["players-platforms"]["rows"]
    assert blocks["players-countries"]["rows"][0] == ["United States", "30", "15", "15"], blocks["players-countries"]["rows"]
    assert blocks["players-events"]["rows"][0] == ["Match:Finish", "8", "4", "4"], blocks["players-events"]["rows"]
    # Civic Watch's first progression part is always "match", so the table goes by mode.
    assert blocks["players-progression"]["columns"][0] == "Mode" and blocks["players-progression"]["rows"][0][:2] == ["zombie_coop", "10"], blocks["players-progression"]
    assert blocks["players-event-types"]["rows"][0] == ["Design", "6", "6", "12"] and blocks["players-event-types"]["rows"][-1] == ["Ads", "0", "0", "0"]
    retention_chart = blocks["retention-cohorts"]
    assert retention_chart["y_format"] == "percent" and retention_chart["series"][0]["points"][:2] == [{"x": "Oct 5", "y": 1.0}, {"x": "Oct 6", "y": 0.0}], retention_chart
    for block in tab["blocks"]:
        if block["type"] == "table":
            assert all(isinstance(cell, str) for row in block["rows"] for cell in row), block["id"]
        if block["type"] == "chart":
            assert all(len(s["points"]) <= 400 for s in block["series"]), block["id"]
    # A metric GameAnalytics refuses is a callout and a dash, never a zero.
    refused = json.loads(json.dumps(result))
    for platform in ga.PLATFORMS:
        refused["data"]["mecca-gecko"][platform]["retention_daily"] = {"error": "http 402", "detail": "upgrade"}
    gap_tab = build_tab("mecca-gecko", refused, "now")
    gap_ids = [block["id"] for block in gap_tab["blocks"]]
    assert "players-unavailable" in gap_ids and "Retention" in gap_tab["blocks"][gap_ids.index("players-unavailable")]["text"], gap_ids
    assert {t["id"]: t for t in next(b for b in gap_tab["blocks"] if b["id"] == "players-kpis")["items"]}["d1"]["value"] == "—"
    # A daily query one platform did not answer leaves that metric out of the series, never half a total.
    for platform in ga.PLATFORMS[:1]:
        refused["data"]["mecca-gecko"][platform]["playtime_daily"] = {"error": "http 402", "detail": "upgrade"}
    gap_series = series_block("mecca-gecko", refused["data"]["mecca-gecko"])
    assert [m["id"] for m in gap_series["metrics"]] == ["players", "new-players", "sessions"] and gap_series["product"] == "Mecca Gecko", gap_series["metrics"]
    assert series_block("mecca-gecko", {}) is None
    assert "retention-cohorts" not in gap_ids
    # Schedule text comes from the scheduler's environment.
    # A real run gets these from the scheduler; the test puts the real values back afterwards.
    saved_env = {name: os.environ.get(name) for name in ("SECRETARY_SCHEDULE_LABEL", "SECRETARY_NEXT_RUN_AT")}
    os.environ["SECRETARY_SCHEDULE_LABEL"], os.environ["SECRETARY_NEXT_RUN_AT"] = "Every 5 min, by the Secretary scheduler", "2026-10-11T03:11:00Z"
    try:
        rows = {row["label"]: row["value"] for row in source_block(ga.GAMES["civic-watch"], "now", data["civic-watch"])["items"]}
    finally:
        for name, value in saved_env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
    assert rows["Live values"].startswith("Every 5 min, by the Secretary scheduler") and "Next check" in rows and "launchd" not in json.dumps(rows), rows
    assert "Ads" in rows
    now = datetime(2026, 10, 5, 3, 5, tzinfo=timezone.utc)
    quiet, state = plan_alerts(result, {}, now)
    assert quiet == [] and state["bootstrapped"], quiet
    bought = json.loads(json.dumps(result))
    bought["data"]["mecca-gecko"]["ios"]["revenue_hourly"] = resp([0, 0, 99])
    bought["data"]["civic-watch"]["android"]["active_hourly"] = resp([0, 1, 5])
    alerts, state2 = plan_alerts(bought, state, now)
    titles = sorted(alert["title"] for alert in alerts)
    assert titles == ["Civic Watch: busiest hour yet", "Mecca Gecko purchase"], titles
    assert "$0.99" in next(a for a in alerts if a["title"] == "Mecca Gecko purchase")["body"]
    again, _ = plan_alerts(bought, state2, now)
    assert again == [], again
    down = {"ok": False, "code": "signed_out", "error": "refresh 401", "checked_at": "2026-10-05T03:10:00Z", "data": {}}
    outage, state3 = plan_alerts(down, state2, now)
    assert len(outage) == 1 and "signed out" in outage[0]["body"], outage
    assert plan_alerts(down, state3, now)[0] == [], "one outage alert a day"
    assert build_tab("civic-watch", down, "now")["blocks"][0]["id"] == "players-status"
    kept = stale_tab("civic-watch", down, tab["blocks"], "now")["blocks"]
    assert kept[0]["id"] == "players-status" and [b["id"] for b in kept[1:]] == ids, "a failed read keeps the last good figures"
    # The scheduler owns the timing: jobs.json must match these constants, and the installer only hands over.
    job = next(item for item in json.loads(JOBS_FILE.read_text(encoding="utf-8"))["jobs"] if item["id"] == JOB_ID)
    assert int(job["every"]) == INTERVAL_SECONDS and int(job.get("offset") or 0) == OFFSET_SECONDS, ("jobs.json drifted", job["every"], job.get("offset"))
    assert any(str(part).endswith("tools/secretary/gather_gameanalytics.py") for part in job["argv"]), job["argv"]
    installer = (Path(__file__).resolve().parent / "install_gameanalytics_launchd.sh").read_text()
    assert JOB_ID in installer and "install_scheduler.sh" in installer and "<plist" not in installer and "launchctl" not in installer, "installer drifted"


def main() -> int:
    self_test()
    if "--self-test" in sys.argv:
        print("self-test ok")
        return 0
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOCK_PATH.open("a+") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("gameanalytics gatherer already running")
            return 0
        return run(dry_run="--dry-run" in sys.argv)


if __name__ == "__main__":
    raise SystemExit(main())
