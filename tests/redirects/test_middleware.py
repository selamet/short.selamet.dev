import pytest

from tests.redirects.conftest import DESKTOP_UA


@pytest.mark.django_db
def test_redirect_returns_302_with_no_store(client, link):
    response = client.get(f"/{link.code}", HTTP_USER_AGENT=DESKTOP_UA)
    assert response.status_code == 302
    assert response["Location"] == "https://example.com/p"
    assert "no-store" in response["Cache-Control"]


@pytest.mark.django_db
def test_redirect_does_not_touch_the_session(client, link):
    response = client.get(f"/{link.code}", HTTP_USER_AGENT=DESKTOP_UA)
    assert response.status_code == 302
    assert "Set-Cookie" not in response


@pytest.mark.django_db
def test_known_prefixes_are_left_alone(client, db):
    assert client.get("/health/").status_code == 200
    assert client.get("/auth/login/").status_code == 200
    assert client.get("/w/").status_code in (302, 200)


@pytest.mark.django_db
def test_unknown_code_renders_the_not_found_page(client):
    response = client.get("/nope-nope", HTTP_USER_AGENT=DESKTOP_UA)
    assert response.status_code == 404
    body = response.content.decode()
    assert "doesn’t exist" in body or "does not exist" in body


@pytest.mark.django_db
def test_paths_with_more_than_one_segment_are_not_claimed(client):
    assert client.get("/nope/nope").status_code == 404


@pytest.mark.django_db
def test_a_database_outage_returns_503(client, monkeypatch):
    from django.db import OperationalError

    def boom(*args, **kwargs):
        raise OperationalError("db down")

    monkeypatch.setattr("apps.redirects.resolver._payload_for", boom)
    response = client.get("/spring-drop", HTTP_USER_AGENT=DESKTOP_UA)
    assert response.status_code == 503
    assert response["Retry-After"] == "5"


@pytest.mark.django_db
def test_an_ordinary_dashboard_page_still_carries_its_csp_header(client, db):
    """RedirectMiddleware sits right after ContentSecurityPolicyMiddleware now; a page
    that never touches the redirect path at all must keep getting its header."""
    response = client.get("/auth/login/")
    assert "'nonce-" in response["Content-Security-Policy"]
