import pytest
from django.urls import reverse

from apps.accounts.models import User
from apps.workspaces.models import Membership, Role, Workspace


@pytest.fixture
def user(db):
    return User.objects.create_user(email="ada@example.com")


def test_anonymous_home_is_landing_page(client, db):
    response = client.get("/")
    assert response.status_code == 200
    assert "Sign in" in response.content.decode()


def test_signed_in_user_without_workspace_is_sent_to_create(client, user):
    client.force_login(user)
    response = client.get("/")
    assert response.status_code == 302
    assert response.url == reverse("workspaces:create")


def test_signed_in_user_with_workspace_is_sent_to_dashboard(client, workspace, owner):
    client.force_login(owner)
    response = client.get("/")
    assert response.status_code == 302
    assert response.url == reverse("workspaces:dashboard", args=["acme-social"])


def test_create_workspace_flow(client, user):
    client.force_login(user)
    page = client.get(reverse("workspaces:create"))
    assert page.status_code == 200
    assert "Name your workspace" in page.content.decode()
    response = client.post(
        reverse("workspaces:create"),
        {"name": "Acme Social", "slug": "acme-social", "timezone": "Europe/Istanbul"},
    )
    assert response.status_code == 302
    assert response.url == reverse("workspaces:dashboard", args=["acme-social"])
    workspace = Workspace.objects.get(slug="acme-social")
    assert workspace.timezone == "Europe/Istanbul"
    assert Membership.objects.get(workspace=workspace, user=user).role == Role.OWNER


def test_create_workspace_view_renders_slug_race_as_form_error(client, user, monkeypatch):
    from django.db import IntegrityError

    def raise_integrity_error(*args, **kwargs):
        raise IntegrityError

    monkeypatch.setattr(Workspace.objects, "create", raise_integrity_error)
    client.force_login(user)
    response = client.post(
        reverse("workspaces:create"),
        {"name": "Acme Social", "slug": "brand-new", "timezone": "UTC"},
    )
    assert response.status_code == 200
    assert "already taken" in response.content.decode()
    assert not Workspace.objects.exists()


def test_create_workspace_shows_slug_errors(client, user, workspace):
    client.force_login(user)
    response = client.post(
        reverse("workspaces:create"), {"name": "X", "slug": "acme-social", "timezone": "UTC"}
    )
    assert response.status_code == 200
    assert "already taken" in response.content.decode()


def test_check_slug_partial(client, user, workspace):
    client.force_login(user)
    taken = client.get(
        reverse("workspaces:check_slug") + "?slug=acme-social", HTTP_HX_REQUEST="true"
    )
    assert taken.status_code == 200 and "already taken" in taken.content.decode()
    free = client.get(
        reverse("workspaces:check_slug") + "?slug=fresh-brand", HTTP_HX_REQUEST="true"
    )
    assert "available" in free.content.decode()
    bad = client.get(reverse("workspaces:check_slug") + "?slug=new", HTTP_HX_REQUEST="true")
    assert "reserved" in bad.content.decode()


def test_check_slug_is_rate_limited(client, user):
    client.force_login(user)
    for _ in range(60):
        response = client.get(reverse("workspaces:check_slug") + "?slug=fresh-brand")
        assert response.status_code == 200
    blocked = client.get(reverse("workspaces:check_slug") + "?slug=fresh-brand")
    assert blocked.status_code == 429
    assert "Too many checks" in blocked.content.decode()


def test_dashboard_renders_guided_empty_state_for_members(client, workspace, member_membership):
    client.force_login(member_membership.user)
    response = client.get(reverse("workspaces:dashboard", args=["acme-social"]))
    assert response.status_code == 200
    body = response.content.decode()
    assert "Three steps to your first link" in body
    assert "Acme Social" in body


def test_dashboard_404_for_outsiders(client, workspace, outsider):
    client.force_login(outsider)
    assert client.get(reverse("workspaces:dashboard", args=["acme-social"])).status_code == 404


def test_index_lists_memberships(client, workspace, owner):
    client.force_login(owner)
    response = client.get(reverse("workspaces:index"))
    assert response.status_code == 200
    assert "Acme Social" in response.content.decode()
