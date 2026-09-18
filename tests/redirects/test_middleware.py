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
def test_a_url_encoded_space_and_extra_slashes_resolve_to_the_same_link(client, link):
    padded = client.get(f"/%20{link.code}", HTTP_USER_AGENT=DESKTOP_UA)
    trailing = client.get(f"/{link.code}///", HTTP_USER_AGENT=DESKTOP_UA)
    assert padded.status_code == 302
    assert padded["Location"] == "https://example.com/p"
    assert trailing.status_code == 302
    assert trailing["Location"] == "https://example.com/p"


@pytest.mark.django_db
def test_the_preview_page_renders_the_normalized_code(client, link):
    response = client.get(f"/%20{link.code.upper()}+", HTTP_USER_AGENT=DESKTOP_UA)
    assert response.status_code == 200
    body = response.content.decode()
    assert link.code in body
    assert link.code.upper() not in body


@pytest.mark.django_db
def test_single_segments_with_a_dot_fall_through_instead_of_a_branded_404(client, db):
    response = client.get("/favicon.ico")
    assert response.status_code == 404
    # Django's default 404, not the branded "this short link doesn't exist" page.
    assert b"doesn\xe2\x80\x99t exist" not in response.content


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
def test_any_other_exception_from_the_resolver_also_returns_503(client, monkeypatch, caplog):
    def boom(*args, **kwargs):
        raise RuntimeError("something unrelated to the database broke")

    monkeypatch.setattr("apps.redirects.resolver._payload_for", boom)
    response = client.get("/spring-drop", HTTP_USER_AGENT=DESKTOP_UA)
    assert response.status_code == 503
    assert response["Retry-After"] == "5"
    assert "unexpected error" in caplog.text


@pytest.mark.django_db
def test_an_exception_from_the_resolver_makes_the_preview_page_answer_503_too(client, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr("apps.redirects.resolver._payload_for", boom)
    response = client.get("/spring-drop+", HTTP_USER_AGENT=DESKTOP_UA)
    assert response.status_code == 503
    assert response["Retry-After"] == "5"


@pytest.mark.django_db
def test_an_ordinary_dashboard_page_still_carries_its_csp_header(client, db):
    """RedirectMiddleware sits right after ContentSecurityPolicyMiddleware now; a page
    that never touches the redirect path at all must keep getting its header."""
    response = client.get("/auth/login/")
    assert "'nonce-" in response["Content-Security-Policy"]


@pytest.mark.django_db
def test_redirect_does_not_set_vary_cookie(client, link):
    response = client.get(f"/{link.code}", HTTP_USER_AGENT=DESKTOP_UA)
    assert "Cookie" not in response.get("Vary", "")


@pytest.mark.django_db
def test_the_twenty_first_request_in_the_window_is_rate_limited(client, link, settings):
    settings.REDIRECT_RATE_PER_IP = 20
    settings.REDIRECT_RATE_PER_IP_WINDOW = 60
    for _ in range(20):
        response = client.get(f"/{link.code}", HTTP_USER_AGENT=DESKTOP_UA)
        assert response.status_code == 302
    blocked = client.get(f"/{link.code}", HTTP_USER_AGENT=DESKTOP_UA)
    assert blocked.status_code == 429
    assert blocked["Retry-After"] == "1"
    assert blocked["Cache-Control"] == "no-store"
    # A bare response: no template was rendered to produce it.
    assert blocked.content == b""


@pytest.mark.django_db
def test_a_normal_visitor_is_unaffected_by_the_rate_limit(client, link, settings):
    settings.REDIRECT_RATE_PER_IP = 20
    settings.REDIRECT_RATE_PER_IP_WINDOW = 60
    for _ in range(5):
        response = client.get(f"/{link.code}", HTTP_USER_AGENT=DESKTOP_UA)
        assert response.status_code == 302
