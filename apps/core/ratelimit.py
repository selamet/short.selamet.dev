"""Fixed-window rate limiting on top of Django's cache API."""

from django.core.cache import cache


def hit(scope, identity, limit, window):
    """Record one event for (scope, identity). Return True while the count stays within limit."""
    key = f"rl:{scope}:{identity}"
    cache.add(key, 0, timeout=window)
    try:
        count = cache.incr(key)
    except ValueError:
        # The key expired between add and incr; start a new window.
        cache.add(key, 0, timeout=window)
        count = cache.incr(key)
    return count <= limit
