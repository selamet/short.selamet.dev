"""Destination URL validation.

The same checks run when a link is saved and again before any outbound fetch, because
DNS can change between the two.
"""

import ipaddress
import socket
from urllib.parse import urlsplit, urlunsplit

from django.conf import settings
from django.core.exceptions import ValidationError

ALLOWED_SCHEMES = {"http", "https"}


def is_blocked_host(host):
    host = (host or "").lower().rstrip(".")
    for blocked in settings.BLOCKED_LINK_DOMAINS:
        blocked = blocked.lower().strip()
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


def validate_destination(url, check_dns=False):
    url = (url or "").strip()
    parts = urlsplit(url)
    if parts.scheme.lower() not in ALLOWED_SCHEMES or not parts.netloc:
        raise ValidationError("Enter a full URL starting with http:// or https://.")
    host = (parts.hostname or "").lower()
    if not host:
        raise ValidationError("Enter a full URL starting with http:// or https://.")
    short_host = settings.SHORT_DOMAIN.split(":")[0].lower()
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
    netloc = parts.netloc.lower()
    return urlunsplit((parts.scheme.lower(), netloc, parts.path, parts.query, parts.fragment))
