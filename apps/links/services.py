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
    changed = []
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
    link.og_overridden = bool(link.og_title or link.og_description or link.og_image_url)
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
    logger.info(
        "%s workspace=%s actor=%s code=%s", event, link.workspace_id, actor.user_id, link.code
    )
    return link


def archive_link(actor, link):
    return _set_status(actor, link, Link.Status.ARCHIVED, "link.archive")


def restore_link(actor, link):
    return _set_status(actor, link, Link.Status.ACTIVE, "link.restore")
