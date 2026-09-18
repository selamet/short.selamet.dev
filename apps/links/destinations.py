"""Destination URL validation.

The same checks run when a link is saved and again before any outbound fetch, because
DNS can change between the two.
"""

import ipaddress
import re
import socket
from urllib.parse import urlsplit, urlunsplit

from django.conf import settings
from django.core.exceptions import ValidationError

ALLOWED_SCHEMES = {"http", "https"}

# Schemes an app-link target must never use, checked after control characters are
# stripped (see `validate_app_url`).
DENIED_APP_SCHEMES = {"javascript", "data", "vbscript", "blob", "file", "about"}
_APP_SCHEME_RE = re.compile(r"^([a-z][a-z0-9+.-]*):", re.IGNORECASE)
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x1f\x7f]")


def _normalize_host(host):
    """Lowercase and drop a trailing dot, so "example.com." can't dodge a string check
    that "example.com" would fail."""
    return (host or "").strip().rstrip(".").lower()


def _idna(host):
    """Punycode form of a host, so a Unicode entry and its ASCII form compare equal."""
    try:
        return host.encode("idna").decode("ascii")
    except UnicodeError:
        return host


def is_blocked_host(host):
    host = _idna(_normalize_host(host))
    for blocked in settings.BLOCKED_LINK_DOMAINS:
        blocked = _idna(_normalize_host(blocked))
        if blocked and (host == blocked or host.endswith(f".{blocked}")):
            return True
    return False


def _is_private(address):
    return (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
        or address.is_multicast
        or address.is_unspecified
    )


def resolves_to_private_address(host):
    """True when the host is, or resolves to, an address we must not reach."""
    try:
        return _is_private(ipaddress.ip_address(host.strip("[]")))
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        # Unresolvable today is not proof of safety, but it is not a private target either.
        return False
    return any(_is_private(ipaddress.ip_address(info[4][0])) for info in infos)


def _rebuild_netloc(parts, host):
    """Re-assemble netloc from the normalized host, keeping any port and userinfo."""
    netloc_host = f"[{host}]" if ":" in host else host
    netloc = netloc_host if parts.port is None else f"{netloc_host}:{parts.port}"
    if parts.username:
        userinfo = (
            parts.username if parts.password is None else f"{parts.username}:{parts.password}"
        )
        netloc = f"{userinfo}@{netloc}"
    return netloc


def validate_destination(url, check_dns=False):
    url = (url or "").strip()
    parts = urlsplit(url)
    if parts.scheme.lower() not in ALLOWED_SCHEMES or not parts.netloc:
        raise ValidationError("Enter a full URL starting with http:// or https://.")
    host = _normalize_host(parts.hostname)
    if not host:
        raise ValidationError("Enter a full URL starting with http:// or https://.")
    short_host = _normalize_host(settings.SHORT_DOMAIN.split(":")[0])
    if host == short_host or host == "localhost" or host.endswith(".localhost"):
        raise ValidationError("That address points back at this shortener.")
    if is_blocked_host(host):
        raise ValidationError("This domain is not allowed.")
    try:
        if _is_private(ipaddress.ip_address(host.strip("[]"))):
            raise ValidationError("Private and local addresses cannot be used as destinations.")
    except ValueError:
        pass
    if check_dns and resolves_to_private_address(host):
        raise ValidationError("Private and local addresses cannot be used as destinations.")
    netloc = _rebuild_netloc(parts, host)
    return urlunsplit((parts.scheme.lower(), netloc, parts.path, parts.query, parts.fragment))


def validate_app_url(value, check_dns=False):
    """Validate a custom-scheme app-link target (e.g. "instagram://user?username=acme").

    Browsers strip embedded control characters (tabs, newlines, ...) from a URL before
    parsing its scheme, so "java\\nscript:alert(1)" is not a syntax error to them, it is
    "javascript:alert(1)". Strip the same characters here before the scheme is read, or
    a control character could smuggle a denied scheme past a naive check.
    """
    cleaned = _CONTROL_CHARS_RE.sub("", (value or "")).strip()
    match = _APP_SCHEME_RE.match(cleaned)
    if not match:
        raise ValidationError("Enter a valid app link, e.g. instagram://user?username=acme.")
    scheme = match.group(1).lower()
    if scheme in DENIED_APP_SCHEMES:
        raise ValidationError("This app scheme is not allowed.")
    if scheme in ALLOWED_SCHEMES:
        return validate_destination(cleaned, check_dns=check_dns)
    return cleaned
