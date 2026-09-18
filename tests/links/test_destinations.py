import socket
import time

import pytest
from django.core.exceptions import ValidationError

from apps.links import destinations

FAKE_PUBLIC_ADDRESS = "93.184.216.34"


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "data:text/html,hi",
        "file:///etc/passwd",
        "ftp://example.com/x",
        "not a url",
        "http://localhost/admin",
        "http://127.0.0.1:8000/",
        "http://10.0.0.5/",
        "http://192.168.1.1/",
        "http://169.254.169.254/latest/meta-data/",
        "http://[::1]/",
        "https://sho.rt/abc123",
    ],
)
def test_validate_destination_rejects(url, settings):
    settings.SHORT_DOMAIN = "sho.rt"
    with pytest.raises(ValidationError):
        destinations.validate_destination(url)


def test_validate_destination_accepts_and_normalises(settings):
    settings.SHORT_DOMAIN = "sho.rt"
    assert (
        destinations.validate_destination("  https://Example.com/Path?a=1  ")
        == "https://example.com/Path?a=1"
    )
    assert destinations.validate_destination("http://example.com").startswith("http://")


def test_blocked_domains_are_rejected_including_subdomains(settings):
    settings.BLOCKED_LINK_DOMAINS = ["bad.example"]
    assert destinations.is_blocked_host("bad.example") is True
    assert destinations.is_blocked_host("deep.sub.bad.example") is True
    assert destinations.is_blocked_host("notbad.example") is False
    with pytest.raises(ValidationError):
        destinations.validate_destination("https://bad.example/x")


@pytest.mark.parametrize(
    "url",
    ["https://sho.rt./abc", "http://localhost./x"],
)
def test_a_trailing_dot_does_not_bypass_the_self_reference_check(url, settings):
    settings.SHORT_DOMAIN = "sho.rt"
    with pytest.raises(ValidationError):
        destinations.validate_destination(url)


def test_a_trailing_dot_does_not_bypass_the_blocklist(settings):
    settings.BLOCKED_LINK_DOMAINS = ["bad.example"]
    assert destinations.is_blocked_host("bad.example.") is True
    with pytest.raises(ValidationError):
        destinations.validate_destination("https://bad.example./x")


def test_is_blocked_host_matches_across_unicode_and_punycode(settings):
    settings.BLOCKED_LINK_DOMAINS = ["café.example"]
    assert destinations.is_blocked_host("xn--caf-dma.example") is True
    settings.BLOCKED_LINK_DOMAINS = ["xn--caf-dma.example"]
    assert destinations.is_blocked_host("café.example") is True


def test_resolve_host_raises_when_resolution_is_slower_than_its_timeout(monkeypatch):
    def slow_getaddrinfo(host, port):
        time.sleep(0.3)
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (FAKE_PUBLIC_ADDRESS, 0))]

    monkeypatch.setattr(destinations.socket, "getaddrinfo", slow_getaddrinfo)
    start = time.monotonic()
    with pytest.raises(ValidationError):
        destinations.resolve_host("example.com", 0.05)
    assert time.monotonic() - start < 0.3


def test_resolve_host_rejects_a_private_address(monkeypatch):
    monkeypatch.setattr(
        destinations.socket,
        "getaddrinfo",
        lambda host, port: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 0))],
    )
    with pytest.raises(ValidationError):
        destinations.resolve_host("example.com", 1.0)


def test_resolve_host_returns_the_resolved_addresses(monkeypatch):
    monkeypatch.setattr(
        destinations.socket,
        "getaddrinfo",
        lambda host, port: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (FAKE_PUBLIC_ADDRESS, 0))],
    )
    assert destinations.resolve_host("example.com", 1.0) == [FAKE_PUBLIC_ADDRESS]


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "data:text/html,hi",
        "vbscript:msgbox(1)",
        "blob:https://example.com/x",
        "file:///etc/passwd",
        "about:blank",
        "JAVASCRIPT:alert(1)",
    ],
)
def test_validate_app_url_rejects_denied_schemes(url):
    with pytest.raises(ValidationError):
        destinations.validate_app_url(url)


def test_validate_app_url_accepts_a_custom_scheme():
    value = "instagram://user?username=acme"
    assert destinations.validate_app_url(value) == value


def test_validate_app_url_validates_an_http_target_like_a_destination(settings):
    settings.SHORT_DOMAIN = "sho.rt"
    assert destinations.validate_app_url("https://Example.com/x") == "https://example.com/x"
    with pytest.raises(ValidationError):
        destinations.validate_app_url("http://127.0.0.1/x")


def test_validate_app_url_rejects_a_scheme_smuggled_via_control_characters():
    with pytest.raises(ValidationError):
        destinations.validate_app_url("java\nscript:alert(1)")
    with pytest.raises(ValidationError):
        destinations.validate_app_url("java\tscript:alert(1)")
