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
    resolver so these tests never perform a real DNS lookup."""
    monkeypatch.setattr(destinations, "resolve_host", lambda host, timeout: ["93.184.216.34"])


@pytest.fixture
def links(owner_membership):
    first = services.create_link(
        owner_membership,
        destination_url="https://example.com/a",
        code="spring-drop",
        tags=["campaign"],
    )
    second = services.create_link(
        owner_membership, destination_url="https://example.com/b", code="tt-sale24", tags=["tiktok"]
    )
    third = services.create_link(
        owner_membership, destination_url="https://example.com/c", code="nl-jul"
    )
    services.archive_link(owner_membership, third)
    return first, second, third


def test_list_shows_active_links_by_default(member_client, links):
    response = member_client.get(url("list"))
    assert response.status_code == 200
    body = response.content.decode()
    assert "spring-drop" in body and "tt-sale24" in body
    assert "nl-jul" not in body


def test_row_copies_the_full_short_url(member_client, links, settings):
    settings.SITE_URL = "https://sho.rt"
    first = links[0]
    body = member_client.get(url("list")).content.decode()
    assert f'data-copy="https://sho.rt/{first.code}"' in body


def test_list_filters_by_status_tag_and_search(member_client, links):
    archived = member_client.get(url("list") + "?status=archived").content.decode()
    assert "nl-jul" in archived and "spring-drop" not in archived
    tagged = member_client.get(url("list") + "?tag=tiktok").content.decode()
    assert "tt-sale24" in tagged and "spring-drop" not in tagged
    searched = member_client.get(url("list") + "?q=spring").content.decode()
    assert "spring-drop" in searched and "tt-sale24" not in searched


def test_list_htmx_request_returns_rows_only(member_client, links):
    response = member_client.get(url("list") + "?q=spring", HTTP_HX_REQUEST="true")
    body = response.content.decode()
    assert "spring-drop" in body
    assert "<html" not in body


def test_list_is_scoped_to_the_workspace(client, other_membership, links):
    client.force_login(other_membership.user)
    body = client.get(reverse("links:list", args=["other"])).content.decode()
    assert "spring-drop" not in body


def test_empty_state_is_shown_without_links(member_client, workspace):
    body = member_client.get(url("list")).content.decode()
    assert "Three steps to your first link" in body


def test_archive_and_restore_from_the_list(member_client, links, owner_membership):
    first = links[0]
    confirm = member_client.get(url("archive_confirm", "acme-social", first.code))
    assert confirm.status_code == 200 and "Archive" in confirm.content.decode()
    response = member_client.post(url("archive", "acme-social", first.code), HTTP_HX_REQUEST="true")
    assert response.status_code == 200
    first.refresh_from_db()
    assert first.status == Link.Status.ARCHIVED
    member_client.post(url("restore", "acme-social", first.code), HTTP_HX_REQUEST="true")
    first.refresh_from_db()
    assert first.status == Link.Status.ACTIVE


def test_workspace_dashboard_redirects_to_the_list(member_client, workspace):
    response = member_client.get(reverse("workspaces:dashboard", args=["acme-social"]))
    assert response.status_code == 302
    assert response.url == url("list")
