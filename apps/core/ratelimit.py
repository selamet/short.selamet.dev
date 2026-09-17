"""Fixed-window rate limiting on top of Django's cache API."""

import hashlib

from django.core.cache import cache


def hashed_identity(value):
    """Short, non-reversible form of a cache identity, so raw emails/IPs never enter the cache."""
    return hashlib.sha256(value.encode()).hexdigest()[:32]


def hit(scope, identity, limit, window):
    """Record one event for (scope, identity). Return True while the count stays within limit."""
    key = f"rl:{scope}:{hashed_identity(identity)}"
    for _ in range(2):
        cache.add(key, 0, timeout=window)
        try:
            count = cache.incr(key)
            return count <= limit
        except ValueError:
            # The key expired between add and incr; retry once with a fresh window.
            continue
    return False
