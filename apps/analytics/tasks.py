"""Click recording: writes one ClickEvent per served redirect, off the request path.

Geographic resolution (country and city) is deliberately left blank here; GeoLite2
lookup belongs to the analytics issue that owns that database and its licensing.
"""

import logging
from urllib.parse import parse_qs, urlsplit, urlunsplit

from django.db.models import F
from django.tasks import task
from django.utils.dateparse import parse_datetime

from apps.links.models import Link

from . import useragent
from .models import ClickEvent

logger = logging.getLogger(__name__)

UTM_FIELDS = ("utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term")


def _split_referrer(referrer):
    """The referrer's host and a credential-and-query-and-fragment-free URL, or
    `("", "")` when there is no referrer to parse.

    Built from `hostname`/`port`, not `netloc`, so any userinfo (`user:pass@`) in the
    original URL is dropped along with the query string and fragment rather than
    ending up stored.
    """
    if not referrer:
        return "", ""
    parts = urlsplit(referrer)
    host = parts.hostname or ""
    if not host:
        return "", ""
    netloc = f"[{host}]" if ":" in host else host
    if parts.port:
        netloc = f"{netloc}:{parts.port}"
    clean_url = urlunsplit((parts.scheme, netloc, parts.path, "", ""))
    return host, clean_url


def _utm_from_query_string(query_string):
    params = parse_qs(query_string or "")
    return {field: (params.get(field) or [""])[0] for field in UTM_FIELDS}


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
    link_id, *, occurred_at, ip_hash, user_agent, referrer, query_string, target_platform
):
    try:
        link = Link.objects.get(pk=link_id)
    except Link.DoesNotExist:
        logger.warning("click recording skipped: link_id=%s no longer exists", link_id)
        return
    referrer_host, referrer_url = _split_referrer(referrer)
    string_fields = {
        "ip_hash": ip_hash,
        "device_type": useragent.device_type(user_agent),
        "os": useragent.operating_system(user_agent),
        "browser": useragent.browser(user_agent),
        "referrer_host": referrer_host,
        "referrer_url": referrer_url,
        "target_platform": target_platform,
        "user_agent": user_agent,
        **_utm_from_query_string(query_string),
    }
    ClickEvent.objects.create(
        link=link,
        occurred_at=parse_datetime(occurred_at),
        is_bot=useragent.is_bot(user_agent),
        **{name: _truncated(name, value) for name, value in string_fields.items()},
    )
    Link.objects.filter(pk=link_id).update(click_count=F("click_count") + 1)
    # Imported lazily to keep the app dependency one-directional: apps.redirects
    # already imports apps.analytics.tasks (to enqueue this very task), so a
    # module-level import here would be circular.
    from apps.redirects import cache as redirect_cache

    redirect_cache.bump_click_count(link.code)
