"""Fetch the destination's title, favicon and Open Graph tags out of band."""

import logging
import time
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx
from django.conf import settings
from django.tasks import task
from django.utils import timezone

from . import destinations
from .models import Link

logger = logging.getLogger(__name__)


class _MetadataParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.og = {}
        self.title = ""
        self.icon = ""
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "meta":
            key = (attributes.get("property") or attributes.get("name") or "").lower()
            if key.startswith("og:") and attributes.get("content"):
                self.og[key] = attributes["content"].strip()
        elif tag == "link":
            rel = (attributes.get("rel") or "").lower()
            if "icon" in rel and attributes.get("href") and not self.icon:
                self.icon = attributes["href"].strip()
        elif tag == "title":
            self._in_title = True

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title and not self.title:
            self.title = data.strip()


def _open_stream(client, url, *, headers=None, extensions=None):
    """Thin seam over httpx.Client.stream so tests can fake responses without a socket."""
    return client.stream("GET", url, headers=headers, extensions=extensions)


def _pin_address(url):
    """Resolve the validated URL's host once and rebuild the request against the
    resolved address, so a second DNS answer (e.g. a short-TTL record flipping between
    validation and the actual connection) cannot re-point the request at a different,
    unvalidated address. The original host still travels as the Host header and as the
    `sni_hostname` extension, so the server gets the name it expects and TLS still
    verifies against it.
    """
    parts = urlsplit(url)
    original_host = parts.hostname
    address = destinations.resolve_host(original_host, settings.LINK_METADATA_DNS_TIMEOUT)[0]
    pinned_host = f"[{address}]" if ":" in address else address
    netloc = pinned_host if parts.port is None else f"{pinned_host}:{parts.port}"
    pinned_url = urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))
    return pinned_url, {"Host": parts.netloc}, {"sni_hostname": original_host}


def _fetch_html(url):
    """Download the destination, validating every redirect hop and capping size, time
    and hop count. Returns `(html, final_url)`; `final_url` is used to resolve any
    relative favicon/og:image found in the page.

    httpx's own `follow_redirects=True` only validates the URL it is given and the one
    it lands on, so a destination could redirect through an internal address in between.
    Redirects are therefore followed by hand, re-validating (including DNS) before each
    hop is requested, and the actual connection is pinned to the address that
    validation just resolved (see `_pin_address`).
    """
    deadline = time.monotonic() + settings.LINK_METADATA_TOTAL_TIMEOUT
    current_url = destinations.validate_destination(url, check_dns=True)
    timeout = httpx.Timeout(settings.LINK_METADATA_TIMEOUT)
    with httpx.Client(
        timeout=timeout,
        follow_redirects=False,
        headers={"User-Agent": f"{settings.SITE_NAME}-metadata/1.0"},
    ) as client:
        for _ in range(settings.LINK_METADATA_MAX_REDIRECTS + 1):
            if time.monotonic() > deadline:
                raise TimeoutError("metadata fetch exceeded its deadline")
            pinned_url, headers, extensions = _pin_address(current_url)
            stream = _open_stream(client, pinned_url, headers=headers, extensions=extensions)
            with stream as response:
                if response.is_redirect:
                    location = response.headers.get("location", "")
                    next_url = urljoin(current_url, location)
                    current_url = destinations.validate_destination(next_url, check_dns=True)
                    continue
                response.raise_for_status()
                if "html" not in response.headers.get("content-type", ""):
                    return "", current_url
                chunks, size = [], 0
                for chunk in response.iter_bytes():
                    if time.monotonic() > deadline:
                        break
                    size += len(chunk)
                    if size > settings.LINK_METADATA_MAX_BYTES:
                        break
                    chunks.append(chunk)
                return b"".join(chunks).decode("utf-8", errors="replace"), current_url
    raise RuntimeError("too many redirects")


def _safe_url(value):
    """Drop a URL whose scheme is not http/https.

    Fetched page content can advertise anything as a favicon or og:image href,
    including `javascript:`/`data:` URLs; those must never be stored or rendered
    as a link/image source. This is a scheme check only, no DNS lookup: it runs
    against already-fetched content, not before an outbound request.
    """
    if not value:
        return ""
    if urlsplit(value).scheme.lower() not in ("http", "https"):
        return ""
    return value


def extract_metadata(url):
    """Validate, fetch and parse a destination's title, favicon and Open Graph tags."""
    html, final_url = _fetch_html(url)
    parser = _MetadataParser()
    parser.feed(html or "")
    og_title = parser.og.get("og:title", "")
    title = og_title or parser.title
    # A relative favicon/og:image is resolved against the URL the fetch actually
    # landed on, not the one the fetch started at, or a redirect to another host
    # would silently point either at the wrong site.
    favicon_url = _safe_url(urljoin(final_url, parser.icon)[:1024]) if parser.icon else ""
    og_image = parser.og.get("og:image", "")
    og_image_url = _safe_url(urljoin(final_url, og_image)[:1024]) if og_image else ""
    return {
        "title": title[:200],
        "favicon_url": favicon_url,
        "og_title": og_title[:200],
        "og_description": parser.og.get("og:description", "")[:400],
        "og_image_url": og_image_url,
    }


@task
def fetch_link_metadata(link_id):
    try:
        link = Link.objects.get(pk=link_id)
    except Link.DoesNotExist:
        logger.warning("metadata fetch skipped: link_id=%s no longer exists", link_id)
        return
    try:
        metadata = extract_metadata(link.destination_url)
    except Exception:
        logger.warning("metadata fetch failed for link_id=%s", link_id, exc_info=True)
        return
    fields = []
    if metadata["title"]:
        link.title = metadata["title"]
        fields.append("title")
    if metadata["favicon_url"]:
        link.favicon_url = metadata["favicon_url"]
        fields.append("favicon_url")
    elif not link.favicon_url:
        parts = urlsplit(link.destination_url)
        link.favicon_url = f"{parts.scheme}://{parts.netloc}/favicon.ico"
        fields.append("favicon_url")
    if not link.og_overridden:
        link.og_title = metadata["og_title"]
        link.og_description = metadata["og_description"]
        link.og_image_url = metadata["og_image_url"]
        fields += ["og_title", "og_description", "og_image_url"]
    link.og_fetched_at = timezone.now()
    fields.append("og_fetched_at")
    link.save(update_fields=sorted(set(fields)))
