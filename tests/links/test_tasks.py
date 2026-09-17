import pytest

from apps.links import services
from apps.links.tasks import fetch_link_metadata

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
    monkeypatch.setattr("apps.links.tasks._fetch_html", lambda url: HTML)
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
        lambda url: "<html><head><title>Fallback title</title></head></html>",
    )
    fetch_link_metadata.enqueue(link.pk)
    link.refresh_from_db()
    assert link.title == "Fallback title"
    assert link.og_title == ""


def test_fetch_link_metadata_never_overwrites_an_override(link, monkeypatch):
    link.og_title = "Mine"
    link.og_overridden = True
    link.save()
    monkeypatch.setattr("apps.links.tasks._fetch_html", lambda url: HTML)
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
