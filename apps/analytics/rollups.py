"""Daily rollups: DailyLinkStat and DailyLinkBreakdown, kept in sync incrementally as
clicks are recorded (see apply_event, called from apps.analytics.tasks.record_click),
and fully recomputable from raw ClickEvent rows at any time (see rebuild, meant for a
nightly job that corrects whatever the incremental path might have missed).
DailyClickIdentity backs both paths' notion of "unique": see _claim_identity.
"""

import hashlib
import logging
import zoneinfo
from datetime import UTC, datetime, time, timedelta

from django.db import IntegrityError, transaction
from django.db.models import F

from .models import ClickEvent, DailyClickIdentity, DailyLinkBreakdown, DailyLinkStat, Dimension

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


def _identity(ip_hash, user_agent):
    """A short, fixed-width key for one (ip_hash, user_agent) pair.

    Plain hashlib.sha256(...).hexdigest() -- the same idiom already used for exactly
    this kind of thing elsewhere in this codebase (apps.core.ratelimit.hashed_identity,
    apps.core.privacy.hash_ip, apps.accounts.services.hash_token) -- rather than a new
    hashing scheme: DailyClickIdentity.identity just needs a bounded, deterministic
    column to put a uniqueness constraint on, no matter how long a user_agent string
    turns out to be.
    """
    return hashlib.sha256(f"{ip_hash}:{user_agent}".encode()).hexdigest()


def _claim_identity(event, day):
    """True exactly when this event is the first click for its (ip_hash, user_agent)
    identity on this link and day; false for a bot click, which never claims one.

    Decided by attempting an INSERT, not by querying for an earlier event first: a
    query-then-decide check (the old is_unique()) has a race between the read and the
    write, since neither of two workers handling the same identity at the same time
    can see the other's still-uncommitted row -- both would see "no earlier event"
    and both would count themselves unique. Racing the INSERT against
    DailyClickIdentity's own unique constraint instead has no such window: PostgreSQL
    either accepts it (this click is the first for that identity today) or raises
    IntegrityError against a row another worker already committed (it is not), with
    nothing in between. Run in its own savepoint: catching IntegrityError inside the
    caller's still-open transaction would otherwise poison it for every query after
    (see the same reasoning on the nested atomic() around this call in
    apps.analytics.tasks.record_click).

    An empty ip_hash still claims an identity exactly like any other value, rather
    than always counting as unique the way the old is_unique() special-cased it: with
    a unique constraint now deciding this, "always unique" would mean skipping the
    claim entirely, which reopens the same race this function exists to close. Two
    different visitors who both end up with a blank ip_hash (a hashing failure, see
    apps.redirects.views._hashed_client_ip) and share a user agent will now collide
    and only the first is counted unique that day -- the same "we cannot fully tell
    these visitors apart" trade-off as before, just resolved the same way every other
    identity is rather than as a special case.
    """
    if event.is_bot:
        return False
    try:
        with transaction.atomic():
            DailyClickIdentity.objects.create(
                link=event.link,
                workspace=event.workspace,
                date=day,
                identity=_identity(event.ip_hash, event.user_agent),
            )
    except IntegrityError:
        return False
    return True


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
    unique = _claim_identity(event, day)
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
            deltas={"clicks": 1, "bot_clicks": int(event.is_bot)},
        )


def rebuild(link, day):
    """Recompute both rollup tables, and the day's DailyClickIdentity rows, for one
    link and day from the raw events, replacing whatever is currently stored. Runs
    inside one transaction so a reader never sees a half-rebuilt day.

    Uniqueness here follows exactly the same rule _claim_identity() enforces
    concurrently -- one DailyClickIdentity row per (link, date, identity), first
    occurrence wins -- rather than a second, parallel definition of "unique": this
    function is single-threaded and already walks the whole day in occurred_at
    order, so a plain set is enough to find each identity's first occurrence here,
    where DailyClickIdentity's unique constraint is what finds it under concurrent
    writers.

    The three deletes run before the events are read, not after: PostgreSQL's default
    READ COMMITTED isolation gives each statement in this transaction a fresh
    snapshot as of when that statement starts, not as of when the transaction opened,
    so reading the events after the delete (rather than before it, as a naive
    "collect the truth, then replace the rows" ordering would) means a concurrent
    apply_event() that commits its ClickEvent in the gap between the delete and the
    read is visible to the read and gets counted here; one that commits after the
    read has already started (and therefore after this rebuild has already decided
    the day's totals) instead lands its own increment through _upsert()'s
    get_or_create()/F()-update, which blocks on this transaction's row lock until it
    commits and then applies cleanly on top of what was just written. Either way,
    nothing that happens concurrently is silently lost -- reading first and deleting
    second, the order this replaced, could lose exactly such a click: read the old
    totals, have a new one commit, then delete and overwrite with the now-stale
    totals that never saw it.
    """
    workspace = link.workspace
    start, end = _day_bounds(workspace, day)

    with transaction.atomic():
        DailyLinkStat.objects.filter(link=link, date=day).delete()
        DailyLinkBreakdown.objects.filter(link=link, date=day).delete()
        DailyClickIdentity.objects.filter(link=link, date=day).delete()

        events = ClickEvent.objects.filter(
            link=link, occurred_at__gte=start, occurred_at__lt=end
        ).order_by("occurred_at")

        totals = {"clicks": 0, "unique_clicks": 0, "bot_clicks": 0}
        breakdown_totals = {}
        identities_seen = set()
        identities_to_create = []
        for event in events:
            totals["clicks"] += 1
            if event.is_bot:
                totals["bot_clicks"] += 1
            else:
                # A bot event never claims an identity (see _claim_identity), so it
                # can never block a later genuine click that happens to share one.
                identity = _identity(event.ip_hash, event.user_agent)
                if identity not in identities_seen:
                    identities_seen.add(identity)
                    identities_to_create.append(identity)
                    totals["unique_clicks"] += 1
            for dimension, value in dimensions_for(event):
                key = (dimension, value)
                row = breakdown_totals.setdefault(key, {"clicks": 0, "bot_clicks": 0})
                row["clicks"] += 1
                row["bot_clicks"] += int(event.is_bot)

        if totals["clicks"]:
            DailyLinkStat.objects.create(link=link, workspace=workspace, date=day, **totals)
        DailyLinkBreakdown.objects.bulk_create(
            DailyLinkBreakdown(
                link=link,
                workspace=workspace,
                date=day,
                dimension=dimension,
                value=value,
                clicks=row["clicks"],
                bot_clicks=row["bot_clicks"],
            )
            for (dimension, value), row in breakdown_totals.items()
        )
        DailyClickIdentity.objects.bulk_create(
            DailyClickIdentity(link=link, workspace=workspace, date=day, identity=identity)
            for identity in identities_to_create
        )
