import pytest
from django.urls import reverse

from apps.accounts import services
from apps.accounts.models import User

LOGIN = reverse("accounts:login")


@pytest.fixture
def user(db):
    return User.objects.create_user(email="ada@example.com")


def verify_url(token):
    return reverse("accounts:verify", args=[token])


def test_verify_get_renders_auto_submit_page_without_consuming(client, user):
    raw = services.create_magic_link(user)
    response = client.get(verify_url(raw))
    assert response.status_code == 200
    body = response.content.decode()
    assert "Signing you in" in body
    assert 'method="post"' in body
    assert "nonce=" in body
    assert user.magic_links.get().used_at is None


def test_verify_post_logs_in_and_redirects(client, user):
    raw = services.create_magic_link(user)
    response = client.post(verify_url(raw))
    assert response.status_code == 302
    assert response.url == "/"
    assert client.session["_auth_user_id"] == str(user.pk)
    assert user.magic_links.get().used_at is not None


def test_verify_post_honours_stored_next(client, user):
    raw = services.create_magic_link(user)
    session = client.session
    session["login_next"] = "/w/acme/"
    session["magic_link_email"] = user.email
    session.save()
    response = client.post(verify_url(raw))
    assert response.url == "/w/acme/"
    assert "login_next" not in client.session
    assert "magic_link_email" not in client.session


def test_verify_post_with_used_or_bad_token_shows_expired_page(client, user):
    raw = services.create_magic_link(user)
    client.post(verify_url(raw))
    client.logout()
    again = client.post(verify_url(raw))
    assert again.status_code == 410
    assert "This link no longer works" in again.content.decode()
    assert client.post(verify_url("nope")).status_code == 410


def test_logout_requires_post_and_ends_session(client, user):
    client.force_login(user)
    assert client.get(reverse("accounts:logout")).status_code == 405
    response = client.post(reverse("accounts:logout"))
    assert response.status_code == 302 and response.url == LOGIN
    assert "_auth_user_id" not in client.session


def test_home_shows_sign_in_or_sign_out(client, user):
    assert "Sign in" in client.get("/").content.decode()
    client.force_login(user)
    body = client.get("/").content.decode()
    assert "Sign out" in body and "ada@example.com" in body
