import pytest
from django.urls import reverse

from apps.accounts.models import User
from apps.workspaces import services
from apps.workspaces.models import Invitation, Membership, Role, Workspace


def url(name, slug="acme-social", *args):
    return reverse(f"workspaces:{name}", args=[slug, *args])


def test_general_settings_update(client, owner_membership):
    client.force_login(owner_membership.user)
    page = client.get(url("settings_general"))
    assert page.status_code == 200 and "Workspace name" in page.content.decode()
    response = client.post(
        url("settings_general"),
        {"name": "Acme Studio", "slug": "acme-studio", "timezone": "Europe/Istanbul"},
    )
    assert response.status_code == 302
    assert response.url == url("settings_general", "acme-studio")
    workspace = Workspace.objects.get()
    assert workspace.name == "Acme Studio" and workspace.slug == "acme-studio"
    assert workspace.timezone == "Europe/Istanbul"


def test_member_gets_403_on_settings(client, member_membership):
    client.force_login(member_membership.user)
    assert client.get(url("settings_general")).status_code == 403


def test_members_page_lists_members_and_matrix(client, owner_membership, member_membership):
    client.force_login(owner_membership.user)
    body = client.get(url("settings_members")).content.decode()
    assert "member@example.com" in body and "owner@example.com" in body
    assert "Delete or transfer workspace" in body


def test_invite_from_members_page(client, admin_membership):
    client.force_login(admin_membership.user)
    response = client.post(
        url("settings_members"),
        {"email": "new@example.com", "role": "member"},
        HTTP_HX_REQUEST="true",
    )
    assert response.status_code == 200
    body = response.content.decode()
    assert "new@example.com" in body
    assert 'id="invite-form"' in body
    assert 'name="email" value=""' in body
    assert Invitation.objects.filter(email="new@example.com").exists()


def test_invite_existing_member_shows_error(client, admin_membership, member_membership):
    client.force_login(admin_membership.user)
    response = client.post(
        url("settings_members"),
        {"email": member_membership.user.email, "role": "member"},
        HTTP_HX_REQUEST="true",
    )
    assert response.status_code == 200
    body = response.content.decode()
    assert "already a member" in body
    assert "Permissions" not in body


def test_invite_existing_member_shows_error_full_page(client, admin_membership, member_membership):
    client.force_login(admin_membership.user)
    response = client.post(
        url("settings_members"), {"email": member_membership.user.email, "role": "member"}
    )
    assert response.status_code == 200
    body = response.content.decode()
    assert "already a member" in body
    assert "Permissions" in body


def test_invite_rate_limit_error_reaches_members_page(client, admin_membership, settings):
    settings.INVITE_RATE_PER_WORKSPACE = 1
    services.invite(admin_membership, "first@example.com", Role.MEMBER)
    client.force_login(admin_membership.user)
    response = client.post(
        url("settings_members"), {"email": "second@example.com", "role": "member"}
    )
    assert response.status_code == 200
    assert "Too many invitations" in response.content.decode()
    assert not Invitation.objects.filter(email="second@example.com").exists()


def test_change_role_and_remove(client, admin_membership, member_membership):
    client.force_login(admin_membership.user)
    response = client.post(
        url("member_role", "acme-social", member_membership.pk),
        {"role": "admin"},
        HTTP_HX_REQUEST="true",
    )
    assert response.status_code == 200
    member_membership.refresh_from_db()
    assert member_membership.role == Role.ADMIN
    response = client.post(
        url("member_remove", "acme-social", member_membership.pk), HTTP_HX_REQUEST="true"
    )
    assert response.status_code == 200
    assert not Membership.objects.filter(pk=member_membership.pk).exists()


def test_owner_row_cannot_be_changed(client, admin_membership, owner_membership):
    client.force_login(admin_membership.user)
    response = client.post(
        url("member_role", "acme-social", owner_membership.pk), {"role": "member"}
    )
    assert response.status_code == 400
    owner_membership.refresh_from_db()
    assert owner_membership.role == Role.OWNER


def test_revoke_invitation(client, admin_membership):
    client.force_login(admin_membership.user)
    services.invite(admin_membership, "x@example.com", Role.MEMBER)
    invitation = Invitation.objects.get()
    response = client.post(
        url("invitation_revoke", "acme-social", invitation.pk), HTTP_HX_REQUEST="true"
    )
    assert response.status_code == 200
    invitation.refresh_from_db()
    assert invitation.is_pending is False


def test_transfer_ownership_view(client, owner_membership, admin_membership):
    client.force_login(owner_membership.user)
    response = client.post(url("transfer"), {"membership": admin_membership.pk})
    assert response.status_code == 302
    admin_membership.refresh_from_db()
    owner_membership.refresh_from_db()
    assert admin_membership.role == Role.OWNER and owner_membership.role == Role.ADMIN


def test_admin_cannot_see_or_use_danger_zone(client, admin_membership):
    client.force_login(admin_membership.user)
    assert client.get(url("settings_danger")).status_code == 403
    assert client.post(url("delete"), {"confirm_slug": "acme-social"}).status_code == 403


def test_delete_requires_matching_slug(client, owner_membership):
    client.force_login(owner_membership.user)
    wrong = client.post(url("delete"), {"confirm_slug": "nope"})
    assert wrong.status_code == 200 and "does not match" in wrong.content.decode()
    assert Workspace.objects.exists()
    response = client.post(url("delete"), {"confirm_slug": "acme-social"})
    assert response.status_code == 302 and response.url == reverse("workspaces:index")
    assert not Workspace.objects.exists()


@pytest.fixture
def other_workspace():
    owner = User.objects.create_user(email="other-owner@example.com")
    return services.create_workspace(owner, name="Other Co", slug="other-co")


@pytest.fixture
def other_membership(other_workspace):
    user = User.objects.create_user(email="other-member@example.com")
    return Membership.objects.create(workspace=other_workspace, user=user, role=Role.MEMBER)


def test_member_role_rejects_cross_workspace_target(client, admin_membership, other_membership):
    client.force_login(admin_membership.user)
    response = client.post(
        url("member_role", "acme-social", other_membership.pk), {"role": "admin"}
    )
    assert response.status_code == 404
    other_membership.refresh_from_db()
    assert other_membership.role == Role.MEMBER


def test_member_remove_rejects_cross_workspace_target(client, admin_membership, other_membership):
    client.force_login(admin_membership.user)
    response = client.post(url("member_remove", "acme-social", other_membership.pk))
    assert response.status_code == 404
    assert Membership.objects.filter(pk=other_membership.pk).exists()


def test_invitation_revoke_rejects_cross_workspace_invitation(
    client, admin_membership, other_workspace
):
    other_owner_membership = Membership.objects.get(workspace=other_workspace, role=Role.OWNER)
    services.invite(other_owner_membership, "target@example.com", Role.MEMBER)
    invitation = Invitation.objects.get(email="target@example.com")
    client.force_login(admin_membership.user)
    response = client.post(url("invitation_revoke", "acme-social", invitation.pk))
    assert response.status_code == 404
    invitation.refresh_from_db()
    assert invitation.is_pending is True
