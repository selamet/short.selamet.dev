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
from apps.redirects import cache as redirect_cache

from . import useragent
from .models import ClickEvent

logger = logging.getLogger(__name__)

UTM_FIELDS = ("utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term")


def _split_referrer(referrer):
    """The referrer's host and a query-and-fragment-free URL, or `("", "")` when there
    is no referrer to parse."""
    if not referrer:
        return "", ""
    parts = urlsplit(referrer)
    if not parts.netloc:
        return "", ""
    clean_url = urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
    return parts.netloc, clean_url


def _utm_from_query_string(query_string):
    params = parse_qs(query_string or "")
    return {field: (params.get(field) or [""])[0] for field in UTM_FIELDS}


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
    ClickEvent.objects.create(
        link=link,
        occurred_at=parse_datetime(occurred_at),
        ip_hash=ip_hash,
        device_type=useragent.device_type(user_agent),
        os=useragent.operating_system(user_agent),
        browser=useragent.browser(user_agent),
        referrer_host=referrer_host,
        referrer_url=referrer_url,
        target_platform=target_platform,
        is_bot=useragent.is_bot(user_agent),
        user_agent=(user_agent or "")[:256],
        **_utm_from_query_string(query_string),
    )
    Link.objects.filter(pk=link_id).update(click_count=F("click_count") + 1)
    redirect_cache.bump_click_count(link.code)
