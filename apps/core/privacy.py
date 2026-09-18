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


def ensure_daily_salt(day=None):
    """Make sure `day`'s (today's by default) salt already exists in the cache,
    without ever replacing one that is already there.

    This used to be rotate_salt(): it forced a fresh token into place unconditionally,
    on the theory that nothing else would force that rotation to happen right at
    local midnight, so whichever click was first to hash an IP after midnight would
    otherwise decide the whole day's salt. That reasoning missed that daily_salt() may
    already have created -- and clicks may already be hashing IPs against -- today's
    salt by the time this runs (this job can simply run a little late, or a click can
    land in the same instant); replacing it out from under those clicks meant one
    visitor who clicked before and after the "rotation" got two different hashes, two
    DailyClickIdentity rows and two unique clicks for what was really one visitor, and
    rollups.rebuild() reproduced that same inflated count from the raw events, since
    both hashes are equally real ClickEvent rows.

    daily_salt()'s own get_or_set() already gives exactly one salt per day; calling
    it here (rather than reimplementing that with cache.add()) makes today's salt
    exist a little earlier -- right at midnight rather than lazily on the day's first
    click -- without ever being able to replace one already in use, which is all this
    job needs to do (see apps.analytics.tasks.rotate_ip_salt).
    """
    return daily_salt(day)


def hash_ip(ip):
    if not ip:
        return ""
    return hashlib.sha256(f"{daily_salt()}:{ip}".encode()).hexdigest()
