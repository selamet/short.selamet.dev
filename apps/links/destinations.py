"""Destination URL validation.

The same checks run when a link is saved and again before any outbound fetch, because
DNS can change between the two.
"""

import ipaddress
import re
import socket
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
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


def resolve_host(host, timeout):
    """Resolve `host` and return its addresses, validated against the same
    private-address rules a literal IP goes through.

    The lookup runs on a worker thread so a slow or hanging resolver cannot run past
    `timeout`: `future.result(timeout=...)` returns (or raises) on time even though the
    blocking `getaddrinfo` call itself cannot be cancelled. The executor is shut down
    without waiting for that worker, since there is no portable way to cancel it — a
    hung resolution keeps running in the background rather than making this call hang
    too.
    """
    host = host.strip("[]")
    executor = ThreadPoolExecutor(max_workers=1)
    try:
        future = executor.submit(socket.getaddrinfo, host, None)
        try:
            infos = future.result(timeout=timeout)
        except (FutureTimeoutError, OSError) as error:
            raise ValidationError("Could not resolve that host.") from error
    finally:
        executor.shutdown(wait=False)
    addresses = [info[4][0] for info in infos]
    if any(_is_private(ipaddress.ip_address(address)) for address in addresses):
        raise ValidationError("Private and local addresses cannot be used as destinations.")
    return addresses


def _rebuild_netloc(parts, host):
    """Re-assemble netloc from the normalized host and port, dropping any userinfo.

    A rebuilt "user@host" netloc can be parsed differently by another URL parser than
    it was by `urlsplit` here (e.g. "https://example.com\\@evil.com/" is validated
    against the host "evil.com" but a naive parser downstream could read "example.com"
    instead), so userinfo never survives into the stored/returned URL.
    """
    netloc_host = f"[{host}]" if ":" in host else host
    return netloc_host if parts.port is None else f"{netloc_host}:{parts.port}"


def validate_destination(url, check_dns=False):
    url = (url or "").strip()
    parts = urlsplit(url)
    if parts.scheme.lower() not in ALLOWED_SCHEMES or not parts.netloc:
        raise ValidationError("Enter a full URL starting with http:// or https://.")
    try:
        _ = parts.port
    except ValueError as error:
        raise ValidationError("Enter a full URL starting with http:// or https://.") from error
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
    if check_dns:
        resolve_host(host, settings.LINK_METADATA_DNS_TIMEOUT)
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
