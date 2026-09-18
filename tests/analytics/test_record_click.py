import pytest
from django.utils import timezone

from apps.analytics.models import ClickEvent
from apps.analytics.tasks import record_click
from apps.core.privacy import hash_ip
from apps.links.models import Link
from apps.redirects import cache as redirect_cache
from tests.redirects.conftest import DESKTOP_UA, IOS_UA

# The redirect view hashes the visitor's address before enqueuing the task (see
# apps/redirects/views.py::_record), so record_click never sees a raw address. This
# stands in for that already-hashed value.
IP_HASH = hash_ip("203.0.113.9")


def _record(link, **overrides):
    payload = {
        "occurred_at": timezone.now().isoformat(),
        "ip_hash": IP_HASH,
        "user_agent": DESKTOP_UA,
        "referrer": "https://www.instagram.com/acme/",
        "query_string": "utm_source=instagram&utm_medium=bio",
        "target_platform": "desktop",
    }
    payload.update(overrides)
    record_click.enqueue(link.pk, **payload)


@pytest.mark.django_db
def test_record_click_writes_an_event_and_increments_the_counter(link):
    _record(link)
    event = ClickEvent.objects.get()
    assert event.link_id == link.pk
    assert event.target_platform == "desktop"
    assert event.device_type == "desktop"
    assert event.browser
    assert event.referrer_host == "www.instagram.com"
    assert event.utm_source == "instagram"
    assert event.is_bot is False
    link.refresh_from_db()
    assert link.click_count == 1


@pytest.mark.django_db
def test_the_ip_hash_is_stored_as_given_and_never_re_hashed(link):
    # record_click receives an already-hashed value from the view; it must persist it
    # unchanged rather than hashing it a second time.
    _record(link)
    event = ClickEvent.objects.get()
    assert event.ip_hash == IP_HASH
    assert len(event.ip_hash) == 64


@pytest.mark.django_db
def test_the_referrer_query_string_is_dropped(link):
    _record(link, referrer="https://www.instagram.com/acme/?secret=token")
    event = ClickEvent.objects.get()
    assert "secret" not in event.referrer_url
    assert event.referrer_host == "www.instagram.com"


@pytest.mark.django_db
def test_a_bot_user_agent_is_flagged_but_still_recorded(link):
    _record(link, user_agent="Googlebot/2.1 (+http://www.google.com/bot.html)")
    event = ClickEvent.objects.get()
    assert event.is_bot is True
    link.refresh_from_db()
    assert link.click_count == 1


@pytest.mark.django_db
def test_platform_fields_come_from_the_user_agent(link):
    _record(link, user_agent=IOS_UA, target_platform="ios")
    event = ClickEvent.objects.get()
    assert event.device_type == "mobile"
    assert event.os == "iOS"


@pytest.mark.django_db
def test_recording_refreshes_the_cached_click_count(link):
    from apps.redirects import resolver

    resolver.resolve(link.code, DESKTOP_UA)
    _record(link)
    assert redirect_cache.get_payload(link.code)["click_count"] == 1


@pytest.mark.django_db
def test_a_deleted_link_is_skipped_quietly(link, caplog):
    link_id = link.pk
    Link.objects.filter(pk=link_id).delete()
    record_click.enqueue(
        link_id,
        occurred_at=timezone.now().isoformat(),
        ip_hash="",
        user_agent="",
        referrer="",
        query_string="",
        target_platform="desktop",
    )
    assert ClickEvent.objects.count() == 0
    assert "no longer exists" in caplog.text
