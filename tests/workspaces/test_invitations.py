import re
from datetime import timedelta

import pytest
from django.core import mail
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.workspaces import services
from apps.workspaces.models import Invitation, Membership, Role


def test_invite_creates_hashed_invitation_and_sends_email(admin_membership):
    raw = services.invite(admin_membership, "new@example.com", Role.MEMBER)
    invitation = Invitation.objects.get()
    assert invitation.email == "new@example.com"
    assert invitation.role == Role.MEMBER
    assert raw not in invitation.token_hash
    assert invitation.invited_by == admin_membership.user
    assert timedelta(days=6) < invitation.expires_at - timezone.now() <= timedelta(days=7)
    assert len(mail.outbox) == 1
    message = mail.outbox[0]
    assert message.to == ["new@example.com"]
    assert "Acme Social" in message.subject
    url = re.search(r"https://sho\.rt/w/invitations/[A-Za-z0-9_-]+/", message.body).group(0)
    assert url.rsplit("/", 2)[1] == raw


def test_member_cannot_invite_and_nobody_invites_owners(member_membership, admin_membership):
    with pytest.raises(services.RoleRequired):
        services.invite(member_membership, "x@example.com", Role.MEMBER)
    with pytest.raises(services.InvalidOperation):
        services.invite(admin_membership, "x@example.com", Role.OWNER)


def test_invite_existing_member_is_rejected(admin_membership, member_membership):
    with pytest.raises(services.InvalidOperation):
        services.invite(admin_membership, member_membership.user.email, Role.MEMBER)


def test_duplicate_pending_invite_is_rejected(admin_membership):
    services.invite(admin_membership, "dup@example.com", Role.MEMBER)
    with pytest.raises(services.InvalidOperation):
        services.invite(admin_membership, "dup@example.com", Role.MEMBER)
    assert len(mail.outbox) == 1
    assert Invitation.objects.filter(email="dup@example.com").count() == 1


def test_revoking_a_pending_invite_lets_a_new_one_through(admin_membership):
    services.invite(admin_membership, "dup@example.com", Role.MEMBER)
    services.revoke_invitation(admin_membership, Invitation.objects.get(email="dup@example.com"))
    services.invite(admin_membership, "dup@example.com", Role.MEMBER)
    assert Invitation.objects.filter(email="dup@example.com").count() == 2
    assert len(mail.outbox) == 2


def test_invite_rate_limit_per_workspace_blocks_the_next_invite(admin_membership, settings):
    settings.INVITE_RATE_PER_WORKSPACE = 20
    for i in range(20):
        services.invite(admin_membership, f"person{i}@example.com", Role.MEMBER)
    with pytest.raises(services.InvalidOperation):
        services.invite(admin_membership, "person20@example.com", Role.MEMBER)
    assert len(mail.outbox) == 20


def test_invite_rate_limit_per_workspace_does_not_affect_other_workspaces(admin_membership):
    for i in range(20):
        services.invite(admin_membership, f"person{i}@example.com", Role.MEMBER)
    with pytest.raises(services.InvalidOperation):
        services.invite(admin_membership, "person20@example.com", Role.MEMBER)

    other_owner = User.objects.create_user(email="other-owner@example.com")
    other_workspace = services.create_workspace(other_owner, name="Other Co", slug="other-co")
    other_membership = Membership.objects.get(workspace=other_workspace, user=other_owner)
    services.invite(other_membership, "fresh@example.com", Role.MEMBER)
    assert Invitation.objects.filter(workspace=other_workspace).count() == 1


def test_accept_invitation_creates_membership_once(admin_membership, outsider):
    raw = services.invite(admin_membership, outsider.email, Role.ADMIN)
    membership = services.accept_invitation(outsider, raw)
    assert membership.role == Role.ADMIN and membership.workspace == admin_membership.workspace
    assert Invitation.objects.get().accepted_by == outsider
    with pytest.raises(services.InvalidInvitation):
        services.accept_invitation(outsider, raw)


def test_accept_rejects_expired_or_revoked(admin_membership, outsider):
    raw = services.invite(admin_membership, outsider.email, Role.MEMBER)
    Invitation.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
    with pytest.raises(services.InvalidInvitation):
        services.accept_invitation(outsider, raw)

    other_user = User.objects.create_user(email="other@example.com")
    raw2 = services.invite(admin_membership, other_user.email, Role.MEMBER)
    services.revoke_invitation(admin_membership, Invitation.objects.get(email="other@example.com"))
    with pytest.raises(services.InvalidInvitation):
        services.accept_invitation(other_user, raw2)


def test_accept_page_flow(client, admin_membership, outsider):
    raw = services.invite(admin_membership, outsider.email, Role.MEMBER)
    url = reverse("workspaces:invitation_accept", args=[raw])
    anonymous = client.get(url)
    assert anonymous.status_code == 302 and anonymous.url.startswith(reverse("accounts:login"))
    client.force_login(outsider)
    page = client.get(url)
    assert page.status_code == 200
    body = page.content.decode()
    assert "invited you to Acme Social" in body and "Member" in body and outsider.email in body
    response = client.post(url)
    assert response.status_code == 302
    assert response.url == reverse("workspaces:dashboard", args=["acme-social"])
    assert Membership.objects.filter(user=outsider, workspace__slug="acme-social").exists()


def test_accept_page_for_bad_token(client, outsider, db):
    client.force_login(outsider)
    response = client.get(reverse("workspaces:invitation_accept", args=["nope"]))
    assert response.status_code == 410
    assert "no longer valid" in response.content.decode()


def test_decline_marks_invitation_used(client, admin_membership, outsider):
    raw = services.invite(admin_membership, outsider.email, Role.MEMBER)
    client.force_login(outsider)
    response = client.post(reverse("workspaces:invitation_decline", args=[raw]))
    assert response.status_code == 302 and response.url == reverse("workspaces:index")
    assert Invitation.objects.get().is_pending is False
    assert not Membership.objects.filter(user=outsider).exists()


def test_login_next_survives_invite_link(client, admin_membership):
    raw = services.invite(admin_membership, "fresh@example.com", Role.MEMBER)
    url = reverse("workspaces:invitation_accept", args=[raw])
    response = client.get(url)
    assert response.status_code == 302
    assert f"next={url}" in response.url.replace("%2F", "/")


def test_accept_invitation_rejects_mismatched_email(admin_membership, outsider):
    stranger = User.objects.create_user(email="stranger@example.com")
    raw = services.invite(admin_membership, outsider.email, Role.MEMBER)
    with pytest.raises(services.InvitationEmailMismatch):
        services.accept_invitation(stranger, raw)
    assert not Membership.objects.filter(user=stranger).exists()


def test_decline_invitation_rejects_mismatched_email(admin_membership, outsider):
    stranger = User.objects.create_user(email="stranger@example.com")
    raw = services.invite(admin_membership, outsider.email, Role.MEMBER)
    with pytest.raises(services.InvitationEmailMismatch):
        services.decline_invitation(stranger, raw)
    assert Invitation.objects.get().is_pending is True


def test_invitation_accept_page_rejects_mismatched_email(client, admin_membership, outsider):
    stranger = User.objects.create_user(email="stranger@example.com")
    raw = services.invite(admin_membership, outsider.email, Role.MEMBER)
    accept_url = reverse("workspaces:invitation_accept", args=[raw])
    client.force_login(stranger)

    get_response = client.get(accept_url)
    assert get_response.status_code == 403
    assert outsider.email in get_response.content.decode()

    post_response = client.post(accept_url)
    assert post_response.status_code == 403
    assert not Membership.objects.filter(user=stranger).exists()


def test_invitation_decline_page_rejects_mismatched_email(client, admin_membership, outsider):
    stranger = User.objects.create_user(email="stranger@example.com")
    raw = services.invite(admin_membership, outsider.email, Role.MEMBER)
    client.force_login(stranger)
    response = client.post(reverse("workspaces:invitation_decline", args=[raw]))
    assert response.status_code == 403
    assert outsider.email in response.content.decode()
    assert Invitation.objects.get().is_pending is True


def test_concurrent_accept_returns_410_instead_of_500(
    client, admin_membership, outsider, monkeypatch
):
    raw = services.invite(admin_membership, outsider.email, Role.MEMBER)
    client.force_login(outsider)

    def raise_invalid(*args, **kwargs):
        raise services.InvalidInvitation

    monkeypatch.setattr(services, "accept_invitation", raise_invalid)
    response = client.post(reverse("workspaces:invitation_accept", args=[raw]))
    assert response.status_code == 410
    assert not Membership.objects.filter(user=outsider).exists()


def test_concurrent_decline_returns_410_instead_of_500(
    client, admin_membership, outsider, monkeypatch
):
    raw = services.invite(admin_membership, outsider.email, Role.MEMBER)
    client.force_login(outsider)

    def raise_invalid(*args, **kwargs):
        raise services.InvalidInvitation

    monkeypatch.setattr(services, "decline_invitation", raise_invalid)
    response = client.post(reverse("workspaces:invitation_decline", args=[raw]))
    assert response.status_code == 410


def test_invitation_accept_allows_case_insensitive_email_match(client, admin_membership):
    user = User.objects.create_user(email="Fresh@Example.com")
    raw = services.invite(admin_membership, "fresh@example.com", Role.MEMBER)
    accept_url = reverse("workspaces:invitation_accept", args=[raw])
    client.force_login(user)
    response = client.post(accept_url)
    assert response.status_code == 302
    assert Membership.objects.filter(user=user, workspace__slug="acme-social").exists()
