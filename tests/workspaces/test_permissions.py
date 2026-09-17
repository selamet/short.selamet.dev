import pytest
from django.http import HttpResponse
from django.test import RequestFactory
from django.urls import reverse

from apps.workspaces.permissions import (
    PERMISSIONS,
    Role,
    can,
    get_membership,
    matrix_rows,
    require_role,
)


def test_matrix_rows_match_spec():
    # Per constraints.md (roles): member creates/edits links and views analytics;
    # admin also manages members and API keys; owner also transfers ownership and
    # deletes the workspace.
    rows = {row["label"]: row for row in matrix_rows()}
    assert len(rows) == len(PERMISSIONS)
    assert rows["Create & edit links"] == {
        "label": "Create & edit links",
        "owner": True,
        "admin": True,
        "member": True,
    }
    assert rows["View analytics"] == {
        "label": "View analytics",
        "owner": True,
        "admin": True,
        "member": True,
    }
    assert rows["Invite & manage members"] == {
        "label": "Invite & manage members",
        "owner": True,
        "admin": True,
        "member": False,
    }
    assert rows["Manage API keys"] == {
        "label": "Manage API keys",
        "owner": True,
        "admin": True,
        "member": False,
    }
    assert rows["Edit workspace settings"] == {
        "label": "Edit workspace settings",
        "owner": True,
        "admin": True,
        "member": False,
    }
    assert rows["Transfer ownership"] == {
        "label": "Transfer ownership",
        "owner": True,
        "admin": False,
        "member": False,
    }
    assert rows["Delete workspace"] == {
        "label": "Delete workspace",
        "owner": True,
        "admin": False,
        "member": False,
    }


def test_can_uses_membership_role(member_membership, owner_membership):
    assert can(member_membership, "links.manage") is True
    assert can(member_membership, "members.manage") is False
    assert can(owner_membership, "workspace.delete") is True
    assert can(None, "links.manage") is False


def test_get_membership_matches_slug_case_insensitively(member_membership):
    assert get_membership(member_membership.user, "Acme-Social") == member_membership
    assert get_membership(member_membership.user, "ACME-SOCIAL") == member_membership


@require_role(Role.OWNER, Role.ADMIN)
def _admin_view(request, slug):
    return HttpResponse(f"{request.workspace.slug}:{request.membership.role}")


def _call(user, slug):
    request = RequestFactory().get(f"/w/{slug}/x/")
    request.user = user
    return _admin_view(request, slug=slug)


def test_require_role_sets_workspace_and_membership(admin_membership):
    response = _call(admin_membership.user, "acme-social")
    assert response.status_code == 200
    assert response.content == b"acme-social:admin"


def test_require_role_404_for_non_members_and_unknown_slugs(outsider, workspace):
    from django.http import Http404

    with pytest.raises(Http404):
        _call(outsider, "acme-social")
    with pytest.raises(Http404):
        _call(outsider, "nope")


def test_require_role_403_for_insufficient_role(member_membership):
    from django.core.exceptions import PermissionDenied

    with pytest.raises(PermissionDenied):
        _call(member_membership.user, "acme-social")


def test_require_role_redirects_anonymous_to_login(db, workspace):
    from django.contrib.auth.models import AnonymousUser

    response = _call(AnonymousUser(), "acme-social")
    assert response.status_code == 302
    assert response.url.startswith(reverse("accounts:login"))
