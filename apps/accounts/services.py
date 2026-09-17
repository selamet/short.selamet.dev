"""Magic link lifecycle. Only hashes are stored; raw tokens live in the email and the URL."""

import hashlib
import secrets
import time
from datetime import timedelta

from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from apps.core import ratelimit
from apps.core.privacy import hash_ip

from .models import MagicLink, User


class InvalidMagicLink(Exception):
    """The token is unknown, expired, already used, or belongs to an inactive user."""


def hash_token(raw_token):
    return hashlib.sha256(raw_token.encode()).hexdigest()


def get_or_create_user(email):
    email = User.objects.normalize_email(email)
    user = User.objects.filter(email__iexact=email).first()
    return user or User.objects.create_user(email=email)


def create_magic_link(user, ip_hash=""):
    raw_token = secrets.token_urlsafe(32)
    MagicLink.objects.create(
        user=user,
        token_hash=hash_token(raw_token),
        ip_hash=ip_hash,
        expires_at=timezone.now() + timedelta(minutes=settings.MAGIC_LINK_TTL_MINUTES),
    )
    return raw_token


def consume_magic_link(raw_token):
    with transaction.atomic():
        try:
            link = (
                MagicLink.objects.select_for_update()
                .select_related("user")
                .get(token_hash=hash_token(raw_token))
            )
        except MagicLink.DoesNotExist:
            raise InvalidMagicLink from None
        if not link.is_valid() or not link.user.is_active:
            raise InvalidMagicLink
        now = timezone.now()
        link.used_at = now
        link.save(update_fields=["used_at"])
        # Signing in with one link invalidates any other outstanding links for the
        # same user, so an older, still-unused link can't be used after the fact.
        MagicLink.objects.filter(user=link.user, used_at__isnull=True).update(used_at=now)
        return link.user


def magic_link_url(raw_token):
    return f"{settings.SITE_URL}{reverse('accounts:verify', args=[raw_token])}"


def _cooldown_key(email):
    return f"magic-link-cooldown:{ratelimit.hashed_identity(email.lower())}"


def start_cooldown(email):
    seconds = settings.MAGIC_LINK_RESEND_COOLDOWN_SECONDS
    if seconds:
        cache.set(_cooldown_key(email), time.time() + seconds, timeout=seconds)


def cooldown_remaining(email):
    expires = cache.get(_cooldown_key(email))
    return max(0, int(expires - time.time())) if expires else 0


def request_magic_link(email, ip):
    """Enqueue a link for the email unless a rate limit is hit. Returns the user, or None."""
    # Imported lazily: apps.accounts.tasks imports this module at module load time.
    from .tasks import send_magic_link

    allowed_for_email = ratelimit.hit(
        "magic-link-email",
        email.lower(),
        limit=settings.MAGIC_LINK_RATE_PER_EMAIL,
        window=settings.MAGIC_LINK_RATE_PER_EMAIL_WINDOW,
    )
    allowed_for_ip = ratelimit.hit(
        "magic-link-ip",
        ip,
        limit=settings.MAGIC_LINK_RATE_PER_IP,
        window=settings.MAGIC_LINK_RATE_PER_IP_WINDOW,
    )
    if not (allowed_for_email and allowed_for_ip):
        return None
    user = get_or_create_user(email)
    send_magic_link.enqueue(user.pk, ip_hash=hash_ip(ip))
    start_cooldown(user.email)
    return user
