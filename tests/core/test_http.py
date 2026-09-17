from django.test import RequestFactory

from apps.core.http import client_ip


def test_client_ip_ignores_client_supplied_forwarded_entries():
    request = RequestFactory().get(
        "/", HTTP_X_FORWARDED_FOR="1.2.3.4, 203.0.113.9", REMOTE_ADDR="10.0.0.1"
    )
    assert client_ip(request) == "203.0.113.9"


def test_client_ip_with_zero_hops_uses_remote_addr(settings):
    settings.TRUSTED_PROXY_HOPS = 0
    request = RequestFactory().get(
        "/", HTTP_X_FORWARDED_FOR="1.2.3.4, 203.0.113.9", REMOTE_ADDR="10.0.0.1"
    )
    assert client_ip(request) == "10.0.0.1"


def test_client_ip_with_two_hops(settings):
    settings.TRUSTED_PROXY_HOPS = 2
    request = RequestFactory().get(
        "/", HTTP_X_FORWARDED_FOR="1.2.3.4, 203.0.113.9, 10.0.0.2", REMOTE_ADDR="10.0.0.1"
    )
    assert client_ip(request) == "203.0.113.9"


def test_client_ip_falls_back_to_remote_addr():
    request = RequestFactory().get("/", REMOTE_ADDR="10.0.0.1")
    assert client_ip(request) == "10.0.0.1"
