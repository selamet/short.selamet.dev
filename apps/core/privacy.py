"""Privacy helpers: IPs are only ever stored as a hash salted with a per-day secret."""

import hashlib
import secrets

from django.core.cache import cache
from django.utils import timezone

SALT_TTL_SECONDS = 60 * 60 * 48


def daily_salt(day=None):
    day = day or timezone.now().date()
    return cache.get_or_set(
        f"ipsalt:{day.isoformat()}", lambda: secrets.token_hex(16), timeout=SALT_TTL_SECONDS
    )


def hash_ip(ip):
    if not ip:
        return ""
    return hashlib.sha256(f"{daily_salt()}:{ip}".encode()).hexdigest()
