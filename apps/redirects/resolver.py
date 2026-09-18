"""Turn a short code and a user agent into the URL a visitor should be sent to."""

import logging
from dataclasses import dataclass, field
from datetime import datetime

from django.conf import settings
from django.utils import timezone

from apps.links import codes as code_utils
from apps.links import utm as utm_utils
from apps.links.models import Link
from apps.links.reserved import RESERVED_CODES

from . import cache as redirect_cache
from . import platforms

logger = logging.getLogger(__name__)

# A custom code this short is plausible for a human to have typed; anything longer
# that still isn't a generated code looks more like a scan trying to grow the
# negative cache than a real link, so its miss is not worth remembering.
PLAUSIBLE_CUSTOM_CODE_MAX_LENGTH = 20


@dataclass
class Resolution:
    link_id: int
    status: str
    url: str
    platform: str
    app_url: str = ""
    fallback_url: str = ""
    expired: bool = False
    og: dict = field(default_factory=dict)


def _is_lookupable(code):
    if not code or code in RESERVED_CODES:
        return False
    return bool(code_utils.CODE_RE.match(code))


def _looks_worth_caching_as_a_miss(code):
    """Only remember a miss for a code that looks like it could plausibly be a real
    link: either the exact shape of a generated code (drawn only from `codes.ALPHABET`,
    `LINK_CODE_LENGTH` characters long), or short enough to be a plausible custom code.
    Anything else is skipped so a scan built from long, arbitrary strings cannot grow
    the negative cache without bound.
    """
    if len(code) == settings.LINK_CODE_LENGTH and all(c in code_utils.ALPHABET for c in code):
        return True
    return len(code) <= PLAUSIBLE_CUSTOM_CODE_MAX_LENGTH


def _payload_for(code):
    cached = redirect_cache.get_payload(code)
    if cached == redirect_cache.MISS:
        return None
    if cached is not None:
        return cached
    link = Link.objects.filter(code=code).prefetch_related("targets").first()
    if link is None:
        if _looks_worth_caching_as_a_miss(code):
            redirect_cache.set_miss(code)
        return None
    payload = redirect_cache.payload_from_link(link)
    redirect_cache.set_payload(code, payload)
    return payload


def _is_expired(payload):
    expires_at = payload.get("expires_at")
    if expires_at and datetime.fromisoformat(expires_at) <= timezone.now():
        return True
    max_clicks = payload.get("max_clicks")
    return bool(max_clicks and payload.get("click_count", 0) >= max_clicks)


def choose_target(payload, platform):
    """The row for this platform, or the link's own destination."""
    target = payload["targets"].get(platform)
    if target and (target["url"] or target["app_url"]):
        return target
    return {"url": payload["destination_url"], "app_url": "", "fallback_url": ""}


def resolve(code, user_agent):
    code = code_utils.normalize_code(code)
    if not _is_lookupable(code):
        return None
    payload = _payload_for(code)
    if payload is None:
        return None
    platform = platforms.detect_platform(user_agent)
    target = choose_target(payload, platform)
    base_url = target["url"] or target["fallback_url"] or payload["destination_url"]
    fallback_url = (
        utm_utils.merge_utm(target["fallback_url"], payload["utm"])
        if target["fallback_url"]
        else ""
    )
    return Resolution(
        link_id=payload["id"],
        status=payload["status"],
        url=utm_utils.merge_utm(base_url, payload["utm"]),
        platform=platform,
        app_url=target["app_url"],
        fallback_url=fallback_url,
        expired=_is_expired(payload),
        og=payload["og"],
    )
