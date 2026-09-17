import pytest
from django.core import mail
from django.urls import reverse

from apps.accounts.models import MagicLink, User

LOGIN = reverse("accounts:login")
INBOX = reverse("accounts:check_inbox")
RESEND = reverse("accounts:resend")


@pytest.mark.django_db
def test_login_page_renders_form(client):
    response = client.get(LOGIN)
    assert response.status_code == 200
    assert 'name="email"' in response.content.decode()
    assert "Sign in to short" in response.content.decode()


@pytest.mark.django_db
def test_login_post_creates_user_sends_link_and_redirects_to_inbox(client):
    response = client.post(LOGIN, {"email": "Ada@Example.com"})
    assert response.status_code == 302
    assert response.url == INBOX
    user = User.objects.get()
    assert user.email == "Ada@example.com"
    assert MagicLink.objects.filter(user=user).count() == 1
    assert len(mail.outbox) == 1
    inbox = client.get(INBOX)
    assert inbox.status_code == 200
    assert "Ada@example.com" in inbox.content.decode()
    assert "Resend" in inbox.content.decode()


@pytest.mark.django_db
def test_login_post_for_existing_user_looks_identical(client):
    User.objects.create_user(email="ada@example.com")
    response = client.post(LOGIN, {"email": "ada@example.com"})
    assert response.status_code == 302 and response.url == INBOX
    assert User.objects.count() == 1
    assert len(mail.outbox) == 1


@pytest.mark.django_db
def test_login_rejects_invalid_email(client):
    response = client.post(LOGIN, {"email": "not-an-email"})
    assert response.status_code == 200
    assert "Enter a valid email address." in response.content.decode()
    assert len(mail.outbox) == 0


@pytest.mark.django_db
def test_login_rate_limits_per_email(client):
    for _ in range(3):
        assert client.post(LOGIN, {"email": "ada@example.com"}).status_code == 302
    blocked = client.post(LOGIN, {"email": "ada@example.com"})
    assert blocked.status_code == 200
    assert "Too many sign-in links" in blocked.content.decode()
    assert len(mail.outbox) == 3


@pytest.mark.django_db
def test_login_rate_limits_per_ip(client):
    for i in range(20):
        assert client.post(LOGIN, {"email": f"u{i}@example.com"}).status_code == 302
    blocked = client.post(LOGIN, {"email": "u99@example.com"})
    assert blocked.status_code == 200
    assert "Too many sign-in links" in blocked.content.decode()
    assert len(mail.outbox) == 20


@pytest.mark.django_db
def test_login_ip_limit_ignores_spoofed_forwarded_for(client):
    # Only the entry TRUSTED_PROXY_HOPS positions from the end is trusted; the attacker
    # can vary everything before it without getting a fresh rate-limit identity.
    for i in range(20):
        response = client.post(
            LOGIN,
            {"email": f"spoof{i}@example.com"},
            HTTP_X_FORWARDED_FOR=f"9.9.9.{i}, 203.0.113.9",
        )
        assert response.status_code == 302
    blocked = client.post(
        LOGIN,
        {"email": "spoof99@example.com"},
        HTTP_X_FORWARDED_FOR="9.9.9.99, 203.0.113.9",
    )
    assert blocked.status_code == 200
    assert "Too many sign-in links" in blocked.content.decode()


@pytest.mark.django_db
def test_login_stores_safe_next_only(client):
    client.post(LOGIN + "?next=/w/acme/", {"email": "ada@example.com"})
    assert client.session["login_next"] == "/w/acme/"
    client.post(LOGIN + "?next=https://evil.example/", {"email": "bob@example.com"})
    assert "login_next" not in client.session


@pytest.mark.django_db
def test_authenticated_user_is_redirected_away_from_login(client):
    user = User.objects.create_user(email="ada@example.com")
    client.force_login(user)
    assert client.get(LOGIN).status_code == 302


@pytest.mark.django_db
def test_check_inbox_without_pending_email_redirects_to_login(client):
    response = client.get(INBOX)
    assert response.status_code == 302 and response.url == LOGIN


@pytest.mark.django_db
def test_resend_respects_cooldown_then_sends_again(client, settings):
    client.post(LOGIN, {"email": "ada@example.com"})
    assert len(mail.outbox) == 1
    during = client.post(RESEND, HTTP_HX_REQUEST="true")
    assert during.status_code == 200
    assert "disabled" in during.content.decode()
    assert len(mail.outbox) == 1
    settings.MAGIC_LINK_RESEND_COOLDOWN_SECONDS = 0
    from django.core.cache import cache

    cache.delete("magic-link-cooldown:ada@example.com")
    after = client.post(RESEND, HTTP_HX_REQUEST="true")
    assert after.status_code == 200
    assert len(mail.outbox) == 2


@pytest.mark.django_db
def test_resend_without_htmx_redirects_to_inbox(client):
    client.post(LOGIN, {"email": "ada@example.com"})
    response = client.post(RESEND)
    assert response.status_code == 302 and response.url == INBOX


@pytest.mark.django_db
def test_resend_reports_rate_limit_instead_of_failing_silently(client, settings):
    settings.MAGIC_LINK_RESEND_COOLDOWN_SECONDS = 0
    client.post(LOGIN, {"email": "ada@example.com"})
    client.post(RESEND, HTTP_HX_REQUEST="true")
    client.post(RESEND, HTTP_HX_REQUEST="true")
    assert len(mail.outbox) == 3
    blocked = client.post(RESEND, HTTP_HX_REQUEST="true")
    assert blocked.status_code == 200
    assert "Too many sign-in links" in blocked.content.decode()
    assert "disabled" in blocked.content.decode()
    assert len(mail.outbox) == 3
