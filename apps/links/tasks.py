"""Fetch the destination's title, favicon and Open Graph tags out of band."""

import logging
import time
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

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


def _open_stream(client, url):
    """Thin seam over httpx.Client.stream so tests can fake responses without a socket."""
    return client.stream("GET", url)


def _fetch_html(url):
    """Download the destination, validating every redirect hop and capping size, time
    and hop count.

    httpx's own `follow_redirects=True` only validates the URL it is given and the one
    it lands on, so a destination could redirect through an internal address in between.
    Redirects are therefore followed by hand, re-validating (including DNS) before each
    hop is requested.
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
            with _open_stream(client, current_url) as response:
                if response.is_redirect:
                    location = response.headers.get("location", "")
                    next_url = urljoin(current_url, location)
                    current_url = destinations.validate_destination(next_url, check_dns=True)
                    continue
                response.raise_for_status()
                if "html" not in response.headers.get("content-type", ""):
                    return ""
                chunks, size = [], 0
                for chunk in response.iter_bytes():
                    if time.monotonic() > deadline:
                        break
                    size += len(chunk)
                    if size > settings.LINK_METADATA_MAX_BYTES:
                        break
                    chunks.append(chunk)
                return b"".join(chunks).decode("utf-8", errors="replace")
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
    html = _fetch_html(url)
    parser = _MetadataParser()
    parser.feed(html or "")
    og_title = parser.og.get("og:title", "")
    title = og_title or parser.title
    favicon_url = _safe_url(urljoin(url, parser.icon)[:1024]) if parser.icon else ""
    return {
        "title": title[:200],
        "favicon_url": favicon_url,
        "og_title": og_title[:200],
        "og_description": parser.og.get("og:description", "")[:400],
        "og_image_url": _safe_url(parser.og.get("og:image", "")[:1024]),
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
