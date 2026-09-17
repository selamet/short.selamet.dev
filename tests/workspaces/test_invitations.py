import re
from datetime import timedelta

import pytest
from django.core import mail
from django.urls import reverse
from django.utils import timezone

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
    with pytest.raises(services.PermissionDenied):
        services.invite(member_membership, "x@example.com", Role.MEMBER)
    with pytest.raises(services.InvalidOperation):
        services.invite(admin_membership, "x@example.com", Role.OWNER)


def test_invite_existing_member_is_rejected(admin_membership, member_membership):
    with pytest.raises(services.InvalidOperation):
        services.invite(admin_membership, member_membership.user.email, Role.MEMBER)


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
    raw2 = services.invite(admin_membership, "other@example.com", Role.MEMBER)
    services.revoke_invitation(admin_membership, Invitation.objects.get(email="other@example.com"))
    with pytest.raises(services.InvalidInvitation):
        services.accept_invitation(outsider, raw2)


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
