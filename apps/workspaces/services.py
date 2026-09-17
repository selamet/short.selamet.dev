"""Workspace rules: slugs, creation, membership changes, ownership transfer, deletion."""

import hashlib
import re
import secrets
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.urls import reverse
from django.utils import timezone

from apps.core import ratelimit

from .models import Invitation, Membership, Role, Workspace, validate_timezone
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


class InvalidInvitation(Exception):
    """Unknown, expired, revoked or already accepted invitation."""


class InvitationEmailMismatch(Exception):
    """The signed-in user's email does not match the invited address."""


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
    validate_timezone(timezone)
    if not slug_is_available(slug):
        raise ValidationError("This slug is already taken.")
    try:
        with transaction.atomic():
            workspace = Workspace.objects.create(
                name=name.strip(), slug=slug, timezone=timezone, created_by=user
            )
    except IntegrityError:
        raise ValidationError("This slug is already taken.") from None
    Membership.objects.create(workspace=workspace, user=user, role=Role.OWNER)
    return workspace


def update_workspace(actor, name, slug, timezone):
    _require(actor, "workspace.settings")
    workspace = actor.workspace
    slug = validate_slug(slug)
    validate_timezone(timezone)
    if slug != workspace.slug and not slug_is_available(slug):
        raise ValidationError("This slug is already taken.")
    workspace.name, workspace.slug, workspace.timezone = name.strip(), slug, timezone
    try:
        with transaction.atomic():
            workspace.save(update_fields=["name", "slug", "timezone"])
    except IntegrityError:
        raise ValidationError("This slug is already taken.") from None
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


def hash_token(raw_token):
    return hashlib.sha256(raw_token.encode()).hexdigest()


def invitation_url(raw_token):
    return f"{settings.SITE_URL}{reverse('workspaces:invitation_accept', args=[raw_token])}"


def invite(actor, email, role):
    _require(actor, "members.manage")
    if role == Role.OWNER:
        raise InvalidOperation("Ownership is granted only through transfer.")
    email = email.strip().lower()
    if Membership.objects.filter(workspace=actor.workspace, user__email__iexact=email).exists():
        raise InvalidOperation("This person is already a member.")
    if Invitation.objects.filter(
        workspace=actor.workspace,
        email__iexact=email,
        accepted_at__isnull=True,
        expires_at__gt=timezone.now(),
    ).exists():
        raise InvalidOperation("An invitation is already pending for this address.")
    # Both counters are always incremented, even when only one is exhausted, so a
    # request that fails on the workspace limit still counts against the user limit.
    allowed_for_workspace = ratelimit.hit(
        "invite-workspace",
        str(actor.workspace_id),
        limit=settings.INVITE_RATE_PER_WORKSPACE,
        window=settings.INVITE_RATE_PER_WORKSPACE_WINDOW,
    )
    allowed_for_user = ratelimit.hit(
        "invite-user",
        str(actor.user_id),
        limit=settings.INVITE_RATE_PER_USER,
        window=settings.INVITE_RATE_PER_USER_WINDOW,
    )
    if not (allowed_for_workspace and allowed_for_user):
        raise InvalidOperation("Too many invitations. Try again in a while.")
    raw_token = secrets.token_urlsafe(32)
    invitation = Invitation.objects.create(
        workspace=actor.workspace,
        email=email,
        role=role,
        token_hash=hash_token(raw_token),
        expires_at=timezone.now() + timedelta(days=settings.INVITATION_TTL_DAYS),
        invited_by=actor.user,
    )
    from .tasks import send_invitation

    send_invitation.enqueue(invitation.pk, raw_token)
    return raw_token


def revoke_invitation(actor, invitation):
    _require(actor, "members.manage")
    if invitation.workspace_id != actor.workspace_id:
        raise InvalidOperation("Invitation belongs to another workspace.")
    invitation.expires_at = timezone.now()
    invitation.save(update_fields=["expires_at"])


def get_pending_invitation(raw_token):
    invitation = (
        Invitation.objects.select_related("workspace", "invited_by")
        .filter(token_hash=hash_token(raw_token))
        .first()
    )
    if invitation is None or not invitation.is_pending:
        raise InvalidInvitation
    return invitation


@transaction.atomic
def accept_invitation(user, raw_token):
    invitation = get_pending_invitation(raw_token)
    if user.email.lower() != invitation.email.lower():
        raise InvitationEmailMismatch
    invitation = Invitation.objects.select_for_update().get(pk=invitation.pk)
    if not invitation.is_pending:
        raise InvalidInvitation
    membership, _ = Membership.objects.get_or_create(
        workspace=invitation.workspace, user=user, defaults={"role": invitation.role}
    )
    invitation.accepted_at = timezone.now()
    invitation.accepted_by = user
    invitation.save(update_fields=["accepted_at", "accepted_by"])
    return membership


def decline_invitation(user, raw_token):
    invitation = get_pending_invitation(raw_token)
    if user.email.lower() != invitation.email.lower():
        raise InvitationEmailMismatch
    invitation.expires_at = timezone.now()
    invitation.save(update_fields=["expires_at"])
