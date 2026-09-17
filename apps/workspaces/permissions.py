"""Role matrix and the view decorator that resolves /w/<slug>/ into request.workspace."""

from functools import wraps

from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from django.http import Http404

from .models import Membership, Role

ALL_ROLES = {Role.OWNER, Role.ADMIN, Role.MEMBER}
MANAGERS = {Role.OWNER, Role.ADMIN}

PERMISSIONS = {
    "links.manage": ALL_ROLES,
    "analytics.view": ALL_ROLES,
    "members.manage": MANAGERS,
    "api_keys.manage": MANAGERS,
    "workspace.settings": MANAGERS,
    "workspace.transfer": {Role.OWNER},
    "workspace.delete": {Role.OWNER},
}

# Human labels for the permission matrix rendered on the members page, in display order.
PERMISSION_LABELS = {
    "links.manage": "Create & edit links",
    "analytics.view": "View analytics",
    "members.manage": "Invite & manage members",
    "api_keys.manage": "Manage API keys",
    "workspace.settings": "Edit workspace settings",
    "workspace.transfer": "Transfer ownership",
    "workspace.delete": "Delete workspace",
}


def can(membership, permission):
    if membership is None:
        return False
    return membership.role in PERMISSIONS[permission]


def matrix_rows():
    """The permission matrix as rendered rows, derived from PERMISSIONS so the two
    never drift apart. Raises KeyError if a permission is missing its label, rather
    than silently rendering an incomplete matrix."""
    return [
        {
            "label": PERMISSION_LABELS[permission],
            "owner": Role.OWNER in roles,
            "admin": Role.ADMIN in roles,
            "member": Role.MEMBER in roles,
        }
        for permission, roles in PERMISSIONS.items()
    ]


def get_membership(user, slug):
    """The user's membership for the workspace at `slug`, or None (also for anonymous users)."""
    if not user.is_authenticated:
        return None
    return (
        Membership.objects.select_related("workspace", "user")
        .filter(workspace__slug__iexact=slug, user=user)
        .first()
    )


def require_role(*roles):
    """Resolve the workspace from the `slug` kwarg; 404 for non-members, 403 for the wrong role."""
    allowed = set(roles) or ALL_ROLES

    def decorator(view):
        @wraps(view)
        def wrapper(request, slug, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect_to_login(request.get_full_path())
            membership = get_membership(request.user, slug)
            if membership is None:
                raise Http404
            if membership.role not in allowed:
                raise PermissionDenied
            request.workspace = membership.workspace
            request.membership = membership
            return view(request, slug, *args, **kwargs)

        return wrapper

    return decorator
