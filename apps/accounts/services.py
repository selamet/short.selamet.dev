"""Magic link lifecycle. Only hashes are stored; raw tokens live in the email and the URL."""

import hashlib
import secrets
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

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
        link.used_at = timezone.now()
        link.save(update_fields=["used_at"])
        return link.user


def magic_link_url(raw_token):
    return f"{settings.SITE_URL}{reverse('accounts:verify', args=[raw_token])}"
