import pytest
from django.urls import reverse

from apps.links import destinations, services
from apps.links.models import Link


def url(name, slug="acme-social", *args):
    return reverse(f"links:{name}", args=[slug, *args])


@pytest.fixture
def member_client(client, owner_membership):
    client.force_login(owner_membership.user)
    return client


@pytest.fixture(autouse=True)
def _fake_dns(monkeypatch):
    """The service layer resolves every destination before saving it (I6); stub the
    resolver so these tests never perform a real DNS lookup. Tests exercising the
    resolution failure/private-address paths override this per test."""
    monkeypatch.setattr(destinations, "resolve_host", lambda host, timeout: ["93.184.216.34"])


def test_create_page_renders_form(member_client, workspace):
    response = member_client.get(url("create"))
    assert response.status_code == 200
    body = response.content.decode()
    assert "Destination URL" in body
    assert "Short code" in body
    assert "Instagram bio" in body


def test_create_link_saves_everything(member_client, workspace, owner_membership):
    response = member_client.post(
        url("create"),
        {
            "destination_url": "https://shop.example.com/collections/spring",
            "code": "spring-drop",
            "note": "hero link",
            "tags": "campaign, ig-bio",
            "utm_source": "instagram",
            "utm_medium": "bio",
            "utm_campaign": "spring26",
            "utm_content": "",
            "utm_term": "",
            "og_title": "Spring drop is live",
            "og_description": "40 new pieces.",
            "og_image_url": "",
            "routing_enabled": "on",
            "target_ios_app_url": "instagram://user?username=acme",
            "target_ios_fallback_url": "https://m.example.com/ios",
            "target_android_url": "https://m.example.com/android",
            "target_desktop_url": "",
        },
    )
    assert response.status_code == 302
    link = Link.objects.get(code="spring-drop")
    assert link.destination_url.startswith("https://shop.example.com")
    assert link.utm_campaign == "spring26"
    assert link.og_title == "Spring drop is live" and link.og_overridden is True
    assert sorted(link.tags.values_list("name", flat=True)) == ["campaign", "ig-bio"]
    assert set(link.targets.values_list("platform", flat=True)) == {"ios", "android"}


def test_create_link_rerenders_with_errors(member_client, workspace):
    response = member_client.post(
        url("create"), {"destination_url": "javascript:alert(1)", "code": "admin"}
    )
    assert response.status_code == 200
    body = response.content.decode()
    assert "http://" in body
    assert "Reserved word" in body
    assert not Link.objects.exists()


def test_create_link_with_a_malformed_port_rerenders_instead_of_500ing(member_client, workspace):
    response = member_client.post(url("create"), {"destination_url": "http://example.com:abc/"})
    assert response.status_code == 200
    assert "http://" in response.content.decode()
    assert not Link.objects.exists()


def test_edit_link_updates(member_client, owner_membership):
    link = services.create_link(
        owner_membership, destination_url="https://example.com", code="first"
    )
    response = member_client.post(
        url("edit", "acme-social", "first"),
        {
            "destination_url": "https://example.com/new",
            "code": "second",
            "note": "",
            "tags": "",
            "utm_source": "",
            "utm_medium": "",
            "utm_campaign": "",
            "utm_content": "",
            "utm_term": "",
            "og_title": "",
            "og_description": "",
            "og_image_url": "",
        },
    )
    assert response.status_code == 302
    link.refresh_from_db()
    assert link.code == "second" and link.destination_url.endswith("/new")


def test_edit_404_for_another_workspace(client, other_membership, owner_membership):
    services.create_link(owner_membership, destination_url="https://example.com", code="mine")
    client.force_login(other_membership.user)
    assert client.get(reverse("links:edit", args=["other", "mine"])).status_code == 404


def test_code_check_fragment(member_client, owner_membership):
    services.create_link(owner_membership, destination_url="https://example.com", code="taken")
    taken = member_client.get(url("code_check") + "?code=taken", HTTP_HX_REQUEST="true")
    assert "already taken" in taken.content.decode()
    free = member_client.get(url("code_check") + "?code=fresh-code", HTTP_HX_REQUEST="true")
    assert "available" in free.content.decode()
    reserved = member_client.get(url("code_check") + "?code=admin", HTTP_HX_REQUEST="true")
    assert "Reserved word" in reserved.content.decode()


def test_metadata_fragment_uses_the_task_helper(member_client, monkeypatch):
    monkeypatch.setattr(
        "apps.links.tasks._fetch_html",
        lambda url: (
            "<html><head><title>Hello</title>"
            '<meta property="og:description" content="Desc"></head></html>',
            url,
        ),
    )
    response = member_client.post(
        url("metadata"), {"destination_url": "https://example.com"}, HTTP_HX_REQUEST="true"
    )
    assert response.status_code == 200
    body = response.content.decode()
    assert "Hello" in body and "Desc" in body


def test_metadata_fragment_reports_a_bad_url(member_client):
    response = member_client.post(
        url("metadata"), {"destination_url": "javascript:alert(1)"}, HTTP_HX_REQUEST="true"
    )
    assert response.status_code == 422
    assert "http://" in response.content.decode()


def test_metadata_lookup_is_rate_limited(member_client, monkeypatch, settings):
    settings.LINK_METADATA_RATE = 1
    calls = []

    def fake_fetch_html(url):
        calls.append(url)
        return "<html><head><title>Hello</title></head></html>", url

    monkeypatch.setattr("apps.links.tasks._fetch_html", fake_fetch_html)
    first = member_client.post(
        url("metadata"), {"destination_url": "https://example.com"}, HTTP_HX_REQUEST="true"
    )
    assert first.status_code == 200
    second = member_client.post(
        url("metadata"), {"destination_url": "https://example.com"}, HTTP_HX_REQUEST="true"
    )
    assert second.status_code == 429
    assert "Too many lookups" in second.content.decode()
    assert calls == ["https://example.com"]


def test_create_link_rejects_a_javascript_image_url(member_client, workspace):
    response = member_client.post(
        url("create"),
        {
            "destination_url": "https://example.com",
            "code": "",
            "og_image_url": "javascript:alert(1)",
        },
    )
    assert response.status_code == 200
    assert "http://" in response.content.decode()
    assert not Link.objects.exists()


def test_create_link_rejects_a_private_image_url(member_client, workspace):
    response = member_client.post(
        url("create"),
        {
            "destination_url": "https://example.com",
            "code": "",
            "og_image_url": "http://127.0.0.1/x.png",
        },
    )
    assert response.status_code == 200
    assert "Private and local addresses" in response.content.decode()
    assert not Link.objects.exists()


def test_utm_preset_fragment_fills_fields(member_client):
    response = member_client.post(
        url("utm_preset"),
        {
            "preset": "instagram-bio",
            "utm_campaign": "spring26",
            "destination_url": "https://example.com/p",
        },
        HTTP_HX_REQUEST="true",
    )
    body = response.content.decode()
    assert 'value="instagram"' in body and 'value="bio"' in body and "spring26" in body
    assert "utm_source=instagram" in body


def test_card_preview_switches_platform(member_client):
    response = member_client.post(
        url("card_preview"),
        {
            "platform": "whatsapp",
            "og_title": "T",
            "og_description": "D",
            "og_image_url": "",
            "destination_url": "https://example.com",
        },
        HTTP_HX_REQUEST="true",
    )
    assert response.status_code == 200
    assert "WhatsApp" in response.content.decode()


def test_rate_limit_surfaces_as_a_form_error(member_client, settings, workspace):
    settings.LINK_RATE_PER_USER = 1
    member_client.post(
        url("create"),
        {
            "destination_url": "https://example.com/1",
            "code": "",
            "note": "",
            "tags": "",
            "utm_source": "",
            "utm_medium": "",
            "utm_campaign": "",
            "utm_content": "",
            "utm_term": "",
            "og_title": "",
            "og_description": "",
            "og_image_url": "",
        },
    )
    blocked = member_client.post(
        url("create"),
        {
            "destination_url": "https://example.com/2",
            "code": "",
            "note": "",
            "tags": "",
            "utm_source": "",
            "utm_medium": "",
            "utm_campaign": "",
            "utm_content": "",
            "utm_term": "",
            "og_title": "",
            "og_description": "",
            "og_image_url": "",
        },
    )
    assert blocked.status_code == 200
    assert "Slow down" in blocked.content.decode()
    assert Link.objects.count() == 1
