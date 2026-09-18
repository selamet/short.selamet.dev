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


def clicks_key_for(code):
    return f"{key_for(code)}:clicks"


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


def get_click_count(code):
    """The atomically incremented click counter for a code, kept in its own key
    entirely outside the cached payload (see bump_click_count). None when nothing is
    cached for it: a cache outage, or no click has bumped it since the payload was
    last (re)cached, in which case the caller falls back to the payload's own
    click_count.
    """
    try:
        return cache.get(clicks_key_for(code))
    except Exception:
        logger.warning(
            "cache unavailable while reading the click count for %s", code, exc_info=True
        )
        return None


def bump_click_count(code, seed):
    """Atomically increment the click counter kept outside the cached payload by one.

    Deliberately never reads or writes the payload itself: the previous version nudged
    click_count inside the cached payload on every click, which could rewrite a stale
    payload with a fresh TTL right after an edit had invalidated it, resurrecting data
    the edit meant to throw away. Counting in a separate key removes that interaction
    entirely, and using cache.incr makes the count itself atomic against concurrent
    clicks (the previous read-modify-write on the payload could lose increments under
    concurrency; this cannot).

    `seed` is the database's click_count from just before this click, used to prime
    the counter the first time it is touched after a cache miss (an edit's
    invalidation, a cold cache, an eviction) so it picks up where PostgreSQL left off
    instead of restarting at zero. `cache.add` is a no-op once the key exists, so
    `seed` is ignored on every call after the first.
    """
    key = clicks_key_for(code)
    try:
        cache.add(key, seed, timeout=settings.REDIRECT_CACHE_TTL)
        return cache.incr(key)
    except ValueError:
        # The key expired between add and incr; retry once with a fresh seed.
        try:
            cache.add(key, seed, timeout=settings.REDIRECT_CACHE_TTL)
            return cache.incr(key)
        except Exception:
            logger.warning(
                "cache unavailable while bumping the click count for %s", code, exc_info=True
            )
            return None
    except Exception:
        logger.warning(
            "cache unavailable while bumping the click count for %s", code, exc_info=True
        )
        return None
