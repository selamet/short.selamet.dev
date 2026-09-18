"""Read-only query services the dashboard uses to build its views.

Every function takes a workspace (and, where it makes sense, a specific link) plus a
date range, and returns plain data -- dicts, lists, and lists of lists, never a
queryset, a model instance, or anything built from raw SQL, an ordering, or a field
name the caller supplies. `summary`, `time_series`, `breakdown` and `leaderboard`
read the two rollup tables (DailyLinkStat, DailyLinkBreakdown) apps.analytics.rollups
keeps in sync; `recent_clicks` and `hour_weekday_matrix` are the two exceptions that
read raw ClickEvent rows instead, because neither an individual visit nor an
hour-of-day breakdown is something a daily rollup keeps.

`start` and `end` are inclusive dates in the workspace's own calendar. A
DailyLinkStat/DailyLinkBreakdown row's `date` is already the workspace-local day
apps.analytics.rollups.local_date() assigned its clicks to when it applied them, so
querying the four rollup-backed functions below needs no further timezone
conversion; only recent_clicks and hour_weekday_matrix convert a raw event's UTC
occurred_at themselves, since neither has a rollup row to read that conversion off
of (see _zone).
"""

import zoneinfo
from datetime import UTC, datetime, time, timedelta

from django.conf import settings
from django.db.models import Sum
from django.utils import timezone

from apps.links.models import Link

from .models import ClickEvent, DailyLinkBreakdown, DailyLinkStat


def _zone(workspace):
    """The workspace's own timezone, falling back to UTC when it cannot be loaded.

    Deliberately not imported from apps.analytics.rollups, whose equivalent
    (_workspace_zone) is a private helper: the analytics plan's interface list
    names only rollups.rebuild(), rollups.local_date(), Dimension, the three rollup
    models and privacy.daily_salt as shared across modules, so this read path keeps
    its own copy of the same small fallback instead of reaching past that boundary.
    """
    try:
        return zoneinfo.ZoneInfo(workspace.timezone)
    except (zoneinfo.ZoneInfoNotFoundError, ValueError):
        return UTC


def _clamp_limit(limit):
    """Keep a caller-supplied `limit` between 1 and ANALYTICS_QUERY_MAX_LIMIT, so a
    dashboard request can never turn into an unbounded scan of a breakdown,
    leaderboard or recent-clicks query."""
    return max(1, min(limit, settings.ANALYTICS_QUERY_MAX_LIMIT))


def padded_utc_window(start, end):
    """The [start, end) range of UTC instants that could contain every event whose
    local date -- under any workspace timezone offset -- falls somewhere in the
    inclusive local-date range [start, end]. Padding a full day on each side covers
    every real-world UTC offset (UTC-12 to UTC+14).

    Public (no leading underscore): shared by hour_weekday_matrix() below and
    apps.analytics.tasks.rebuild_daily_stats(), both of which need to scan raw
    ClickEvent rows by a local, not UTC, date range and both used to compute this
    window inline identically. It lives here, in queries.py, because tasks.py can
    import from queries.py with no cycle (queries.py has no dependency on tasks.py)
    and this is, at heart, a read concern -- but a second module reaching into a
    name queries.py itself marks private (with the leading underscore this used to
    have) is exactly the kind of import this codebase otherwise avoids, so the name
    is public instead.
    """
    window_start = datetime.combine(start - timedelta(days=1), time.min, tzinfo=UTC)
    window_end = datetime.combine(end + timedelta(days=2), time.min, tzinfo=UTC)
    return window_start, window_end


def _stat_queryset(workspace, link, start, end):
    query = DailyLinkStat.objects.filter(workspace=workspace, date__gte=start, date__lte=end)
    if link is not None:
        query = query.filter(link=link)
    return query


def _totals(workspace, link, start, end, include_bots):
    totals = _stat_queryset(workspace, link, start, end).aggregate(
        clicks=Sum("clicks"), unique_clicks=Sum("unique_clicks"), bot_clicks=Sum("bot_clicks")
    )
    clicks = totals["clicks"] or 0
    unique_clicks = totals["unique_clicks"] or 0
    bot_clicks = totals["bot_clicks"] or 0
    if not include_bots:
        clicks -= bot_clicks
    return clicks, unique_clicks, bot_clicks


def summary(workspace, link=None, *, start, end, include_bots=False):
    """Totals for [start, end], plus the same total clicks for the immediately
    preceding period of equal length and the percentage change between the two.

    `unique_clicks` always excludes bot clicks, the same way DailyLinkStat's own
    unique_clicks column does (see rollups._claim_identity): there is no
    "unique bot click" to include. `include_bots` only controls whether bot_clicks
    is folded back into `clicks` (and into `previous_clicks`, so the delta compares
    like with like).

    `delta_pct` is 0.0 when both periods have no clicks, and 100.0 when the previous
    period had none but this one does (a "0 to N" jump has no percentage of its own).
    """
    clicks, unique_clicks, bot_clicks = _totals(workspace, link, start, end, include_bots)
    period_days = (end - start).days + 1
    previous_end = start - timedelta(days=1)
    previous_start = previous_end - timedelta(days=period_days - 1)
    previous_clicks, _, _ = _totals(workspace, link, previous_start, previous_end, include_bots)
    if previous_clicks:
        delta_pct = round((clicks - previous_clicks) / previous_clicks * 100, 1)
    else:
        delta_pct = 100.0 if clicks else 0.0
    return {
        "clicks": clicks,
        "unique_clicks": unique_clicks,
        "bot_clicks": bot_clicks,
        "previous_clicks": previous_clicks,
        "delta_pct": delta_pct,
    }


def time_series(workspace, link=None, *, start, end, granularity="day", include_bots=False):
    """One point per day between start and end inclusive, zero-filled for any day
    with no DailyLinkStat row. `clicks` excludes bot clicks by default, the same
    default summary() uses and with the same arithmetic (subtracting bot_clicks from
    the day's total); `include_bots=True` folds them back in. `unique_clicks` never
    includes bots either way, the same as summary().

    `granularity` only accepts "day" for now. The parameter exists so a coarser mode
    (e.g. "week") can be added without changing every caller's signature, but no
    caller needs one yet, and an untested aggregation mode is worse than none --
    anything else raises rather than silently guessing what a caller wanted.
    """
    if granularity != "day":
        raise ValueError(f"Unsupported granularity: {granularity!r}")
    by_date = {
        row["date"]: row
        for row in _stat_queryset(workspace, link, start, end).values(
            "date", "clicks", "unique_clicks", "bot_clicks"
        )
    }
    points = []
    day = start
    while day <= end:
        row = by_date.get(day)
        if row:
            clicks = row["clicks"] if include_bots else (row["clicks"] - row["bot_clicks"])
        else:
            clicks = 0
        unique_clicks = row["unique_clicks"] if row else 0
        points.append({"date": day, "clicks": clicks, "unique_clicks": unique_clicks})
        day += timedelta(days=1)
    return points


def breakdown(workspace, dimension, link=None, *, start, end, limit=10, include_bots=False):
    """The top `limit` values of one Dimension by total clicks over [start, end],
    each with its share of that dimension's own total over the same range (not of
    overall traffic) as a percentage rounded to one decimal place.

    Bot clicks are excluded by default, the same default summary() uses, both from
    each value's own `clicks` and from the total its `share` is computed against;
    `include_bots=True` folds them back into both.
    """
    limit = _clamp_limit(limit)
    query = DailyLinkBreakdown.objects.filter(
        workspace=workspace, dimension=dimension, date__gte=start, date__lte=end
    )
    if link is not None:
        query = query.filter(link=link)
    clicks_sum = Sum("clicks") if include_bots else Sum("clicks") - Sum("bot_clicks")
    # Grouped once, unlimited: `share` needs the total across every value in range,
    # not just the ones that make the top `limit`, or a long tail outside the top N
    # would silently inflate the shares shown.
    grouped = list(query.values("value").annotate(clicks=clicks_sum).order_by("-clicks", "value"))
    total = sum(row["clicks"] for row in grouped)
    return [
        {
            "value": row["value"],
            "clicks": row["clicks"],
            "share": round(row["clicks"] / total * 100, 1) if total else 0.0,
        }
        for row in grouped[:limit]
    ]


def leaderboard(workspace, start, end, limit=10, include_bots=False):
    """The workspace's top `limit` links by total clicks over [start, end]. Bot
    clicks are excluded by default, the same default summary() and breakdown() use;
    `include_bots=True` folds them back in. Ties keep the query's own tie-break,
    ascending link id, so the order is deterministic and stable across calls.

    `rows` (below) already comes back in exactly that order, from ORDER BY -clicks,
    link_id; the return list is built by walking `rows` in that same order and only
    using Link.objects.in_bulk() as a lookup table for each row's code/title, rather
    than fetching Link objects and re-sorting them in Python -- a second sort with a
    different (or no) tie-break, against a queryset whose own default ordering
    (Link.Meta: "-created_at") has nothing to do with clicks, previously could and
    did disagree with the SQL order on a tie.

    A link deleted between the aggregate above and the in_bulk() lookup below is
    skipped rather than raising KeyError: the aggregate is already stale the moment
    that happens, and the rest of the leaderboard is still worth returning.
    """
    limit = _clamp_limit(limit)
    clicks_sum = Sum("clicks") if include_bots else Sum("clicks") - Sum("bot_clicks")
    rows = list(
        DailyLinkStat.objects.filter(workspace=workspace, date__gte=start, date__lte=end)
        .values("link_id")
        .annotate(clicks=clicks_sum)
        .order_by("-clicks", "link_id")[:limit]
    )
    links_by_id = Link.objects.only("pk", "code", "title").in_bulk(row["link_id"] for row in rows)
    result = []
    for row in rows:
        link_obj = links_by_id.get(row["link_id"])
        if link_obj is None:
            continue
        result.append({"code": link_obj.code, "title": link_obj.title, "clicks": row["clicks"]})
    return result


def recent_clicks(workspace, link, limit=20):
    """The link's most recent raw clicks, newest first, still within the retention
    window (CLICK_EVENT_RETENTION_DAYS): an event purge_click_events has already
    removed, or is about to, should never surface here even if the ClickEvent row
    momentarily still exists between purge runs.
    """
    limit = _clamp_limit(limit)
    cutoff = timezone.now() - timedelta(days=settings.CLICK_EVENT_RETENTION_DAYS)
    events = ClickEvent.objects.filter(
        workspace=workspace, link=link, occurred_at__gte=cutoff
    ).order_by("-occurred_at")[:limit]
    return [
        {
            "occurred_at": event.occurred_at,
            "country": event.country,
            "city": event.city,
            "device_type": event.device_type,
            "browser": event.browser,
            "referrer_host": event.referrer_host,
            "target_platform": event.target_platform,
        }
        for event in events
    ]


def hour_weekday_matrix(workspace, link, start, end, include_bots=False):
    """A 7x24 matrix (rows: local weekday, 0=Monday..6=Sunday; columns: local
    hour-of-day, 0-23) of click counts for one link over [start, end]. Bot clicks are
    excluded by default, the same default every other function here uses, by
    filtering on `is_bot`; `include_bots=True` includes them.

    Raw ClickEvent rows are queried in a UTC window from padded_utc_window(), wide
    enough to catch every event whose local day could fall in [start, end] under any
    timezone offset; each candidate is then converted with _zone() and only kept if
    its local date actually lands in range -- the same two-step
    apps.analytics.tasks.rebuild_daily_stats() uses for the same reason (and the
    same window helper). That window is also floored at CLICK_EVENT_RETENTION_DAYS,
    the same floor recent_clicks() applies: a raw ClickEvent this old has already
    been purged (or is about to be), so a `start` reaching further back than that is
    bounded rather than scanning a range that can never return anything for it.
    """
    zone = _zone(workspace)
    window_start, window_end = padded_utc_window(start, end)
    retention_floor = timezone.now() - timedelta(days=settings.CLICK_EVENT_RETENTION_DAYS)
    window_start = max(window_start, retention_floor)
    matrix = [[0] * 24 for _ in range(7)]
    events = ClickEvent.objects.filter(
        workspace=workspace, link=link, occurred_at__gte=window_start, occurred_at__lt=window_end
    )
    if not include_bots:
        events = events.filter(is_bot=False)
    events = events.only("occurred_at", "link_id", "workspace_id")
    for event in events.iterator():
        local = event.occurred_at.astimezone(zone)
        if start <= local.date() <= end:
            matrix[local.weekday()][local.hour] += 1
    return matrix


def export_rows(workspace, link, start, end):
    """Yield the link's daily stats for [start, end] as plain rows -- a header
    first, then one zero-filled row per day, the same shape time_series() fills its
    gaps with -- never pre-formatted CSV text: the caller (typically a streaming
    HTTP response) feeds each row through its own csv.writer.
    """
    yield ["date", "clicks", "unique_clicks", "bot_clicks"]
    by_date = {
        row["date"]: row
        for row in DailyLinkStat.objects.filter(
            workspace=workspace, link=link, date__gte=start, date__lte=end
        ).values("date", "clicks", "unique_clicks", "bot_clicks")
    }
    day = start
    while day <= end:
        row = by_date.get(day, {"clicks": 0, "unique_clicks": 0, "bot_clicks": 0})
        yield [day.isoformat(), row["clicks"], row["unique_clicks"], row["bot_clicks"]]
        day += timedelta(days=1)
