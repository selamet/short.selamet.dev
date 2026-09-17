"""Deleting a user's account must never leave a workspace without an owner."""

from apps.accounts.models import User
from apps.workspaces.models import Membership, Role, Workspace


def test_deleting_owner_promotes_oldest_admin(
    workspace, owner, admin_membership, member_membership
):
    owner_id = owner.pk
    owner.delete()
    admin_membership.refresh_from_db()
    member_membership.refresh_from_db()
    assert admin_membership.role == Role.OWNER
    assert member_membership.role == Role.MEMBER
    assert Membership.objects.filter(workspace=workspace, role=Role.OWNER).count() == 1
    assert not Membership.objects.filter(user_id=owner_id).exists()


def test_deleting_owner_with_no_admin_promotes_oldest_member(workspace, owner, member_membership):
    second_user = User.objects.create_user(email="second-member@example.com")
    second_membership = Membership.objects.create(
        workspace=workspace, user=second_user, role=Role.MEMBER
    )
    owner.delete()
    member_membership.refresh_from_db()
    second_membership.refresh_from_db()
    assert member_membership.role == Role.OWNER
    assert second_membership.role == Role.MEMBER
    assert Membership.objects.filter(workspace=workspace, role=Role.OWNER).count() == 1


def test_deleting_sole_owner_deletes_workspace(workspace, owner, owner_membership):
    workspace_id = workspace.pk
    owner.delete()
    assert not Workspace.objects.filter(pk=workspace_id).exists()
    assert not Membership.objects.filter(workspace_id=workspace_id).exists()


def test_deleting_non_owner_leaves_workspace_untouched(
    workspace, owner_membership, member_membership
):
    member_membership.user.delete()
    owner_membership.refresh_from_db()
    assert owner_membership.role == Role.OWNER
    assert Workspace.objects.filter(pk=workspace.pk).exists()
    assert not Membership.objects.filter(pk=member_membership.pk).exists()
