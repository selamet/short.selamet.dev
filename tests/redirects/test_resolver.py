from datetime import timedelta

import pytest
from django.utils import timezone

from apps.links import services as link_services
from apps.links.models import Link
from apps.redirects import cache as redirect_cache
from apps.redirects import resolver
from tests.redirects.conftest import ANDROID_UA, DESKTOP_UA, IOS_UA


def test_resolve_returns_the_destination_and_caches_it(link, django_assert_num_queries):
    first = resolver.resolve(link.code, DESKTOP_UA)
    assert first.url == "https://example.com/p"
    assert first.platform == "desktop"
    assert redirect_cache.get_payload(link.code) is not None
    with django_assert_num_queries(0):
        second = resolver.resolve(link.code, DESKTOP_UA)
    assert second.url == first.url


def test_resolve_is_case_insensitive_on_the_code(link):
    assert resolver.resolve(link.code.upper(), DESKTOP_UA).url == link.destination_url


def test_unknown_code_returns_none_and_negative_caches(db, django_assert_num_queries):
    assert resolver.resolve("missing", DESKTOP_UA) is None
    with django_assert_num_queries(0):
        assert resolver.resolve("missing", DESKTOP_UA) is None


def test_reserved_and_malformed_codes_never_touch_the_database(db, django_assert_num_queries):
    with django_assert_num_queries(0):
        assert resolver.resolve("admin", DESKTOP_UA) is None
        assert resolver.resolve("a b", DESKTOP_UA) is None
        assert resolver.resolve("", DESKTOP_UA) is None


def test_device_targets_win_over_the_default(membership, link):
    link_services.update_link(
        membership,
        link,
        targets=[
            {
                "platform": "ios",
                "url": "",
                "app_url": "instagram://acme",
                "fallback_url": "https://m.example.com/ios",
            },
            {
                "platform": "android",
                "url": "https://m.example.com/android",
                "app_url": "",
                "fallback_url": "",
            },
        ],
    )
    ios = resolver.resolve(link.code, IOS_UA)
    assert ios.app_url == "instagram://acme"
    assert ios.fallback_url == "https://m.example.com/ios"
    android = resolver.resolve(link.code, ANDROID_UA)
    assert android.url == "https://m.example.com/android"
    assert android.app_url == ""
    desktop = resolver.resolve(link.code, DESKTOP_UA)
    assert desktop.url == "https://example.com/p"


def test_utm_parameters_are_merged_without_overriding(membership):
    link = link_services.create_link(
        membership,
        destination_url="https://example.com/p?utm_source=keep",
        code="utm-link",
        utm_source="instagram",
        utm_medium="bio",
    )
    resolution = resolver.resolve(link.code, DESKTOP_UA)
    assert "utm_source=keep" in resolution.url
    assert "utm_medium=bio" in resolution.url


def test_expired_by_date_and_by_clicks(membership):
    by_date = link_services.create_link(
        membership,
        destination_url="https://example.com/a",
        code="old-link",
        expires_at=timezone.now() - timedelta(seconds=1),
    )
    assert resolver.resolve(by_date.code, DESKTOP_UA).expired is True
    by_clicks = link_services.create_link(
        membership, destination_url="https://example.com/b", code="used-up", max_clicks=5
    )
    Link.objects.filter(pk=by_clicks.pk).update(click_count=5)
    redirect_cache.invalidate(by_clicks.code)
    assert resolver.resolve(by_clicks.code, DESKTOP_UA).expired is True


def test_disabled_and_archived_links_resolve_with_their_status(membership, link):
    link_services.archive_link(membership, link)
    resolution = resolver.resolve(link.code, DESKTOP_UA)
    assert resolution.status == "archived"


def test_resolve_falls_back_to_the_database_when_the_cache_is_down(link, monkeypatch):
    monkeypatch.setattr("apps.redirects.cache.get_payload", lambda code: None)
    monkeypatch.setattr("apps.redirects.cache.set_payload", lambda code, payload: None)
    assert resolver.resolve(link.code, DESKTOP_UA).url == link.destination_url


def test_a_missing_generated_length_code_creates_a_negative_cache_entry(db, settings):
    settings.LINK_CODE_LENGTH = 7
    code = "abcd234"  # 7 chars, all drawn from codes.ALPHABET
    assert resolver.resolve(code, DESKTOP_UA) is None
    assert redirect_cache.get_payload(code) == redirect_cache.MISS


def test_a_missing_short_custom_code_creates_a_negative_cache_entry(db):
    code = "a-plausible-code"  # short enough to be a typed custom code
    assert resolver.resolve(code, DESKTOP_UA) is None
    assert redirect_cache.get_payload(code) == redirect_cache.MISS


def test_a_long_random_code_does_not_create_a_negative_cache_entry(db):
    code = "x" * 35  # valid per CODE_RE, but far too long to be worth remembering
    assert resolver.resolve(code, DESKTOP_UA) is None
    assert redirect_cache.get_payload(code) is None


@pytest.mark.parametrize("corrupt_payload", ["just a string", ["a", "list"]])
def test_a_non_dict_payload_falls_back_to_the_database(link, corrupt_payload):
    redirect_cache.set_payload(link.code, corrupt_payload)
    resolution = resolver.resolve(link.code, DESKTOP_UA)
    assert resolution.url == link.destination_url
    # The bad value is replaced by a fresh, well-shaped one.
    assert redirect_cache.get_payload(link.code) != corrupt_payload


def test_a_payload_missing_og_falls_back_to_the_database(link):
    payload = redirect_cache.payload_from_link(link)
    del payload["og"]
    redirect_cache.set_payload(link.code, payload)
    resolution = resolver.resolve(link.code, DESKTOP_UA)
    assert resolution.url == link.destination_url
    assert "og" in redirect_cache.get_payload(link.code)


def test_a_payload_missing_targets_falls_back_to_the_database(link):
    payload = redirect_cache.payload_from_link(link)
    del payload["targets"]
    redirect_cache.set_payload(link.code, payload)
    resolution = resolver.resolve(link.code, DESKTOP_UA)
    assert resolution.url == link.destination_url
    assert "targets" in redirect_cache.get_payload(link.code)


def test_a_bad_expires_at_is_treated_as_not_expired(link):
    payload = redirect_cache.payload_from_link(link)
    payload["expires_at"] = "not-a-date"
    redirect_cache.set_payload(link.code, payload)
    assert resolver.resolve(link.code, DESKTOP_UA).expired is False


def test_a_naive_expires_at_is_treated_as_not_expired(link):
    payload = redirect_cache.payload_from_link(link)
    # No timezone, unlike the isoformat() output payload_from_link normally stores.
    payload["expires_at"] = "2020-01-01T00:00:00"
    redirect_cache.set_payload(link.code, payload)
    assert resolver.resolve(link.code, DESKTOP_UA).expired is False
