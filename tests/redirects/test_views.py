from datetime import timedelta

import pytest
from django.test import Client
from django.utils import timezone

from apps.links import services as link_services
from tests.redirects.conftest import ANDROID_UA, DESKTOP_UA, IOS_UA

CRAWLER_UA = "facebookexternalhit/1.1"


def client_get(code, user_agent=DESKTOP_UA):
    return Client().get(f"/{code}", HTTP_USER_AGENT=user_agent)


class _recorder:
    """Stands in for `record_click`: records every enqueue call instead of scheduling
    a task."""

    def __init__(self, calls):
        self.calls = calls

    def enqueue(self, *args, **kwargs):
        self.calls.append((args, kwargs))


class _raiser:
    """Stands in for `record_click` when the enqueue itself should fail."""

    def enqueue(self, *args, **kwargs):
        raise RuntimeError("queue is down")


@pytest.mark.django_db
def test_expired_link_renders_the_expired_page(membership):
    link = link_services.create_link(
        membership,
        destination_url="https://example.com/a",
        code="old-one",
        expires_at=timezone.now() - timedelta(seconds=1),
    )
    response = client_get(link.code)
    assert response.status_code == 410
    assert "expired" in response.content.decode().lower()


@pytest.mark.django_db
def test_disabled_and_archived_links_render_the_disabled_page(membership, link):
    link_services.archive_link(membership, link)
    response = client_get(link.code)
    assert response.status_code == 403
    body = response.content.decode()
    assert "turned this link off" in body or "disabled" in body.lower()


@pytest.mark.django_db
def test_deep_link_page_offers_the_app_and_a_fallback(membership, link):
    link_services.update_link(
        membership,
        link,
        targets=[
            {
                "platform": "ios",
                "url": "",
                "app_url": "instagram://acme",
                "fallback_url": "https://m.example.com/ios",
            }
        ],
    )
    response = client_get(link.code, IOS_UA)
    assert response.status_code == 200
    body = response.content.decode()
    assert "instagram://acme" in body
    assert "https://m.example.com/ios" in body
    assert "noindex" in body
    assert "nonce=" in body
    assert "no-store" in response["Cache-Control"]


@pytest.mark.django_db
def test_android_target_without_an_app_url_redirects(membership, link):
    link_services.update_link(
        membership,
        link,
        targets=[
            {
                "platform": "android",
                "url": "https://m.example.com/android",
                "app_url": "",
                "fallback_url": "",
            }
        ],
    )
    response = client_get(link.code, ANDROID_UA)
    assert response.status_code == 302
    assert response["Location"] == "https://m.example.com/android"


@pytest.mark.django_db
def test_crawlers_get_a_card_and_no_redirect(membership):
    link = link_services.create_link(
        membership,
        destination_url="https://example.com/p",
        code="card-link",
        og_title="Spring drop",
        og_description="40 new pieces",
        og_image_url="https://cdn.example.com/c.png",
    )
    response = client_get(link.code, CRAWLER_UA)
    assert response.status_code == 200
    body = response.content.decode()
    assert 'property="og:title"' in body
    assert "Spring drop" in body
    assert "40 new pieces" in body
    assert "https://cdn.example.com/c.png" in body


@pytest.mark.django_db
def test_crawlers_do_not_record_a_click(membership, link, monkeypatch):
    calls = []
    monkeypatch.setattr("apps.redirects.views.record_click", _recorder(calls))
    client_get(link.code, CRAWLER_UA)
    assert calls == []
    client_get(link.code, DESKTOP_UA)
    assert len(calls) == 1


@pytest.mark.django_db
def test_a_failed_enqueue_still_redirects(link, monkeypatch, caplog):
    monkeypatch.setattr("apps.redirects.views.record_click", _raiser())
    response = client_get(link.code)
    assert response.status_code == 302
    assert "click was not recorded" in caplog.text


@pytest.mark.django_db
def test_preview_page_shows_where_the_link_goes(link):
    response = Client().get(f"/{link.code}+")
    assert response.status_code == 200
    body = response.content.decode()
    assert "example.com" in body
    assert "noindex" in body
    assert link.code in body
