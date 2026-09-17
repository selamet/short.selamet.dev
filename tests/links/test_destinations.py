import pytest
from django.core.exceptions import ValidationError

from apps.links import destinations


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
