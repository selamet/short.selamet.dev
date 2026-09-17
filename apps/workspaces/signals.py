"""Keep every workspace owned when a user's account is deleted."""

import logging

from .models import Membership, Role

logger = logging.getLogger(__name__)


def reassign_ownership_on_user_delete(sender, instance, **kwargs):
    """Reassign or clean up any workspace the deleted user owned.

    Runs on pre_delete: Django sends pre_delete for every object a delete() call
    will cascade (the user, and each of their Membership rows via CASCADE) before
    it deletes any of them, so the owner's Membership row is still present here.
    It is removed explicitly, ahead of Django's own cascade, so the
    single-owner-per-workspace constraint never has to hold two owners at once
    while a replacement is promoted; Django's later cascade delete of the same
    (now already-gone) row is a harmless no-op.

    Ruling: ownership passes to the oldest remaining admin; with no admin, to the
    oldest remaining member; with no members left, the workspace is deleted.
    """
    owned = Membership.objects.filter(user=instance, role=Role.OWNER).select_related("workspace")
    for owner_membership in owned:
        workspace = owner_membership.workspace
        owner_membership.delete()
        replacement = (
            Membership.objects.filter(workspace=workspace, role=Role.ADMIN)
            .order_by("created_at")
            .first()
            or Membership.objects.filter(workspace=workspace, role=Role.MEMBER)
            .order_by("created_at")
            .first()
        )
        if replacement is not None:
            replacement.role = Role.OWNER
            replacement.save(update_fields=["role"])
            logger.info(
                "workspace ownership reassigned workspace_id=%s new_owner_id=%s "
                "previous_owner_id=%s",
                workspace.pk,
                replacement.user_id,
                instance.pk,
            )
        else:
            workspace.delete()
            logger.info(
                "workspace deleted after its last member's account was removed "
                "workspace_id=%s previous_owner_id=%s",
                workspace.pk,
                instance.pk,
            )
