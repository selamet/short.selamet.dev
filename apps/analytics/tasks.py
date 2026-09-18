"""Click recording: writes one ClickEvent per served redirect, off the request path.

Geographic resolution (country and city) is deliberately left blank here; GeoLite2
lookup belongs to the analytics issue that owns that database and its licensing.
"""

import logging

from django.db import transaction
from django.db.models import F
from django.tasks import task
from django.utils.dateparse import parse_datetime

from apps.links.models import Link

from . import rollups, useragent
from .models import ClickEvent

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
        link = Link.objects.get(pk=link_id)
    except Link.DoesNotExist:
        logger.warning("click recording skipped: link_id=%s no longer exists", link_id)
        return
    string_fields = {
        "ip_hash": ip_hash,
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
            workspace_id=link.workspace_id,
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
