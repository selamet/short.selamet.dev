from django.test import RequestFactory

from apps.core.http import client_ip


def test_client_ip_prefers_first_forwarded_for_entry():
    request = RequestFactory().get(
        "/", HTTP_X_FORWARDED_FOR="203.0.113.9, 10.0.0.2", REMOTE_ADDR="10.0.0.1"
    )
    assert client_ip(request) == "203.0.113.9"


def test_client_ip_falls_back_to_remote_addr():
    request = RequestFactory().get("/", REMOTE_ADDR="10.0.0.1")
    assert client_ip(request) == "10.0.0.1"
