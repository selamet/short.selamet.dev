from datetime import timedelta

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
