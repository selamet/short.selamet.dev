from datetime import timedelta

import pytest
from django.utils import timezone

from apps.accounts import services
from apps.accounts.models import MagicLink, User


@pytest.fixture
def user(db):
    return User.objects.create_user(email="ada@example.com")


def test_get_or_create_user_is_case_insensitive(db):
    created = services.get_or_create_user("Ada@Example.com")
    again = services.get_or_create_user("ADA@example.com")
    assert created.pk == again.pk
    assert User.objects.count() == 1


def test_create_magic_link_stores_only_a_hash(user):
    raw = services.create_magic_link(user, ip_hash="abc")
    link = MagicLink.objects.get()
    assert len(raw) >= 43
    assert raw not in link.token_hash
    assert link.token_hash == services.hash_token(raw)
    assert link.ip_hash == "abc"
    assert link.used_at is None
    assert timedelta(minutes=14) < link.expires_at - timezone.now() <= timedelta(minutes=15)


def test_consume_magic_link_returns_user_once(user):
    raw = services.create_magic_link(user)
    assert services.consume_magic_link(raw) == user
    with pytest.raises(services.InvalidMagicLink):
        services.consume_magic_link(raw)


def test_consume_invalidates_the_users_other_unused_links(user):
    services.create_magic_link(user)
    raw2 = services.create_magic_link(user)
    raw3 = services.create_magic_link(user)

    services.consume_magic_link(raw2)

    remaining = MagicLink.objects.filter(user=user).exclude(token_hash=services.hash_token(raw2))
    assert remaining.count() == 2
    assert all(link.used_at is not None for link in remaining)
    with pytest.raises(services.InvalidMagicLink):
        services.consume_magic_link(raw3)


def test_consume_rejects_link_expiring_exactly_now(user, monkeypatch):
    raw = services.create_magic_link(user)
    frozen_now = timezone.now()
    MagicLink.objects.update(expires_at=frozen_now)
    monkeypatch.setattr("django.utils.timezone.now", lambda: frozen_now)
    with pytest.raises(services.InvalidMagicLink):
        services.consume_magic_link(raw)


def test_consume_rejects_expired_unknown_and_inactive(user):
    raw = services.create_magic_link(user)
    MagicLink.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
    with pytest.raises(services.InvalidMagicLink):
        services.consume_magic_link(raw)
    with pytest.raises(services.InvalidMagicLink):
        services.consume_magic_link("not-a-token")
    fresh = services.create_magic_link(user)
    user.is_active = False
    user.save()
    with pytest.raises(services.InvalidMagicLink):
        services.consume_magic_link(fresh)


def test_magic_link_url_uses_site_url(settings):
    settings.SITE_URL = "https://sho.rt"
    assert services.magic_link_url("tok") == "https://sho.rt/auth/verify/tok/"
