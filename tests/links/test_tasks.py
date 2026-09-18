import pytest
from django.core.exceptions import ValidationError

from apps.links import destinations, services
from apps.links.tasks import _fetch_html, extract_metadata, fetch_link_metadata

FAKE_PUBLIC_ADDRESS = "93.184.216.34"

HTML = """
<html><head>
<title>Fallback title</title>
<link rel="icon" href="/favicon.ico">
<meta property="og:title" content="Spring drop is live">
<meta property="og:description" content="40 new pieces.">
<meta property="og:image" content="https://cdn.example.com/card.png">
</head><body></body></html>
"""


@pytest.fixture
def link(owner_membership):
    return services.create_link(owner_membership, destination_url="https://example.com/p")


def test_fetch_link_metadata_fills_title_favicon_and_og(link, monkeypatch):
    monkeypatch.setattr("apps.links.tasks._fetch_html", lambda url: (HTML, url))
    fetch_link_metadata.enqueue(link.pk)
    link.refresh_from_db()
    assert link.title == "Spring drop is live"
    assert link.og_title == "Spring drop is live"
    assert link.og_description == "40 new pieces."
    assert link.og_image_url == "https://cdn.example.com/card.png"
    assert link.favicon_url == "https://example.com/favicon.ico"
    assert link.og_fetched_at is not None


def test_fetch_link_metadata_falls_back_to_the_title_tag(link, monkeypatch):
    monkeypatch.setattr(
        "apps.links.tasks._fetch_html",
        lambda url: ("<html><head><title>Fallback title</title></head></html>", url),
    )
    fetch_link_metadata.enqueue(link.pk)
    link.refresh_from_db()
    assert link.title == "Fallback title"
    assert link.og_title == ""


def test_fetch_link_metadata_drops_an_unsafe_og_image_url(link, monkeypatch):
    monkeypatch.setattr(
        "apps.links.tasks._fetch_html",
        lambda url: (
            '<html><head><meta property="og:image" content="javascript:alert(1)"></head></html>',
            url,
        ),
    )
    fetch_link_metadata.enqueue(link.pk)
    link.refresh_from_db()
    assert link.og_image_url == ""


def test_fetch_link_metadata_never_overwrites_an_override(link, monkeypatch):
    link.og_title = "Mine"
    link.og_overridden = True
    link.save()
    monkeypatch.setattr("apps.links.tasks._fetch_html", lambda url: (HTML, url))
    fetch_link_metadata.enqueue(link.pk)
    link.refresh_from_db()
    assert link.og_title == "Mine"


def test_fetch_link_metadata_survives_a_failed_fetch(link, monkeypatch, caplog):
    def boom(url):
        raise RuntimeError("down")

    monkeypatch.setattr("apps.links.tasks._fetch_html", boom)
    fetch_link_metadata.enqueue(link.pk)
    link.refresh_from_db()
    assert link.og_fetched_at is None
    assert "metadata fetch failed" in caplog.text


class _FakeResponse:
    """Stand-in for an httpx.Response, controlled entirely by the test."""

    def __init__(self, *, is_redirect=False, location="", content_type="text/html", chunks=None):
        self.is_redirect = is_redirect
        self.headers = {"content-type": content_type}
        if location:
            self.headers["location"] = location
        self._chunks = chunks if chunks is not None else [b""]

    def raise_for_status(self):
        pass

    def iter_bytes(self):
        yield from self._chunks


class _FakeStream:
    """Stand-in for the context manager `httpx.Client.stream(...)` returns."""

    def __init__(self, response):
        self._response = response

    def __enter__(self):
        return self._response

    def __exit__(self, exc_type, exc, tb):
        return False


@pytest.fixture(autouse=True)
def _no_real_dns(monkeypatch):
    """`_fetch_html` re-validates every hop with check_dns=True and then resolves the
    host again to pin the connection; these tests fake the network at `_open_stream`,
    but a bare hostname like "example.com" would still trigger a real DNS lookup inside
    `resolve_host`. Stub the resolver so the redirect-hop tests below never touch the
    network; tests that care about the resolved address override this."""
    monkeypatch.setattr(destinations, "resolve_host", lambda host, timeout: [FAKE_PUBLIC_ADDRESS])


def test_fetch_html_rejects_a_redirect_to_a_private_address(monkeypatch):
    monkeypatch.setattr("apps.links.tasks.time.monotonic", lambda: 0.0)
    calls = []

    def fake_open_stream(client, url, **kwargs):
        calls.append(url)
        return _FakeStream(
            _FakeResponse(is_redirect=True, location="http://169.254.169.254/latest/meta-data/")
        )

    monkeypatch.setattr("apps.links.tasks._open_stream", fake_open_stream)
    with pytest.raises(ValidationError):
        _fetch_html("https://example.com/start")
    assert len(calls) == 1


def test_fetch_html_raises_after_too_many_redirect_hops(monkeypatch):
    monkeypatch.setattr("apps.links.tasks.time.monotonic", lambda: 0.0)

    def fake_open_stream(client, url, **kwargs):
        return _FakeStream(_FakeResponse(is_redirect=True, location="https://example.com/next"))

    monkeypatch.setattr("apps.links.tasks._open_stream", fake_open_stream)
    with pytest.raises(RuntimeError, match="too many redirects"):
        _fetch_html("https://example.com/start")


def test_fetch_html_stops_reading_the_body_at_the_deadline(monkeypatch, settings):
    settings.LINK_METADATA_TOTAL_TIMEOUT = 1.0
    clock = iter([0.0, 0.0, 0.0, 2.0])
    monkeypatch.setattr("apps.links.tasks.time.monotonic", lambda: next(clock, 2.0))

    def fake_open_stream(client, url, **kwargs):
        return _FakeStream(
            _FakeResponse(chunks=[b"<title>first</title>", b"<title>should-not-appear</title>"])
        )

    monkeypatch.setattr("apps.links.tasks._open_stream", fake_open_stream)
    html, _final_url = _fetch_html("https://example.com/start")
    assert "first" in html
    assert "should-not-appear" not in html


def test_fetch_html_stops_reading_the_body_at_max_bytes(monkeypatch, settings):
    settings.LINK_METADATA_MAX_BYTES = 10
    monkeypatch.setattr("apps.links.tasks.time.monotonic", lambda: 0.0)

    def fake_open_stream(client, url, **kwargs):
        return _FakeStream(_FakeResponse(chunks=[b"0123456789", b"more-than-the-cap"]))

    monkeypatch.setattr("apps.links.tasks._open_stream", fake_open_stream)
    html, _final_url = _fetch_html("https://example.com/start")
    assert html == "0123456789"
    assert "more-than-the-cap" not in html


def test_fetch_html_short_circuits_for_a_non_html_content_type(monkeypatch):
    monkeypatch.setattr("apps.links.tasks.time.monotonic", lambda: 0.0)

    def fake_open_stream(client, url, **kwargs):
        return _FakeStream(_FakeResponse(content_type="application/pdf", chunks=[b"%PDF-1.4"]))

    monkeypatch.setattr("apps.links.tasks._open_stream", fake_open_stream)
    html, final_url = _fetch_html("https://example.com/start")
    assert html == ""
    assert final_url == "https://example.com/start"


def test_fetch_html_fetches_a_normal_host(monkeypatch):
    monkeypatch.setattr("apps.links.tasks.time.monotonic", lambda: 0.0)

    def fake_open_stream(client, url, **kwargs):
        return _FakeStream(_FakeResponse(chunks=[b"<title>ok</title>"]))

    monkeypatch.setattr("apps.links.tasks._open_stream", fake_open_stream)
    html, final_url = _fetch_html("https://example.com/start")
    assert "ok" in html
    assert final_url == "https://example.com/start"


def test_fetch_html_connects_to_the_pinned_address_with_the_original_host_header(monkeypatch):
    monkeypatch.setattr("apps.links.tasks.time.monotonic", lambda: 0.0)
    monkeypatch.setattr(destinations, "resolve_host", lambda host, timeout: [FAKE_PUBLIC_ADDRESS])
    calls = []

    def fake_open_stream(client, url, **kwargs):
        calls.append((url, kwargs))
        return _FakeStream(_FakeResponse(chunks=[b"<title>ok</title>"]))

    monkeypatch.setattr("apps.links.tasks._open_stream", fake_open_stream)
    html, _final_url = _fetch_html("https://example.com/start")
    assert "ok" in html
    assert len(calls) == 1
    url, kwargs = calls[0]
    assert url == f"https://{FAKE_PUBLIC_ADDRESS}/start"
    assert kwargs["headers"] == {"Host": "example.com"}
    assert kwargs["extensions"] == {"sni_hostname": "example.com"}


def test_extract_metadata_resolves_favicon_and_og_image_against_the_final_url(monkeypatch):
    html = (
        '<html><head><link rel="icon" href="/favicon.png">'
        '<meta property="og:image" content="/card.png"></head></html>'
    )
    monkeypatch.setattr(
        "apps.links.tasks._fetch_html", lambda url: (html, "https://cdn.example.com/final/")
    )
    data = extract_metadata("https://example.com/start")
    assert data["favicon_url"] == "https://cdn.example.com/favicon.png"
    assert data["og_image_url"] == "https://cdn.example.com/card.png"
