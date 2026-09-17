"""Workspace rules: slugs, creation, membership changes, ownership transfer, deletion."""

import re

from django.core.exceptions import ValidationError
from django.db import transaction

from .models import Membership, Role, Workspace
from .permissions import can

SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,38}[a-z0-9])?$")
RESERVED_SLUGS = {
    "new",
    "check-slug",
    "invitations",
    "api",
    "admin",
    "auth",
    "static",
    "media",
    "health",
    "w",
}


class PermissionDenied(Exception):
    """The acting membership lacks the permission for this operation."""


class InvalidOperation(Exception):
    """The operation is not allowed in this state (e.g. removing the owner)."""


def normalize_slug(slug):
    # Lowercase only: unlike slugify(), this must not paper over invalid input
    # (leading/trailing hyphens, internal spaces) by rewriting it into something valid.
    return (slug or "").strip().lower()


def validate_slug(slug):
    slug = normalize_slug(slug)
    if len(slug) < 2 or not SLUG_RE.match(slug):
        raise ValidationError("Use 2–40 lowercase letters, numbers and hyphens.")
    if slug in RESERVED_SLUGS:
        raise ValidationError("This slug is reserved. Try another.")
    return slug


def slug_is_available(slug):
    return not Workspace.objects.filter(slug__iexact=normalize_slug(slug)).exists()


@transaction.atomic
def create_workspace(user, name, slug, timezone="UTC"):
    slug = validate_slug(slug)
    if not slug_is_available(slug):
        raise ValidationError("This slug is already taken.")
    workspace = Workspace.objects.create(
        name=name.strip(), slug=slug, timezone=timezone, created_by=user
    )
    Membership.objects.create(workspace=workspace, user=user, role=Role.OWNER)
    return workspace


def _require(membership, permission):
    if not can(membership, permission):
        raise PermissionDenied(permission)


def _same_workspace(actor, target):
    if actor.workspace_id != target.workspace_id:
        raise InvalidOperation("Memberships belong to different workspaces.")


def change_role(actor, target, role):
    _require(actor, "members.manage")
    _same_workspace(actor, target)
    if role == Role.OWNER or target.role == Role.OWNER:
        raise InvalidOperation("Ownership changes only through transfer.")
    target.role = role
    target.save(update_fields=["role"])
    return target


def remove_member(actor, target):
    _require(actor, "members.manage")
    _same_workspace(actor, target)
    if target.role == Role.OWNER:
        raise InvalidOperation("The owner cannot be removed. Transfer ownership first.")
    target.delete()


@transaction.atomic
def transfer_ownership(owner, target):
    _require(owner, "workspace.transfer")
    _same_workspace(owner, target)
    if owner.pk == target.pk:
        raise InvalidOperation("Choose another member.")
    # Demote first so the single-owner constraint never sees two owners.
    owner.role = Role.ADMIN
    owner.save(update_fields=["role"])
    target.role = Role.OWNER
    target.save(update_fields=["role"])


def delete_workspace(owner, confirm_slug):
    _require(owner, "workspace.delete")
    if normalize_slug(confirm_slug) != owner.workspace.slug:
        raise InvalidOperation("The slug does not match.")
    owner.workspace.delete()
