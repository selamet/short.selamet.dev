"""Daily rollups: DailyLinkStat and DailyLinkBreakdown, kept in sync incrementally as
clicks are recorded (see apply_event, called from apps.analytics.tasks.record_click),
and fully recomputable from raw ClickEvent rows at any time (see rebuild, meant for a
nightly job that corrects whatever the incremental path might have missed).
"""

import logging
import zoneinfo
from datetime import UTC, datetime, time, timedelta

from django.db import transaction
from django.db.models import F

from .models import ClickEvent, DailyLinkBreakdown, DailyLinkStat, Dimension

logger = logging.getLogger(__name__)

# ClickEvent field -> the Dimension it rolls up into.
_DIMENSION_FIELDS = (
    ("country", Dimension.COUNTRY),
    ("city", Dimension.CITY),
    ("referrer_host", Dimension.REFERRER),
    ("device_type", Dimension.DEVICE),
    ("os", Dimension.OS),
    ("browser", Dimension.BROWSER),
    ("utm_source", Dimension.UTM_SOURCE),
    ("utm_medium", Dimension.UTM_MEDIUM),
    ("utm_campaign", Dimension.UTM_CAMPAIGN),
    ("target_platform", Dimension.TARGET_PLATFORM),
)

_VALUE_MAX_LENGTH = DailyLinkBreakdown._meta.get_field("value").max_length


def _workspace_zone(workspace):
    try:
        return zoneinfo.ZoneInfo(workspace.timezone)
    except (zoneinfo.ZoneInfoNotFoundError, ValueError):
        logger.warning(
            "workspace %s has an unusable timezone %r; rolling up in UTC instead",
            workspace.pk,
            workspace.timezone,
        )
        return UTC


def local_date(event):
    """The calendar date `event.occurred_at` falls on in its workspace's own
    timezone, falling back to UTC when that timezone cannot be loaded."""
    return event.occurred_at.astimezone(_workspace_zone(event.workspace)).date()


def _day_bounds(workspace, day):
    """The [start, end) range of UTC instants that make up `day` in the workspace's
    own timezone."""
    zone = _workspace_zone(workspace)
    start = datetime.combine(day, time.min, tzinfo=zone)
    end = start + timedelta(days=1)
    return start.astimezone(UTC), end.astimezone(UTC)


def dimensions_for(event):
    """The non-empty (dimension, value) pairs this event contributes to, values
    truncated to the breakdown table's own column width."""
    pairs = []
    for field_name, dimension in _DIMENSION_FIELDS:
        value = getattr(event, field_name)
        if value:
            pairs.append((dimension, value[:_VALUE_MAX_LENGTH]))
    return pairs


def is_unique(event, day):
    """True when no earlier ClickEvent on the same link and day shares this event's
    ip_hash and user_agent.

    An empty ip_hash means we cannot tell visitors apart at all: refusing to count
    any of those clicks as unique would understate real unique reach more than
    treating each of them as unique overstates it, so an empty ip_hash always counts
    as unique.
    """
    if not event.ip_hash:
        return True
    start, _end = _day_bounds(event.workspace, day)
    return not ClickEvent.objects.filter(
        link_id=event.link_id,
        ip_hash=event.ip_hash,
        user_agent=event.user_agent,
        occurred_at__gte=start,
        occurred_at__lt=event.occurred_at,
    ).exists()


def _upsert(model, lookup, seed, deltas):
    """Add one event's contribution to a rollup row, creating the row first if it
    does not exist yet.

    Concurrency: PostgreSQL's ON CONFLICT DO UPDATE -- what
    bulk_create(update_conflicts=True, ...) compiles to -- always sets a column to
    EXCLUDED.<column>, the value carried by the incoming row, never
    table.<column> + EXCLUDED.<column>. There is no way to ask it to add to whatever
    is already stored, only to replace it, so it cannot express an increment and is
    the wrong tool here: two workers racing to record clicks for the same link and day
    would each overwrite the other's count instead of both being counted.
    get_or_create() plus an F()-based .update() gives the increment instead:
    get_or_create() already handles two workers racing to create the very same new
    row (the loser gets an IntegrityError from the unique constraint and re-fetches
    the winner's row instead of failing), and the F() update compiles to a single
    `UPDATE ... SET col = col + %s`, which PostgreSQL executes under that row's write
    lock, so concurrent increments from other workers serialize instead of clobbering
    one another. The only cost is that two workers creating the same brand-new row at
    the same instant can briefly block on each other; nothing here can under- or
    over-count a click.
    """
    obj, created = model.objects.get_or_create(**lookup, defaults={**seed, **deltas})
    if created:
        return
    changes = {field: F(field) + amount for field, amount in deltas.items() if amount}
    if changes:
        model.objects.filter(pk=obj.pk).update(**changes)


def apply_event(event):
    """Fold one click into its day's DailyLinkStat row and one DailyLinkBreakdown row
    per non-empty dimension it carries."""
    day = local_date(event)
    # Bot clicks are counted (bot_clicks, clicks) but never counted as unique,
    # regardless of what is_unique would otherwise say about their ip_hash/user_agent.
    unique = is_unique(event, day) and not event.is_bot
    _upsert(
        DailyLinkStat,
        lookup={"link": event.link, "date": day},
        seed={"workspace": event.workspace},
        deltas={
            "clicks": 1,
            "unique_clicks": int(unique),
            "bot_clicks": int(event.is_bot),
        },
    )
    for dimension, value in dimensions_for(event):
        _upsert(
            DailyLinkBreakdown,
            lookup={"link": event.link, "date": day, "dimension": dimension, "value": value},
            seed={"workspace": event.workspace},
            deltas={"clicks": 1},
        )


def rebuild(link, day):
    """Recompute both rollup tables for one link and day from the raw events,
    replacing whatever is currently stored. Runs inside one transaction so a reader
    never sees a half-rebuilt day."""
    workspace = link.workspace
    start, end = _day_bounds(workspace, day)
    events = ClickEvent.objects.filter(
        link=link, occurred_at__gte=start, occurred_at__lt=end
    ).order_by("occurred_at")

    totals = {"clicks": 0, "unique_clicks": 0, "bot_clicks": 0}
    breakdown_totals = {}
    seen = set()
    for event in events:
        totals["clicks"] += 1
        if event.is_bot:
            totals["bot_clicks"] += 1
        # Mirrors is_unique(): the first event for a given (ip_hash, user_agent) in
        # the day is the unique one, regardless of whether it (or a later repeat) is
        # a bot click; only non-bot events ever add to unique_clicks.
        fingerprint = (event.ip_hash, event.user_agent)
        first_seen = not event.ip_hash or fingerprint not in seen
        if first_seen and not event.is_bot:
            totals["unique_clicks"] += 1
        if event.ip_hash:
            seen.add(fingerprint)
        for dimension, value in dimensions_for(event):
            key = (dimension, value)
            breakdown_totals[key] = breakdown_totals.get(key, 0) + 1

    with transaction.atomic():
        DailyLinkStat.objects.filter(link=link, date=day).delete()
        DailyLinkBreakdown.objects.filter(link=link, date=day).delete()
        if totals["clicks"]:
            DailyLinkStat.objects.create(link=link, workspace=workspace, date=day, **totals)
        DailyLinkBreakdown.objects.bulk_create(
            DailyLinkBreakdown(
                link=link,
                workspace=workspace,
                date=day,
                dimension=dimension,
                value=value,
                clicks=clicks,
            )
            for (dimension, value), clicks in breakdown_totals.items()
        )
