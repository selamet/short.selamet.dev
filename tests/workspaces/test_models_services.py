import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError

from apps.workspaces import services
from apps.workspaces.models import Membership, Role, Workspace


def test_create_workspace_makes_creator_owner(owner):
    workspace = services.create_workspace(owner, name="Acme Social", slug="Acme-Social")
    assert workspace.slug == "acme-social"
    assert workspace.created_by == owner
    membership = Membership.objects.get(workspace=workspace)
    assert membership.user == owner and membership.role == Role.OWNER


def test_workspace_timezone_validator_rejects_bad_value(db):
    workspace = Workspace(name="Acme Social", slug="acme-social", timezone="Mars/Olympus")
    with pytest.raises(ValidationError):
        workspace.full_clean()


def test_create_workspace_rejects_invalid_timezone(owner):
    with pytest.raises(ValidationError):
        services.create_workspace(owner, name="Acme", slug="acme-x", timezone="Mars/Olympus")
    assert not Workspace.objects.exists()


def test_update_workspace_rejects_invalid_timezone(owner_membership):
    with pytest.raises(ValidationError):
        services.update_workspace(
            owner_membership, name="Acme Social", slug="acme-social", timezone="Mars/Olympus"
        )
    owner_membership.workspace.refresh_from_db()
    assert owner_membership.workspace.timezone == "UTC"


@pytest.mark.parametrize(
    "slug", ["a", "-acme", "acme-", "Acme Social", "new", "check-slug", "x" * 41, "acme_social"]
)
def test_validate_slug_rejects_bad_values(db, slug):
    with pytest.raises(ValidationError):
        services.validate_slug(slug)


def test_slug_is_available_is_case_insensitive(workspace):
    assert services.slug_is_available("ACME-SOCIAL") is False
    assert services.slug_is_available("other") is True


def test_create_workspace_rejects_taken_slug(workspace, outsider):
    with pytest.raises(ValidationError):
        services.create_workspace(outsider, name="Other", slug="acme-social")


def test_create_workspace_surfaces_race_on_duplicate_slug(outsider, monkeypatch):
    def raise_integrity_error(*args, **kwargs):
        raise IntegrityError

    monkeypatch.setattr(Workspace.objects, "create", raise_integrity_error)
    with pytest.raises(ValidationError):
        services.create_workspace(outsider, name="Other", slug="new-slug")


def test_one_owner_per_workspace(workspace, admin_membership):
    with pytest.raises(services.InvalidOperation):
        services.change_role(Membership.objects.get(role=Role.OWNER), admin_membership, Role.OWNER)


def test_admin_can_change_member_role_but_not_owner(
    owner_membership, admin_membership, member_membership
):
    services.change_role(admin_membership, member_membership, Role.ADMIN)
    member_membership.refresh_from_db()
    assert member_membership.role == Role.ADMIN
    with pytest.raises(services.InvalidOperation):
        services.change_role(admin_membership, owner_membership, Role.MEMBER)


def test_member_cannot_change_roles(member_membership, admin_membership):
    with pytest.raises(services.PermissionDenied):
        services.change_role(member_membership, admin_membership, Role.MEMBER)


def test_remove_member_rules(owner_membership, admin_membership, member_membership):
    with pytest.raises(services.InvalidOperation):
        services.remove_member(admin_membership, owner_membership)
    services.remove_member(admin_membership, member_membership)
    assert not Membership.objects.filter(pk=member_membership.pk).exists()
    with pytest.raises(services.InvalidOperation):
        services.remove_member(owner_membership, owner_membership)


def test_transfer_ownership_swaps_roles(owner_membership, admin_membership):
    services.transfer_ownership(owner_membership, admin_membership)
    owner_membership.refresh_from_db()
    admin_membership.refresh_from_db()
    assert admin_membership.role == Role.OWNER
    assert owner_membership.role == Role.ADMIN
    assert (
        Membership.objects.filter(workspace=owner_membership.workspace, role=Role.OWNER).count()
        == 1
    )


def test_only_owner_transfers(admin_membership, member_membership):
    with pytest.raises(services.PermissionDenied):
        services.transfer_ownership(admin_membership, member_membership)


def test_delete_workspace_requires_owner_and_matching_slug(owner_membership, admin_membership):
    with pytest.raises(services.PermissionDenied):
        services.delete_workspace(admin_membership, confirm_slug="acme-social")
    with pytest.raises(services.InvalidOperation):
        services.delete_workspace(owner_membership, confirm_slug="wrong")
    services.delete_workspace(owner_membership, confirm_slug="acme-social")
    assert not Workspace.objects.exists()
