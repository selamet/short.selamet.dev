"""Link rules: codes, destinations, targets, tags and lifecycle.

Every function takes the acting Membership so the dashboard and the API enforce the
same permissions.
"""

import logging

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from apps.core import ratelimit
from apps.workspaces.permissions import can

from . import codes as code_utils
from . import destinations
from .models import Link, LinkTarget, Tag

logger = logging.getLogger(__name__)

UTM_FIELDS = ("utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term")
EDITABLE_FIELDS = (
    "destination_url",
    "note",
    "og_title",
    "og_description",
    "og_image_url",
    *UTM_FIELDS,
)


class InvalidOperation(Exception):
    """The action is not allowed for this actor, or not allowed in this state."""


def _require_manage(actor):
    if not can(actor, "links.manage"):
        raise InvalidOperation("You cannot manage links in this workspace.")


def _require_same_workspace(actor, link):
    if link.workspace_id != actor.workspace_id:
        raise InvalidOperation("This link belongs to another workspace.")


def short_url(link):
    return f"{settings.SITE_URL.rstrip('/')}/{link.code}"


def _invalidate_on_commit(*codes):
    """Clear the redirect cache for one or more codes once the current transaction
    actually commits, so a write that later rolls back never clears a good entry.

    The redirect cache is imported lazily, inside the callback, to keep the app
    dependency one-directional: apps.redirects already imports from apps.links, so a
    module-level import here would be circular.
    """
    unique_codes = {code for code in codes if code}
    if not unique_codes:
        return

    def _invalidate():
        from apps.redirects import cache as redirect_cache

        for code in unique_codes:
            redirect_cache.invalidate(code)

    transaction.on_commit(_invalidate)


def code_available(code, exclude=None):
    code = code_utils.normalize_code(code)
    query = Link.objects.filter(code=code)
    if exclude is not None:
        query = query.exclude(pk=exclude.pk)
    return not query.exists()


def _resolve_code(code, exclude=None):
    if code:
        code = code_utils.validate_code(code)
        if not code_available(code, exclude=exclude):
            raise ValidationError("That code is already taken.")
        return code
    for _ in range(10):
        candidate = code_utils.generate_code()
        if code_available(candidate):
            return candidate
    raise ValidationError("Could not allocate a short code. Try again.")


def set_tags(actor, link, names):
    _require_manage(actor)
    _require_same_workspace(actor, link)
    tags = []
    for raw in names or []:
        name = (raw or "").strip().lower()
        if not name:
            continue
        # get_or_create still races: two concurrent creates for the same new name can
        # both miss the SELECT and then collide on the unique constraint. Django's own
        # retry inside get_or_create re-queries with an exact match, which misses a row
        # saved under different casing, so fall back to an explicit case-insensitive read.
        try:
            tag, _created = Tag.objects.get_or_create(workspace=link.workspace, name=name)
        except IntegrityError:
            tag = Tag.objects.get(workspace=link.workspace, name__iexact=name)
        tags.append(tag)
    link.tags.set(tags)
    _invalidate_on_commit(link.code)
    return tags


def set_targets(actor, link, rows):
    """Replace the per-device rows. An empty list turns device routing off."""
    _require_manage(actor)
    _require_same_workspace(actor, link)
    cleaned = []
    for row in rows or []:
        platform = (row.get("platform") or "").strip()
        if platform not in LinkTarget.Platform.values:
            raise ValidationError("Unknown platform.")
        url = (row.get("url") or "").strip()
        app_url = (row.get("app_url") or "").strip()
        fallback_url = (row.get("fallback_url") or "").strip()
        if not url and not app_url:
            continue
        if url:
            url = destinations.validate_destination(url, check_dns=True)
        if app_url:
            app_url = destinations.validate_app_url(app_url, check_dns=True)
        if app_url and not fallback_url:
            raise ValidationError("An app scheme needs a web fallback URL.")
        if fallback_url:
            fallback_url = destinations.validate_destination(fallback_url, check_dns=True)
        cleaned.append(
            {"platform": platform, "url": url, "app_url": app_url, "fallback_url": fallback_url}
        )
    with transaction.atomic():
        link.targets.all().delete()
        LinkTarget.objects.bulk_create([LinkTarget(link=link, **row) for row in cleaned])
    _invalidate_on_commit(link.code)
    return cleaned


def _check_rate_limits(actor):
    if not ratelimit.hit(
        "link-create-user",
        str(actor.user_id),
        settings.LINK_RATE_PER_USER,
        settings.LINK_RATE_PER_USER_WINDOW,
    ):
        raise InvalidOperation("Too many links created. Slow down for a moment.")
    if not ratelimit.hit(
        "link-create-workspace",
        str(actor.workspace_id),
        settings.LINK_RATE_PER_WORKSPACE,
        settings.LINK_RATE_PER_WORKSPACE_WINDOW,
    ):
        raise InvalidOperation("This workspace has created too many links recently.")


def create_link(actor, destination_url, code="", tags=None, targets=None, **fields):
    _require_manage(actor)
    destination_url = destinations.validate_destination(destination_url, check_dns=True)
    og_image_url = (fields.get("og_image_url") or "").strip()
    if og_image_url:
        fields["og_image_url"] = destinations.validate_destination(og_image_url, check_dns=True)
    _check_rate_limits(actor)
    code = _resolve_code(code)
    values = {key: (fields.get(key) or "") for key in EDITABLE_FIELDS if key != "destination_url"}
    try:
        with transaction.atomic():
            link = Link.objects.create(
                workspace=actor.workspace,
                code=code,
                destination_url=destination_url,
                created_by=actor.user,
                expires_at=fields.get("expires_at"),
                max_clicks=fields.get("max_clicks"),
                og_overridden=bool(
                    values["og_title"] or values["og_description"] or values["og_image_url"]
                ),
                **values,
            )
            if tags:
                set_tags(actor, link, tags)
            if targets:
                set_targets(actor, link, targets)
    except IntegrityError as error:
        raise ValidationError("That code is already taken.") from error
    # Synchronous, not deferred to commit: this only ever clears a negative cache entry
    # (or nothing), so a code that was probed a moment ago starts working immediately,
    # and there is no "good entry" a later rollback could be protecting.
    from apps.redirects import cache as redirect_cache

    redirect_cache.invalidate(code)
    logger.info(
        "link.create workspace=%s actor=%s code=%s", link.workspace_id, actor.user_id, link.code
    )
    from .tasks import fetch_link_metadata

    # Deferred until commit: enqueuing before the row is durably saved could hand the
    # metadata task a link_id no other transaction can see yet.
    transaction.on_commit(lambda: fetch_link_metadata.enqueue(link.pk))
    return link


def update_link(actor, link, destination_url=None, code=None, tags=None, targets=None, **fields):
    _require_manage(actor)
    _require_same_workspace(actor, link)
    old_code = link.code
    changed = []
    # Snapshot of what a fetch (or an earlier override) last stored, taken before the
    # loop below overwrites it, so an edit form that simply re-submits the same values
    # it was seeded with does not look like a fresh override (I9).
    previous_og = {
        key: getattr(link, key) for key in ("og_title", "og_description", "og_image_url")
    }
    if destination_url is not None:
        new_destination = destinations.validate_destination(destination_url, check_dns=True)
        if new_destination != link.destination_url:
            _check_rate_limits(actor)
            link.destination_url = new_destination
            link.og_fetched_at = None
            changed += ["destination_url", "og_fetched_at"]
    if code is not None and code_utils.normalize_code(code) != link.code:
        link.code = _resolve_code(code, exclude=link)
        changed.append("code")
    for key in EDITABLE_FIELDS:
        if key == "destination_url" or key not in fields:
            continue
        value = fields.get(key) or ""
        if key == "og_image_url" and value:
            value = destinations.validate_destination(value, check_dns=True)
        setattr(link, key, value)
        changed.append(key)
    if "expires_at" in fields:
        link.expires_at = fields["expires_at"]
        changed.append("expires_at")
    if "max_clicks" in fields:
        link.max_clicks = fields["max_clicks"]
        changed.append("max_clicks")
    submitted_og = {key: getattr(link, key) for key in previous_og}
    if not any(submitted_og.values()):
        # The user cleared every override field: let the next fetch refill them.
        link.og_overridden = False
        changed.append("og_overridden")
    elif submitted_og != previous_og:
        # At least one field actually changed from what was last stored: this is a
        # deliberate override, not just the edit form re-submitting fetched values.
        link.og_overridden = True
        changed.append("og_overridden")
    try:
        with transaction.atomic():
            link.save(update_fields=sorted(set(changed)) or None)
            if tags is not None:
                set_tags(actor, link, tags)
            if targets is not None:
                set_targets(actor, link, targets)
    except IntegrityError as error:
        raise ValidationError("That code is already taken.") from error
    # The old code always needs invalidating (any field may have changed the cached
    # payload); the new one only matters when the code itself changed, but passing both
    # is harmless since _invalidate_on_commit dedupes.
    _invalidate_on_commit(old_code, link.code)
    logger.info(
        "link.update workspace=%s actor=%s code=%s", link.workspace_id, actor.user_id, link.code
    )
    if "destination_url" in changed:
        from .tasks import fetch_link_metadata

        transaction.on_commit(lambda: fetch_link_metadata.enqueue(link.pk))
    return link


def _set_status(actor, link, status, event):
    _require_manage(actor)
    _require_same_workspace(actor, link)
    # A light throttle of its own (distinct scope from link creation/destination edits)
    # so archiving/restoring in a loop cannot be used to spam the audit log.
    if not ratelimit.hit(
        "link-status-user",
        str(actor.user_id),
        settings.LINK_RATE_PER_USER,
        settings.LINK_RATE_PER_USER_WINDOW,
    ):
        raise InvalidOperation("Too many changes. Slow down for a moment.")
    link.status = status
    link.save(update_fields=["status"])
    _invalidate_on_commit(link.code)
    logger.info(
        "%s workspace=%s actor=%s code=%s", event, link.workspace_id, actor.user_id, link.code
    )
    return link


def archive_link(actor, link):
    return _set_status(actor, link, Link.Status.ARCHIVED, "link.archive")


def restore_link(actor, link):
    return _set_status(actor, link, Link.Status.ACTIVE, "link.restore")
