"""Click recording: writes one ClickEvent per served redirect, off the request path.

Geographic resolution happens in the view, not here (see apps.redirects.views._record
and apps.analytics.geo): the raw address never reaches this task, and by the time an
address has been resolved to a country and city it is no longer needed, so `country`
and `city` arrive already resolved, as two short strings.
"""

import logging
from datetime import date, timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import F, Q
from django.tasks import task
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from apps.core import privacy
from apps.links import services as link_services
from apps.links.models import Link

from . import rollups, useragent
from .models import ClickEvent, DailyClickIdentity
from .queries import _padded_utc_window

logger = logging.getLogger(__name__)


def _truncated(field_name, value):
    """Clip a value to its ClickEvent field's own max_length, reading the limit off
    the model rather than repeating it, so an overlong value (an implausibly long UTM
    parameter, a stuffed referrer) never turns into a lost click: without this, the
    INSERT below raises DataError in the asynchronous production path, where there is
    no request-level length guard left to catch it, and the event, the counter
    increment and the cache bump are all lost with it.
    """
    max_length = ClickEvent._meta.get_field(field_name).max_length
    return (value or "")[:max_length]


@task
def record_click(
    link_id,
    *,
    occurred_at,
    ip_hash,
    user_agent,
    referrer_host,
    referrer_url,
    utm_source,
    utm_medium,
    utm_campaign,
    utm_content,
    utm_term,
    target_platform,
    country,
    city,
):
    """Record one click. Takes `referrer_host`/`referrer_url` and the five UTM values
    already split out of the raw referrer and query string (see
    `apps.analytics.attribution`), never the raw values themselves: the production
    task backend persists its arguments to the database, and credentials or an
    unbounded query string must never reach that table.

    Not idempotent against a retried task: a redelivered call would write a second
    ClickEvent and double-count. Deferred, because the database backend in use here
    does not retry a task today; worth revisiting if that changes.
    """
    try:
        # select_related: rollups.apply_event() below reads event.workspace (for the
        # day's timezone and to stamp the rollup rows); without this, that would be a
        # second query on every single click, since ClickEvent.objects.create() below
        # is given workspace_id, not the workspace object.
        link = Link.objects.select_related("workspace").get(pk=link_id)
    except Link.DoesNotExist:
        logger.warning("click recording skipped: link_id=%s no longer exists", link_id)
        return
    string_fields = {
        "ip_hash": ip_hash,
        "country": country,
        "city": city,
        "device_type": useragent.device_type(user_agent),
        "os": useragent.operating_system(user_agent),
        "browser": useragent.browser(user_agent),
        "referrer_host": referrer_host,
        "referrer_url": referrer_url,
        "target_platform": target_platform,
        "user_agent": user_agent,
        "utm_source": utm_source,
        "utm_medium": utm_medium,
        "utm_campaign": utm_campaign,
        "utm_content": utm_content,
        "utm_term": utm_term,
    }
    # The event write and the counter update land together or not at all; the cache
    # increment happens after, outside the transaction, since it is best-effort and a
    # cache outage must never roll back a successful write.
    with transaction.atomic():
        event = ClickEvent.objects.create(
            link=link,
            workspace=link.workspace,
            occurred_at=parse_datetime(occurred_at),
            is_bot=useragent.is_bot(user_agent),
            **{name: _truncated(name, value) for name, value in string_fields.items()},
        )
        Link.objects.filter(pk=link_id).update(click_count=F("click_count") + 1)
        try:
            # Its own savepoint, not just a try/except: an exception raised while the
            # outer atomic() block is still open would otherwise poison it (Postgres
            # refuses any further query on a transaction that hit a database error),
            # which would lose the ClickEvent and the counter update above along with
            # the rollup. The nested atomic() rolls back only the rollup's own writes
            # on failure, leaving the outer transaction free to commit.
            with transaction.atomic():
                rollups.apply_event(event)
        except Exception:
            # The event and the counter above are what matters; losing today's rollup
            # for this one click is recoverable (the nightly rebuild recomputes the day
            # from raw events), losing the click itself is not, so a rollup failure is
            # logged and swallowed rather than allowed to roll back the write above.
            logger.exception("rollup failed for click on link_id=%s", link_id)
    # Imported lazily to keep the app dependency one-directional: apps.redirects
    # already imports apps.analytics.tasks (to enqueue this very task), so a
    # module-level import here would be circular.
    from apps.redirects import cache as redirect_cache

    redirect_cache.bump_click_count(link.code, seed=link.click_count)


# The four scheduled jobs below (expire_links included) all live in this module,
# rather than each in the app that owns the model it touches: they are only ever
# enqueued together, by the same crontab (see docker/crontab), and there is exactly
# one place an operator needs to look to see everything that runs on a schedule.
# expire_links is a link concern in every other sense -- see apps.links.services for
# the rest of that lifecycle -- but a scheduled one, and that outweighs app purity
# here.


def _coerce_day(day):
    """Accept either a date (the natural type for a direct call, e.g. from a shell)
    or an ISO date string (what a JSON-serializing task backend, such as
    django_tasks_db in production, hands back on execution) -- the same trade-off
    record_click() above makes for occurred_at."""
    if day is None or isinstance(day, date):
        return day
    return date.fromisoformat(day)


@task
def rebuild_daily_stats(day=None):
    """Recompute DailyLinkStat, DailyLinkBreakdown and DailyClickIdentity for `day`
    (UTC yesterday by default) for every link with at least one click that day,
    correcting anything the incremental path in rollups.apply_event() might have
    missed. Meant to run once a night; also callable with an explicit date (a date
    or an ISO string) to repair or backfill a single day.

    Each workspace picks its own timezone (Workspace.timezone), so which raw
    ClickEvent rows actually fall on `day` differs link by link. Rather than
    duplicating that per-workspace conversion here, this scans every event in a
    window wide enough to cover any timezone offset (see
    apps.analytics.queries._padded_utc_window, shared with hour_weekday_matrix()
    there) and asks rollups.local_date() -- the same function apply_event() itself
    uses -- which day each one lands on.
    """
    day = _coerce_day(day) or (timezone.now().date() - timedelta(days=1))
    window_start, window_end = _padded_utc_window(day, day)
    candidates = ClickEvent.objects.filter(
        occurred_at__gte=window_start, occurred_at__lt=window_end
    ).select_related("workspace")
    link_ids = {
        event.link_id for event in candidates.iterator() if rollups.local_date(event) == day
    }
    for link in Link.objects.filter(pk__in=link_ids).select_related("workspace"):
        rollups.rebuild(link, day)
    logger.info("rebuild_daily_stats day=%s links=%d", day, len(link_ids))


def _delete_in_batches(queryset, batch_size):
    """Delete every row `queryset` matches, `batch_size` rows at a time, so clearing
    a large backlog never holds one long-running DELETE (and its locks) for the
    whole set. Returns the total number of rows removed."""
    model = queryset.model
    total = 0
    while True:
        ids = list(queryset.order_by("pk").values_list("pk", flat=True)[:batch_size])
        if not ids:
            break
        deleted, _ = model.objects.filter(pk__in=ids).delete()
        total += deleted
    return total


@task
def purge_click_events():
    """Delete ClickEvent rows older than CLICK_EVENT_RETENTION_DAYS, and the
    DailyClickIdentity rows for the same cutoff date, in batches of
    ANALYTICS_PURGE_BATCH_SIZE. DailyLinkStat and DailyLinkBreakdown are never
    touched here: they are the entire point of keeping rollups once the raw events
    behind them are gone.

    DailyClickIdentity carries no foreign key to ClickEvent (see its docstring in
    apps.analytics.models: it exists purely so rollups._claim_identity() has
    something to race an INSERT against, keyed by (link, date, identity), not by
    event), so deleting ClickEvent rows never cascades into it -- it has to be
    purged here explicitly, by the same cutoff, or it would grow forever.
    """
    cutoff = timezone.now() - timedelta(days=settings.CLICK_EVENT_RETENTION_DAYS)
    batch_size = settings.ANALYTICS_PURGE_BATCH_SIZE
    events_deleted = _delete_in_batches(
        ClickEvent.objects.filter(occurred_at__lt=cutoff), batch_size
    )
    identities_deleted = _delete_in_batches(
        DailyClickIdentity.objects.filter(date__lt=cutoff.date()), batch_size
    )
    logger.info(
        "purge_click_events cutoff=%s events=%d identities=%d",
        cutoff.date(),
        events_deleted,
        identities_deleted,
    )


@task
def rotate_ip_salt():
    """Force today's IP-hashing salt (apps.core.privacy) to rotate right at
    midnight rather than lazily on the day's first click, so every click after
    midnight salts under a value this job picked, not whichever request got there
    first."""
    privacy.rotate_salt()


@task
def expire_links():
    """Disable every active link that has passed its expires_at or reached
    max_clicks, invalidating each one's cached redirect payload through
    apps.links.services.invalidate_cache rather than reaching into the redirect
    cache directly, so this stays the one place that knows how that cache entry
    gets cleared.

    The primary keys of the links to disable are captured first, then the UPDATE is
    issued against exactly that list (`pk__in`), never by re-running the
    expires_at/max_clicks filter a second time. Re-running it would race: a link
    that only becomes eligible in the gap between the two statements (a click
    landing right as this runs, pushing click_count past max_clicks) would then be
    disabled by an update() that re-evaluated the filter, without its code ever
    having been captured for invalidate_cache -- disabled, but still serving its
    old cached payload until the cache entry's own TTL expires. Scoping the update
    to the captured primary keys instead means exactly the links that get disabled
    are exactly the ones invalidated, every time; a link that turns eligible mid-run
    is simply left for the next run (this job runs every 10 minutes, see
    docker/crontab) rather than raced.
    """
    now = timezone.now()
    with transaction.atomic():
        due = Link.objects.filter(status=Link.Status.ACTIVE).filter(
            Q(expires_at__lt=now) | Q(max_clicks__isnull=False, click_count__gte=F("max_clicks"))
        )
        pks_and_codes = list(due.values_list("pk", "code"))
        if not pks_and_codes:
            return
        pks = [pk for pk, _code in pks_and_codes]
        codes = [code for _pk, code in pks_and_codes]
        updated = Link.objects.filter(pk__in=pks).update(status=Link.Status.DISABLED)
    link_services.invalidate_cache(*codes)
    logger.info("expire_links disabled=%d", updated)
