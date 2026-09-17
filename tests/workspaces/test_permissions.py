import pytest
from django.http import HttpResponse
from django.test import RequestFactory
from django.urls import reverse

from apps.workspaces.permissions import PERMISSIONS, Role, can, require_role


def test_permission_matrix_matches_spec():
    assert PERMISSIONS["links.manage"] == {Role.OWNER, Role.ADMIN, Role.MEMBER}
    assert PERMISSIONS["analytics.view"] == {Role.OWNER, Role.ADMIN, Role.MEMBER}
    assert PERMISSIONS["members.manage"] == {Role.OWNER, Role.ADMIN}
    assert PERMISSIONS["api_keys.manage"] == {Role.OWNER, Role.ADMIN}
    assert PERMISSIONS["workspace.settings"] == {Role.OWNER, Role.ADMIN}
    assert PERMISSIONS["workspace.transfer"] == {Role.OWNER}
    assert PERMISSIONS["workspace.delete"] == {Role.OWNER}


def test_can_uses_membership_role(member_membership, owner_membership):
    assert can(member_membership, "links.manage") is True
    assert can(member_membership, "members.manage") is False
    assert can(owner_membership, "workspace.delete") is True
    assert can(None, "links.manage") is False


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
