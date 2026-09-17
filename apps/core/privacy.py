"""Privacy helpers: IPs are only ever stored as a hash salted with a per-day secret."""

import hashlib
import secrets
from datetime import datetime, time, timedelta

from django.core.cache import cache
from django.utils import timezone

SALT_GRACE_SECONDS = 60 * 60


def salt_timeout(now):
    """Seconds until the end of now's UTC day, plus a grace period.

    Keeping the salt only slightly past midnight (rather than a flat 48h) limits how
    long a given day's salt, and therefore its hashed IPs, stay correlatable.
    """
    midnight = datetime.combine(now.date() + timedelta(days=1), time.min, tzinfo=now.tzinfo)
    return int((midnight - now).total_seconds()) + SALT_GRACE_SECONDS


def daily_salt(day=None):
    day = day or timezone.now().date()
    return cache.get_or_set(
        f"ipsalt:{day.isoformat()}",
        lambda: secrets.token_hex(16),
        timeout=salt_timeout(timezone.now()),
    )


def hash_ip(ip):
    if not ip:
        return ""
    return hashlib.sha256(f"{daily_salt()}:{ip}".encode()).hexdigest()
