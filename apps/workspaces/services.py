"""Workspace rules: slugs, creation, membership changes, ownership transfer, deletion."""

import hashlib
import logging
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

logger = logging.getLogger(__name__)

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


class RoleRequired(Exception):
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
def create_workspace(user, name, slug, tz="UTC"):
    slug = validate_slug(slug)
    validate_timezone(tz)
    if not slug_is_available(slug):
        raise ValidationError("This slug is already taken.")
    try:
        with transaction.atomic():
            workspace = Workspace.objects.create(
                name=name.strip(), slug=slug, timezone=tz, created_by=user
            )
    except IntegrityError:
        raise ValidationError("This slug is already taken.") from None
    Membership.objects.create(workspace=workspace, user=user, role=Role.OWNER)
    logger.info(
        "workspace created workspace_id=%s actor_id=%s slug=%s", workspace.pk, user.pk, slug
    )
    return workspace


def update_workspace(actor, name, slug, tz):
    _require(actor, "workspace.settings")
    workspace = actor.workspace
    slug = validate_slug(slug)
    validate_timezone(tz)
    if slug != workspace.slug and not slug_is_available(slug):
        raise ValidationError("This slug is already taken.")
    workspace.name, workspace.slug, workspace.timezone = name.strip(), slug, tz
    try:
        with transaction.atomic():
            workspace.save(update_fields=["name", "slug", "timezone"])
    except IntegrityError:
        raise ValidationError("This slug is already taken.") from None
    logger.info(
        "workspace settings updated workspace_id=%s actor_id=%s", workspace.pk, actor.user_id
    )
    return workspace


def _require(membership, permission):
    if not can(membership, permission):
        raise RoleRequired(permission)


def _same_workspace(actor, target):
    if actor.workspace_id != target.workspace_id:
        raise InvalidOperation("Memberships belong to different workspaces.")


def change_role(actor, target, role):
    _require(actor, "members.manage")
    _same_workspace(actor, target)
    if actor.pk == target.pk:
        raise InvalidOperation("You cannot change your own role.")
    if role == Role.OWNER or target.role == Role.OWNER:
        raise InvalidOperation("Ownership changes only through transfer.")
    target.role = role
    target.save(update_fields=["role"])
    logger.info(
        "member role changed workspace_id=%s actor_id=%s target_id=%s new_role=%s",
        actor.workspace_id,
        actor.user_id,
        target.user_id,
        role,
    )
    return target


def remove_member(actor, target):
    _require(actor, "members.manage")
    _same_workspace(actor, target)
    if actor.pk == target.pk:
        raise InvalidOperation("You cannot remove yourself.")
    if target.role == Role.OWNER:
        raise InvalidOperation("The owner cannot be removed. Transfer ownership first.")
    target.delete()
    logger.info(
        "member removed workspace_id=%s actor_id=%s target_id=%s",
        actor.workspace_id,
        actor.user_id,
        target.user_id,
    )


@transaction.atomic
def transfer_ownership(owner, target):
    _require(owner, "workspace.transfer")
    _same_workspace(owner, target)
    if owner.pk == target.pk:
        raise InvalidOperation("Choose another member.")
    # Lock both rows so a concurrent transfer or removal can't slip in between the
    # check below and the writes that follow, then re-read them under the lock:
    # the caller's in-memory objects may already be stale.
    locked = {
        membership.pk: membership
        for membership in Membership.objects.select_for_update().filter(
            pk__in=[owner.pk, target.pk]
        )
    }
    locked_owner = locked.get(owner.pk)
    locked_target = locked.get(target.pk)
    stale = (
        locked_owner is None
        or locked_target is None
        or locked_owner.role != Role.OWNER
        or locked_owner.workspace_id != locked_target.workspace_id
    )
    if stale:
        raise InvalidOperation(
            "Ownership changed while you were transferring. Reload and try again."
        )
    try:
        with transaction.atomic():
            # Demote first so the single-owner constraint never sees two owners.
            locked_owner.role = Role.ADMIN
            locked_owner.save(update_fields=["role"])
            locked_target.role = Role.OWNER
            locked_target.save(update_fields=["role"])
    except IntegrityError:
        raise InvalidOperation(
            "Ownership changed while you were transferring. Reload and try again."
        ) from None
    logger.info(
        "workspace ownership transferred workspace_id=%s actor_id=%s target_id=%s",
        locked_owner.workspace_id,
        owner.user_id,
        target.user_id,
    )


def delete_workspace(owner, confirm_slug):
    _require(owner, "workspace.delete")
    if normalize_slug(confirm_slug) != owner.workspace.slug:
        raise InvalidOperation("The slug does not match.")
    workspace_id = owner.workspace_id
    owner.workspace.delete()
    logger.info("workspace deleted workspace_id=%s actor_id=%s", workspace_id, owner.user_id)


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
    logger.info(
        "invitation sent workspace_id=%s actor_id=%s invitation_id=%s role=%s",
        actor.workspace_id,
        actor.user_id,
        invitation.pk,
        role,
    )
    return raw_token


def revoke_invitation(actor, invitation):
    _require(actor, "members.manage")
    if invitation.workspace_id != actor.workspace_id:
        raise InvalidOperation("Invitation belongs to another workspace.")
    invitation.expires_at = timezone.now()
    invitation.save(update_fields=["expires_at"])
    logger.info(
        "invitation revoked workspace_id=%s actor_id=%s invitation_id=%s",
        actor.workspace_id,
        actor.user_id,
        invitation.pk,
    )


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
    logger.info(
        "invitation accepted workspace_id=%s actor_id=%s invitation_id=%s",
        invitation.workspace_id,
        user.pk,
        invitation.pk,
    )
    return membership


def decline_invitation(user, raw_token):
    invitation = get_pending_invitation(raw_token)
    if user.email.lower() != invitation.email.lower():
        raise InvitationEmailMismatch
    invitation.expires_at = timezone.now()
    invitation.save(update_fields=["expires_at"])
    logger.info(
        "invitation declined workspace_id=%s actor_id=%s invitation_id=%s",
        invitation.workspace_id,
        user.pk,
        invitation.pk,
    )
