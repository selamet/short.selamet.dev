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

# The top-level keys payload_from_link always sets. A cached value missing any of
# these, or that is not even a dict (a stale shape from before a CACHE_VERSION bump
# that somehow survived, a string, a list, whatever), is treated as a miss rather than
# indexed into blindly, so a payload shape change is never an unhandled exception on
# the hot path.
EXPECTED_PAYLOAD_KEYS = frozenset(
    {
        "id",
        "status",
        "destination_url",
        "expires_at",
        "max_clicks",
        "click_count",
        "utm",
        "og",
        "targets",
    }
)


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


def _has_expected_shape(payload):
    return isinstance(payload, dict) and EXPECTED_PAYLOAD_KEYS.issubset(payload)


def _payload_for(code):
    cached = redirect_cache.get_payload(code)
    if cached == redirect_cache.MISS:
        return None
    if cached is not None:
        if _has_expected_shape(cached):
            return cached
        logger.warning("cached payload for %s had an unexpected shape; reloading", code)
    link = Link.objects.filter(code=code).prefetch_related("targets").first()
    if link is None:
        if _looks_worth_caching_as_a_miss(code):
            redirect_cache.set_miss(code)
        return None
    payload = redirect_cache.payload_from_link(link)
    redirect_cache.set_payload(code, payload)
    return payload


def _is_expired(code, payload):
    # A malformed expires_at (wrong type, unparsable string) or a naive one (no
    # timezone, which makes the comparison below raise TypeError under USE_TZ) is
    # treated as not expired rather than raising: whatever produced it, that is not
    # grounds to block a redirect that would otherwise work.
    expires_at = payload.get("expires_at")
    if expires_at:
        try:
            if datetime.fromisoformat(expires_at) <= timezone.now():
                return True
        except (TypeError, ValueError):
            pass
    max_clicks = payload.get("max_clicks")
    if not max_clicks:
        return False
    # max_clicks is a soft cap, not a hard one: the counter this reads lags the
    # redirect it is about to let through by design (bump_click_count runs from the
    # click task, after this resolve() call returns), so a short burst of concurrent
    # requests can all see a count under the cap and all be let through before it
    # catches up. Good enough for "stop serving after roughly N clicks", not a
    # guarantee of exactly N.
    click_count = redirect_cache.get_click_count(code)
    if click_count is None:
        click_count = payload.get("click_count", 0)
    return click_count >= max_clicks


def choose_target(payload, platform):
    """The row for this platform, or the link's own destination."""
    targets = payload.get("targets") or {}
    target = targets.get(platform)
    if target and (target.get("url") or target.get("app_url")):
        return target
    return {"url": payload.get("destination_url", ""), "app_url": "", "fallback_url": ""}


def resolve(code, user_agent):
    code = code_utils.normalize_code(code)
    if not _is_lookupable(code):
        return None
    payload = _payload_for(code)
    if payload is None:
        return None
    platform = platforms.detect_platform(user_agent)
    target = choose_target(payload, platform)
    utm = payload.get("utm") or {}
    destination_url = payload.get("destination_url", "")
    base_url = target.get("url") or target.get("fallback_url") or destination_url
    target_fallback_url = target.get("fallback_url")
    fallback_url = utm_utils.merge_utm(target_fallback_url, utm) if target_fallback_url else ""
    return Resolution(
        link_id=payload.get("id"),
        status=payload.get("status", Link.Status.DISABLED),
        url=utm_utils.merge_utm(base_url, utm),
        platform=platform,
        app_url=target.get("app_url", ""),
        fallback_url=fallback_url,
        expired=_is_expired(code, payload),
        og=payload.get("og") or {},
    )
