"""The redirect payload cache.

Values are plain JSON-safe dictionaries, never pickled models, so a schema change can
never make a cached entry undeserializable. A missing code is remembered too, so a scan
for short codes does not turn into a scan of the database. The key carries a version
(CACHE_VERSION) so a payload shape change never has to reconcile old-shape values left
over from a previous deployment; resolver._payload_for also treats an unexpected shape
on read as a miss, as a second line of defense.
"""

import logging

from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

MISS = "miss"

# Bump this whenever the payload shape built by payload_from_link changes, so a
# deployment never has to reconcile an old-shape value left over from before it: the
# new code simply misses on the old key and rebuilds under the new one.
CACHE_VERSION = "v1"


def key_for(code):
    return f"link:{CACHE_VERSION}:{code}"


def payload_from_link(link):
    return {
        "id": link.pk,
        "status": link.status,
        "destination_url": link.destination_url,
        "expires_at": link.expires_at.isoformat() if link.expires_at else None,
        "max_clicks": link.max_clicks,
        "click_count": link.click_count,
        "utm": {
            "utm_source": link.utm_source,
            "utm_medium": link.utm_medium,
            "utm_campaign": link.utm_campaign,
            "utm_content": link.utm_content,
            "utm_term": link.utm_term,
        },
        "og": {
            "title": link.og_title or link.title,
            "description": link.og_description,
            "image": link.og_image_url,
        },
        "targets": {
            target.platform: {
                "url": target.url,
                "app_url": target.app_url,
                "fallback_url": target.fallback_url,
            }
            for target in link.targets.all()
        },
    }


def get_payload(code):
    try:
        return cache.get(key_for(code))
    except Exception:
        logger.warning("cache unavailable while reading %s", code, exc_info=True)
        return None


def set_payload(code, payload):
    try:
        cache.set(key_for(code), payload, timeout=settings.REDIRECT_CACHE_TTL)
    except Exception:
        logger.warning("cache unavailable while writing %s", code, exc_info=True)


def set_miss(code):
    try:
        cache.set(key_for(code), MISS, timeout=settings.REDIRECT_MISS_TTL)
    except Exception:
        logger.warning("cache unavailable while writing a miss for %s", code, exc_info=True)


def invalidate(code):
    try:
        cache.delete(key_for(code))
    except Exception:
        logger.warning("cache unavailable while invalidating %s", code, exc_info=True)


def bump_click_count(code):
    """Nudge a cached payload's click_count by one so the resolver's expiry check sees
    a click that just happened without waiting for the entry to expire and reload from
    PostgreSQL. A no-op when nothing is cached for this code, including a cached miss.

    Reads and writes go through get_payload/set_payload, so a cache outage is already
    swallowed there and never raises here either.
    """
    payload = get_payload(code)
    if payload is None or payload == MISS:
        return
    payload["click_count"] = payload.get("click_count", 0) + 1
    set_payload(code, payload)
