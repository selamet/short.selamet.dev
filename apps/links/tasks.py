"""Fetch the destination's title, favicon and Open Graph tags out of band."""

import logging
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


def _fetch_html(url):
    """Download the destination, re-validating it and capping size and redirects."""
    destinations.validate_destination(url, check_dns=True)
    with httpx.Client(
        timeout=settings.LINK_METADATA_TIMEOUT,
        follow_redirects=True,
        max_redirects=3,
        headers={"User-Agent": f"{settings.SITE_NAME}-metadata/1.0"},
    ) as client:
        with client.stream("GET", url) as response:
            response.raise_for_status()
            destinations.validate_destination(str(response.url), check_dns=True)
            if "html" not in response.headers.get("content-type", ""):
                return ""
            chunks, size = [], 0
            for chunk in response.iter_bytes():
                size += len(chunk)
                if size > settings.LINK_METADATA_MAX_BYTES:
                    break
                chunks.append(chunk)
    return b"".join(chunks).decode("utf-8", errors="replace")


def extract_metadata(url):
    """Validate, fetch and parse a destination's title, favicon and Open Graph tags."""
    html = _fetch_html(url)
    parser = _MetadataParser()
    parser.feed(html or "")
    og_title = parser.og.get("og:title", "")
    title = og_title or parser.title
    favicon_url = urljoin(url, parser.icon)[:1024] if parser.icon else ""
    return {
        "title": title[:200],
        "favicon_url": favicon_url,
        "og_title": og_title[:200],
        "og_description": parser.og.get("og:description", "")[:400],
        "og_image_url": parser.og.get("og:image", "")[:1024],
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
