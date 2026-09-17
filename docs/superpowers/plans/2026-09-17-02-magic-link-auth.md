# Accounts: Magic Link Authentication — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Passwordless sign-in for **short**: a user enters an email, receives a single-use link that expires in 15 minutes, opens it, and gets a session. Includes sign-out, resend with cooldown, rate limits and the transactional email.

**Architecture:** `accounts.MagicLink` stores only a SHA-256 hash of the token. `accounts/services.py` owns token creation and consumption; `accounts/tasks.py` generates the token and sends the email inside a Django task so the raw token never sits in the task queue; views are thin. Rate limits and IP hashing are small helpers in `apps/core` that later apps (redirects, links) reuse. The verify page consumes the token on POST (auto-submitted by a nonce'd inline script) so email link scanners that only GET cannot burn it.

**Tech Stack:** Django 6.1 (`django.tasks`, `MAILERS`), Django forms, HTMX for resend, pytest-django with `mail.outbox`, LocMemCache.

**Spec:** `docs/superpowers/specs/2026-09-17-short-design.md` (sections 3 `accounts`, 6 "Magic link flow", 8 rate limits/privacy). Design reference: `docs/design/README.md` (auth and email screens), `docs/design/screens/auth.html`, `docs/design/screens/email.html`.

## Global Constraints

- Everything in the repo is English. Commit messages `GH-<issue>-<type>: description` on branch `GH-<issue>` (the issue number is given in the dispatch). No AI attribution anywhere.
- No hostnames, IPs or secrets in the repository; new env vars go into `.env.example` (a test enforces this).
- Tokens: 32 random bytes via `secrets.token_urlsafe(32)`, stored only as SHA-256 hex; valid 15 minutes; single use. The raw token never touches the database or the task queue.
- Rate limits (through Django's cache API only): 3 links per email per 10 minutes, 20 per IP per hour; resend cooldown 45 seconds.
- Never reveal whether an email has an account: the same "check your inbox" page for everyone.
- IPs are stored only as a salted hash (daily salt kept in the cache).
- `client_ip` resolves the address from `TRUSTED_PROXY_HOPS` (env, default 1): the trustworthy `X-Forwarded-For` entry is the one `hops` positions from the end, since anything before it is client-supplied and must be ignored to keep rate limits from being spoofed.
- Templates extend `templates/base.html`; inline `<script>` tags carry `nonce="{{ csp_nonce }}"`; no native `alert/confirm`.
- Email: table-based HTML, inline styles, 560px, no images, plus a plain-text alternative carrying the same URL.
- Tests: `uv run pytest`, 0 warnings; ruff and pre-commit clean; `makemigrations --check` clean.

---

## File structure

```
apps/core/http.py                 # client_ip(request)
apps/core/privacy.py              # daily_salt(), hash_ip(ip)
apps/core/ratelimit.py            # hit(scope, identity, limit, window) -> bool
apps/accounts/models.py           # + MagicLink
apps/accounts/migrations/0002_magiclink.py
apps/accounts/services.py         # get_or_create_user, create_magic_link, consume_magic_link, magic_link_url, InvalidMagicLink
apps/accounts/tasks.py            # send_magic_link task
apps/accounts/forms.py            # LoginForm
apps/accounts/views.py            # login, check_inbox, resend, verify, logout
apps/accounts/urls.py             # app_name "accounts"
apps/accounts/admin.py            # + MagicLinkAdmin (read-only)
config/settings/base.py           # MAGIC_LINK_*, SITE_URL
config/settings/prod.py           # SITE_URL default https
config/settings/test.py           # SITE_URL
config/urls.py                    # include auth urls
.env.example                      # SITE_URL
templates/accounts/_auth_base.html
templates/accounts/login.html
templates/accounts/check_inbox.html
templates/accounts/partials/resend.html
templates/accounts/verify.html
templates/accounts/link_expired.html
templates/accounts/email/magic_link.html
templates/accounts/email/magic_link.txt
templates/core/home.html          # sign-in / sign-out links
tests/core/test_http.py
tests/core/test_privacy.py
tests/core/test_ratelimit.py
tests/accounts/test_services.py
tests/accounts/test_tasks.py
tests/accounts/test_views_login.py
tests/accounts/test_views_verify.py
```

---

### Task 1: Core helpers, MagicLink model and services

**Files:**
- Create: `apps/core/http.py`, `apps/core/privacy.py`, `apps/core/ratelimit.py`, `apps/accounts/services.py`, `apps/accounts/migrations/0002_magiclink.py` (generated), `tests/core/test_http.py`, `tests/core/test_privacy.py`, `tests/core/test_ratelimit.py`, `tests/accounts/test_services.py`
- Modify: `apps/accounts/models.py`, `apps/accounts/admin.py`, `config/settings/base.py`, `config/settings/prod.py`, `config/settings/test.py`, `.env.example`

**Interfaces:**
- Produces: `client_ip(request) -> str`; `hash_ip(ip: str) -> str` (64 hex chars, "" for empty); `ratelimit.hit(scope, identity, limit, window_seconds) -> bool`; `MagicLink` model with `is_valid()`; `services.get_or_create_user(email) -> User`; `services.create_magic_link(user, ip_hash="") -> raw_token: str`; `services.consume_magic_link(raw_token) -> User` raising `services.InvalidMagicLink`; `services.magic_link_url(raw_token) -> str`; settings `MAGIC_LINK_TTL_MINUTES = 15`, `MAGIC_LINK_RESEND_COOLDOWN_SECONDS = 45`, `SITE_URL`.

- [ ] **Step 1: Write the failing tests**

`tests/core/test_http.py`:
```python
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
```

`tests/core/test_privacy.py`:
```python
from datetime import date

from apps.core.privacy import daily_salt, hash_ip


def test_hash_ip_is_stable_within_a_day_and_never_the_raw_ip():
    first = hash_ip("203.0.113.9")
    assert first == hash_ip("203.0.113.9")
    assert len(first) == 64
    assert "203.0.113.9" not in first


def test_hash_ip_of_empty_is_empty():
    assert hash_ip("") == ""


def test_daily_salt_differs_per_day():
    assert daily_salt(date(2026, 1, 1)) != daily_salt(date(2026, 1, 2))
```

`tests/core/test_ratelimit.py`:
```python
from apps.core import ratelimit


def test_hit_allows_up_to_limit_then_blocks():
    assert ratelimit.hit("t", "a", limit=2, window=60) is True
    assert ratelimit.hit("t", "a", limit=2, window=60) is True
    assert ratelimit.hit("t", "a", limit=2, window=60) is False


def test_hit_isolates_identities_and_scopes():
    assert ratelimit.hit("t", "a", limit=1, window=60) is True
    assert ratelimit.hit("t", "b", limit=1, window=60) is True
    assert ratelimit.hit("other", "a", limit=1, window=60) is True
```

`tests/accounts/test_services.py`:
```python
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.accounts import services
from apps.accounts.models import MagicLink, User


@pytest.fixture
def user(db):
    return User.objects.create_user(email="ada@example.com")


def test_get_or_create_user_is_case_insensitive(db):
    created = services.get_or_create_user("Ada@Example.com")
    again = services.get_or_create_user("ADA@example.com")
    assert created.pk == again.pk
    assert User.objects.count() == 1


def test_create_magic_link_stores_only_a_hash(user):
    raw = services.create_magic_link(user, ip_hash="abc")
    link = MagicLink.objects.get()
    assert len(raw) >= 43
    assert raw not in link.token_hash
    assert link.token_hash == services.hash_token(raw)
    assert link.ip_hash == "abc"
    assert link.used_at is None
    assert timedelta(minutes=14) < link.expires_at - timezone.now() <= timedelta(minutes=15)


def test_consume_magic_link_returns_user_once(user):
    raw = services.create_magic_link(user)
    assert services.consume_magic_link(raw) == user
    with pytest.raises(services.InvalidMagicLink):
        services.consume_magic_link(raw)


def test_consume_rejects_expired_unknown_and_inactive(user):
    raw = services.create_magic_link(user)
    MagicLink.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
    with pytest.raises(services.InvalidMagicLink):
        services.consume_magic_link(raw)
    with pytest.raises(services.InvalidMagicLink):
        services.consume_magic_link("not-a-token")
    fresh = services.create_magic_link(user)
    user.is_active = False
    user.save()
    with pytest.raises(services.InvalidMagicLink):
        services.consume_magic_link(fresh)


def test_magic_link_url_uses_site_url(settings):
    settings.SITE_URL = "https://sho.rt"
    assert services.magic_link_url("tok") == "https://sho.rt/auth/verify/tok/"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/core/test_http.py tests/core/test_privacy.py tests/core/test_ratelimit.py tests/accounts/test_services.py -v`
Expected: import errors (`ModuleNotFoundError`) for the new modules.

- [ ] **Step 3: Write the core helpers**

`apps/core/http.py`:
```python
from django.conf import settings


def client_ip(request):
    """Client address behind TRUSTED_PROXY_HOPS reverse proxies.

    Proxies append the peer address to X-Forwarded-For, so the trustworthy entry is the
    one `hops` positions from the end; anything before it is client-supplied and ignored.
    """
    hops = settings.TRUSTED_PROXY_HOPS
    parts = [
        p.strip() for p in request.META.get("HTTP_X_FORWARDED_FOR", "").split(",") if p.strip()
    ]
    if hops and len(parts) >= hops:
        return parts[-hops]
    return request.META.get("REMOTE_ADDR", "")
```

`apps/core/privacy.py`:
```python
"""Privacy helpers: IPs are only ever stored as a hash salted with a per-day secret."""

import hashlib
import secrets

from django.core.cache import cache
from django.utils import timezone

SALT_TTL_SECONDS = 60 * 60 * 48


def daily_salt(day=None):
    day = day or timezone.now().date()
    return cache.get_or_set(f"ipsalt:{day.isoformat()}", lambda: secrets.token_hex(16), timeout=SALT_TTL_SECONDS)


def hash_ip(ip):
    if not ip:
        return ""
    return hashlib.sha256(f"{daily_salt()}:{ip}".encode()).hexdigest()
```

`apps/core/ratelimit.py`:
```python
"""Fixed-window rate limiting on top of Django's cache API."""

from django.core.cache import cache


def hit(scope, identity, limit, window):
    """Record one event for (scope, identity). Return True while the window's count is within limit."""
    key = f"rl:{scope}:{identity}"
    cache.add(key, 0, timeout=window)
    try:
        count = cache.incr(key)
    except ValueError:
        # The key expired between add and incr; start a new window.
        cache.add(key, 0, timeout=window)
        count = cache.incr(key)
    return count <= limit
```

- [ ] **Step 4: Add settings and the env example entry**

`config/settings/base.py`, after `SITE_NAME = "short"`:
```python
# Absolute origin used in emails and other links generated outside a request.
SITE_URL = env("SITE_URL", default=f"http://{SHORT_DOMAIN}")
MAGIC_LINK_TTL_MINUTES = 15
MAGIC_LINK_RESEND_COOLDOWN_SECONDS = 45
```

`config/settings/prod.py`, after `DEBUG = False`:
```python
SITE_URL = env("SITE_URL", default=f"https://{SHORT_DOMAIN}")
```

`config/settings/test.py`, after `SHORT_DOMAIN = "sho.rt"`:
```python
SITE_URL = "https://sho.rt"
```

`.env.example`, right under `SHORT_DOMAIN=localhost:8000`:
```dotenv
# Absolute origin for links in emails. Defaults to http://SHORT_DOMAIN (https:// in production).
# SITE_URL=https://sho.rt
```

- [ ] **Step 5: Add the MagicLink model, admin and migration**

Append to `apps/accounts/models.py`:
```python
class MagicLink(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="magic_links")
    token_hash = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    ip_hash = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["user", "created_at"])]

    def __str__(self):
        return f"magic link for {self.user_id}"

    def is_valid(self):
        return self.used_at is None and self.expires_at > timezone.now()
```

Append to `apps/accounts/admin.py`:
```python
from .models import MagicLink


@admin.register(MagicLink)
class MagicLinkAdmin(admin.ModelAdmin):
    list_display = ("user", "created_at", "expires_at", "used_at")
    list_select_related = ("user",)
    readonly_fields = ("user", "token_hash", "expires_at", "used_at", "ip_hash", "created_at")
    search_fields = ("user__email",)

    def has_add_permission(self, request):
        return False
```
(Merge the import with the existing `from .models import User` line: `from .models import MagicLink, User`.)

Generate the migration: `uv run python manage.py makemigrations accounts -n magiclink`.

- [ ] **Step 6: Write the services**

`apps/accounts/services.py`:
```python
"""Magic link lifecycle. Only hashes are stored; raw tokens live in the email and the URL."""

import hashlib
import secrets
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from .models import MagicLink, User


class InvalidMagicLink(Exception):
    """The token is unknown, expired, already used, or belongs to an inactive user."""


def hash_token(raw_token):
    return hashlib.sha256(raw_token.encode()).hexdigest()


def get_or_create_user(email):
    email = User.objects.normalize_email(email)
    user = User.objects.filter(email__iexact=email).first()
    return user or User.objects.create_user(email=email)


def create_magic_link(user, ip_hash=""):
    raw_token = secrets.token_urlsafe(32)
    MagicLink.objects.create(
        user=user,
        token_hash=hash_token(raw_token),
        ip_hash=ip_hash,
        expires_at=timezone.now() + timedelta(minutes=settings.MAGIC_LINK_TTL_MINUTES),
    )
    return raw_token


def consume_magic_link(raw_token):
    with transaction.atomic():
        try:
            link = (
                MagicLink.objects.select_for_update()
                .select_related("user")
                .get(token_hash=hash_token(raw_token))
            )
        except MagicLink.DoesNotExist:
            raise InvalidMagicLink from None
        if not link.is_valid() or not link.user.is_active:
            raise InvalidMagicLink
        link.used_at = timezone.now()
        link.save(update_fields=["used_at"])
        return link.user


def magic_link_url(raw_token):
    return f"{settings.SITE_URL}{reverse('accounts:verify', args=[raw_token])}"
```

The `accounts:verify` route arrives in Task 3. To keep this task green, add `apps/accounts/urls.py` now with only that route pointing at a placeholder, and include it in `config/urls.py`:

`apps/accounts/urls.py`:
```python
from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("verify/<str:token>/", views.verify, name="verify"),
]
```

`apps/accounts/views.py` (placeholder, replaced in Task 3):
```python
from django.http import HttpResponseNotFound


def verify(request, token):
    return HttpResponseNotFound()
```

`config/urls.py`: add `path("auth/", include("apps.accounts.urls")),` before the core include.

- [ ] **Step 7: Run the tests and the migration check**

Run: `uv run pytest tests/core tests/accounts -v && uv run python manage.py makemigrations --check --dry-run && uv run ruff check . && uv run ruff format --check .`
Expected: all PASS, "No changes detected", ruff clean.

- [ ] **Step 8: Commit**

```bash
git add apps/core apps/accounts config .env.example tests/core tests/accounts
git commit -m "GH-<issue>-feat: add magic link model, services and core privacy helpers"
```

---

### Task 2: send_magic_link task and email templates

**Files:**
- Create: `apps/accounts/tasks.py`, `templates/accounts/email/magic_link.html`, `templates/accounts/email/magic_link.txt`, `tests/accounts/test_tasks.py`

**Interfaces:**
- Consumes: `services.create_magic_link`, `services.magic_link_url`, settings `SITE_NAME`, `SHORT_DOMAIN`, `MAGIC_LINK_TTL_MINUTES`, `DEFAULT_FROM_EMAIL`.
- Produces: `send_magic_link` task; call as `send_magic_link.enqueue(user.pk, ip_hash=...)`. The task generates the token, so callers never see it.

- [ ] **Step 1: Write the failing test**

`tests/accounts/test_tasks.py`:
```python
import re

import pytest
from django.core import mail

from apps.accounts import services
from apps.accounts.models import MagicLink, User
from apps.accounts.tasks import send_magic_link


@pytest.mark.django_db
def test_send_magic_link_creates_link_and_emails_both_parts():
    user = User.objects.create_user(email="ada@example.com")

    send_magic_link.enqueue(user.pk, ip_hash="h")

    link = MagicLink.objects.get(user=user)
    assert link.ip_hash == "h"
    assert len(mail.outbox) == 1
    message = mail.outbox[0]
    assert message.to == ["ada@example.com"]
    assert message.subject == "Your sign-in link to short"
    urls = re.findall(r"https://sho\.rt/auth/verify/[A-Za-z0-9_-]+/", message.body)
    assert len(urls) == 1
    raw = urls[0].rsplit("/", 2)[1]
    assert link.token_hash == services.hash_token(raw)
    html, mimetype = message.alternatives[0]
    assert mimetype == "text/html"
    assert urls[0] in html
    assert "<img" not in html
    assert "15 minutes" in message.body and "15 minutes" in html
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/accounts/test_tasks.py -v`
Expected: FAIL with `ModuleNotFoundError: apps.accounts.tasks`.

- [ ] **Step 3: Write the task**

`apps/accounts/tasks.py`:
```python
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.tasks import task
from django.template.loader import render_to_string

from . import services
from .models import User


@task
def send_magic_link(user_id, ip_hash=""):
    """Create a fresh magic link for the user and email it. The raw token exists only here."""
    user = User.objects.get(pk=user_id)
    raw_token = services.create_magic_link(user, ip_hash=ip_hash)
    context = {
        "url": services.magic_link_url(raw_token),
        "site_name": settings.SITE_NAME,
        "short_domain": settings.SHORT_DOMAIN,
        "ttl_minutes": settings.MAGIC_LINK_TTL_MINUTES,
    }
    message = EmailMultiAlternatives(
        subject=f"Your sign-in link to {settings.SITE_NAME}",
        body=render_to_string("accounts/email/magic_link.txt", context),
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[user.email],
    )
    message.attach_alternative(render_to_string("accounts/email/magic_link.html", context), "text/html")
    message.send()
```

- [ ] **Step 4: Write the email templates**

`templates/accounts/email/magic_link.txt`:
```
Your sign-in link to {{ site_name }}

Open this link to sign in. It works once and expires in {{ ttl_minutes }} minutes:

{{ url }}

Didn't request this? Ignore this email. Nothing happens unless the link is opened.

Sent by your self-hosted {{ site_name }} instance · {{ short_domain }}
```

`templates/accounts/email/magic_link.html` (table-based, inline styles only, no images):
```html
<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>Your sign-in link to {{ site_name }}</title></head>
<body style="margin:0;padding:24px;background:#e9e6e0;font-family:'IBM Plex Sans',Helvetica,Arial,sans-serif;color:#1b1a18;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
    <tr><td align="center">
      <table role="presentation" width="560" cellpadding="0" cellspacing="0" border="0" style="max-width:560px;width:100%;background:#ffffff;border:1px solid rgba(0,0,0,0.14);border-radius:8px;">
        <tr><td style="padding:28px 32px 8px 32px;font-size:20px;font-weight:600;"><span style="color:#d8552a;">&raquo;</span> {{ site_name }}</td></tr>
        <tr><td style="padding:8px 32px 0 32px;font-size:20px;font-weight:600;line-height:1.2;">Your sign-in link</td></tr>
        <tr><td style="padding:12px 32px 0 32px;font-size:14px;line-height:1.5;">Tap the button below to sign in to {{ site_name }}. The link works once and expires in {{ ttl_minutes }} minutes.</td></tr>
        <tr><td style="padding:24px 32px 0 32px;">
          <a href="{{ url }}" style="display:inline-block;padding:12px 20px;background:#d8552a;color:#ffffff;text-decoration:none;font-weight:600;font-size:14px;border-radius:6px;">Sign in to {{ site_name }}</a>
        </td></tr>
        <tr><td style="padding:24px 32px 0 32px;font-size:12px;line-height:1.5;color:#77736c;">Or paste this into your browser:<br><span style="font-family:'IBM Plex Mono',Menlo,monospace;word-break:break-all;color:#1b1a18;">{{ url }}</span></td></tr>
        <tr><td style="padding:24px 32px 28px 32px;font-size:12px;line-height:1.5;color:#77736c;">Didn&rsquo;t request this? Ignore the email. Nothing happens without the link being opened.</td></tr>
      </table>
      <table role="presentation" width="560" cellpadding="0" cellspacing="0" border="0" style="max-width:560px;width:100%;">
        <tr><td style="padding:16px 8px;font-size:11px;color:#77736c;">sent by your self-hosted {{ site_name }} instance &middot; {{ short_domain }}</td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>
```

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/accounts/test_tasks.py -v && uv run pytest -q`
Expected: PASS, whole suite green with 0 warnings.

- [ ] **Step 6: Commit**

```bash
git add apps/accounts/tasks.py templates/accounts/email tests/accounts/test_tasks.py
git commit -m "GH-<issue>-feat: send magic link emails through a Django task"
```

---

### Task 3: Login, check-inbox and resend views

**Files:**
- Create: `apps/accounts/forms.py`, `templates/accounts/_auth_base.html`, `templates/accounts/login.html`, `templates/accounts/check_inbox.html`, `templates/accounts/partials/resend.html`, `tests/accounts/test_views_login.py`
- Modify: `apps/accounts/views.py` (replace placeholder, keep `verify` as a placeholder until Task 4), `apps/accounts/urls.py`

**Interfaces:**
- Consumes: `send_magic_link.enqueue(user_id, ip_hash=)`, `ratelimit.hit`, `hash_ip`, `client_ip`, `get_or_create_user`.
- Produces: routes `accounts:login` (`/auth/login/`), `accounts:check_inbox` (`/auth/check-inbox/`), `accounts:resend` (`/auth/resend/`); session keys `PENDING_EMAIL_SESSION_KEY = "magic_link_email"`, `LOGIN_NEXT_SESSION_KEY = "login_next"`.

- [ ] **Step 1: Write the failing tests**

`tests/accounts/test_views_login.py`:
```python
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
    assert len(mail.outbox) == 20


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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/accounts/test_views_login.py -v`
Expected: `NoReverseMatch` for `accounts:login`.

- [ ] **Step 3: Write the form, views and urls**

`apps/accounts/forms.py`:
```python
from django import forms


class LoginForm(forms.Form):
    email = forms.EmailField(
        max_length=254,
        widget=forms.EmailInput(
            attrs={"autocomplete": "email", "autofocus": True, "placeholder": "you@agency.co"}
        ),
    )
```

`apps/accounts/views.py` (full file; `verify` stays a placeholder until Task 4):
```python
import time

from django.conf import settings
from django.core.cache import cache
from django.http import HttpResponseNotFound
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_http_methods, require_POST

from apps.core import ratelimit
from apps.core.http import client_ip
from apps.core.privacy import hash_ip

from . import services
from .forms import LoginForm
from .tasks import send_magic_link

PENDING_EMAIL_SESSION_KEY = "magic_link_email"
LOGIN_NEXT_SESSION_KEY = "login_next"
RATE_LIMIT_MESSAGE = "Too many sign-in links requested. Please wait a few minutes and try again."


def _cooldown_key(email):
    return f"magic-link-cooldown:{email.lower()}"


def _start_cooldown(email):
    seconds = settings.MAGIC_LINK_RESEND_COOLDOWN_SECONDS
    if seconds:
        cache.set(_cooldown_key(email), time.time() + seconds, timeout=seconds)


def _cooldown_remaining(email):
    expires = cache.get(_cooldown_key(email))
    return max(0, int(expires - time.time())) if expires else 0


def _request_magic_link(request, email):
    """Enqueue a link for the email unless a rate limit is hit. Returns the user, or None."""
    ip = client_ip(request)
    allowed_for_email = ratelimit.hit("magic-link-email", email.lower(), limit=3, window=600)
    allowed_for_ip = ratelimit.hit("magic-link-ip", ip, limit=20, window=3600)
    if not (allowed_for_email and allowed_for_ip):
        return None
    user = services.get_or_create_user(email)
    send_magic_link.enqueue(user.pk, ip_hash=hash_ip(ip))
    _start_cooldown(user.email)
    return user


def _safe_next(request, candidate):
    if candidate and url_has_allowed_host_and_scheme(
        candidate, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return candidate
    return ""


@require_http_methods(["GET", "POST"])
def login(request):
    if request.user.is_authenticated:
        return redirect(settings.LOGIN_REDIRECT_URL)
    next_url = _safe_next(request, request.GET.get("next") or request.POST.get("next"))
    form = LoginForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = _request_magic_link(request, form.cleaned_data["email"])
        if user is not None:
            # Store the normalized address so later pages and the cooldown key agree.
            request.session[PENDING_EMAIL_SESSION_KEY] = user.email
            if next_url:
                request.session[LOGIN_NEXT_SESSION_KEY] = next_url
            else:
                request.session.pop(LOGIN_NEXT_SESSION_KEY, None)
            return redirect("accounts:check_inbox")
        form.add_error(None, RATE_LIMIT_MESSAGE)
    return render(request, "accounts/login.html", {"form": form, "next": next_url})


def check_inbox(request):
    email = request.session.get(PENDING_EMAIL_SESSION_KEY)
    if not email:
        return redirect("accounts:login")
    return render(
        request, "accounts/check_inbox.html", {"email": email, "cooldown": _cooldown_remaining(email)}
    )


@require_POST
def resend(request):
    email = request.session.get(PENDING_EMAIL_SESSION_KEY)
    if not email:
        return redirect("accounts:login")
    if _cooldown_remaining(email) == 0:
        _request_magic_link(request, email)
    context = {"email": email, "cooldown": _cooldown_remaining(email)}
    if request.headers.get("HX-Request"):
        return render(request, "accounts/partials/resend.html", context)
    return redirect("accounts:check_inbox")


def verify(request, token):
    return HttpResponseNotFound()
```

`apps/accounts/urls.py`:
```python
from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("login/", views.login, name="login"),
    path("check-inbox/", views.check_inbox, name="check_inbox"),
    path("resend/", views.resend, name="resend"),
    path("verify/<str:token>/", views.verify, name="verify"),
]
```

- [ ] **Step 4: Write the templates**

`templates/accounts/_auth_base.html`:
```html
{% extends "base.html" %}
{% block body %}
<main class="mx-auto flex min-h-screen w-full max-w-md flex-col justify-center px-4 py-12">
  <p class="mono text-accent text-[13px]" aria-hidden="true">»</p>
  <section class="mt-4 rounded-lg border border-line bg-surface p-6 shadow-e1">
    {% block content %}{% endblock %}
  </section>
</main>
{% endblock %}
```

`templates/accounts/login.html`:
```html
{% extends "accounts/_auth_base.html" %}
{% block title %}Sign in · {{ SITE_NAME }}{% endblock %}
{% block content %}
<h1 class="text-[20px] font-semibold leading-tight">Sign in to {{ SITE_NAME }}</h1>
<p class="mt-2 text-ink-muted">No password. We email you a link that signs you in.</p>
<form method="post" action="{% url 'accounts:login' %}" class="mt-6 flex flex-col gap-4" novalidate>
  {% csrf_token %}
  {% if next %}<input type="hidden" name="next" value="{{ next }}">{% endif %}
  {% if form.non_field_errors %}
  <div class="rounded-md border border-danger px-3 py-2 text-danger" role="alert">{{ form.non_field_errors.0 }}</div>
  {% endif %}
  <label class="flex flex-col gap-1">
    <span class="text-[11.5px] font-medium uppercase tracking-wide text-ink-muted">Email</span>
    <input type="email" name="email" value="{{ form.email.value|default:'' }}" autocomplete="email" autofocus placeholder="you@agency.co" required
           class="rounded-sm border border-line bg-surface-2 px-3 py-2 text-[13px] focus:border-accent focus:outline-none"
           {% if form.email.errors %}aria-invalid="true" aria-describedby="email-error"{% endif %}>
    {% if form.email.errors %}<span id="email-error" class="text-danger">{{ form.email.errors.0 }}</span>{% endif %}
  </label>
  <button type="submit" class="rounded-md bg-accent px-4 py-2 font-semibold text-white hover:bg-accent-hover">Email me a link</button>
</form>
<p class="mt-6 text-[11.5px] text-ink-muted">By continuing you agree to the terms. Self-hosted instances set their own.</p>
{% endblock %}
```

`templates/accounts/partials/resend.html`:
```html
<div id="resend" class="mt-6 flex flex-wrap items-center gap-3">
  <form method="post" action="{% url 'accounts:resend' %}" hx-post="{% url 'accounts:resend' %}" hx-target="#resend" hx-swap="outerHTML">
    {% csrf_token %}
    <button type="submit" class="rounded-md border border-line px-3 py-2 font-medium hover:bg-surface-2 disabled:opacity-50" {% if cooldown %}disabled{% endif %}>Resend</button>
  </form>
  <a href="{% url 'accounts:login' %}" class="text-ink-muted underline">Change email</a>
  {% if cooldown %}<span class="w-full text-[11.5px] text-ink-muted">Resend is disabled for {{ cooldown }}s after each send.</span>{% endif %}
</div>
```

`templates/accounts/check_inbox.html`:
```html
{% extends "accounts/_auth_base.html" %}
{% block title %}Check your inbox · {{ SITE_NAME }}{% endblock %}
{% block content %}
<p class="mono text-accent" aria-hidden="true">» ✉</p>
<h1 class="mt-2 text-[20px] font-semibold leading-tight">Check your inbox</h1>
<p class="mt-2 text-ink-muted">We sent a sign-in link to <span class="mono text-ink">{{ email }}</span>. It expires in 15 minutes.</p>
{% include "accounts/partials/resend.html" %}
{% endblock %}
```

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/accounts/test_views_login.py -v && uv run pytest -q && uv run ruff check . && uv run ruff format --check .`
Expected: PASS, suite green, 0 warnings.

- [ ] **Step 6: Commit**

```bash
git add apps/accounts templates/accounts tests/accounts/test_views_login.py
git commit -m "GH-<issue>-feat: add magic link login, inbox and resend views"
```

---

### Task 4: Verify, logout and home page links

**Files:**
- Create: `templates/accounts/verify.html`, `templates/accounts/link_expired.html`, `tests/accounts/test_views_verify.py`
- Modify: `apps/accounts/views.py` (replace `verify` placeholder, add `logout`), `apps/accounts/urls.py`, `templates/core/home.html`

**Interfaces:**
- Consumes: `services.consume_magic_link`, session keys from Task 3.
- Produces: `accounts:verify` GET renders the auto-submitting page; POST consumes the token, logs in, redirects to `login_next` or `LOGIN_REDIRECT_URL`; `accounts:logout` (`/auth/logout/`, POST only).

- [ ] **Step 1: Write the failing tests**

`tests/accounts/test_views_verify.py`:
```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/accounts/test_views_verify.py -v`
Expected: failures (404 from the placeholder, `NoReverseMatch` for logout).

- [ ] **Step 3: Replace the verify placeholder and add logout**

In `apps/accounts/views.py`, replace the placeholder `verify` with:
```python
@require_http_methods(["GET", "POST"])
def verify(request, token):
    if request.method == "GET":
        # Consuming on POST keeps email link scanners (which only GET) from burning the token.
        return render(request, "accounts/verify.html", {"token": token})
    try:
        user = services.consume_magic_link(token)
    except services.InvalidMagicLink:
        return render(request, "accounts/link_expired.html", status=410)
    auth_login(request, user)
    request.session.pop(PENDING_EMAIL_SESSION_KEY, None)
    next_url = request.session.pop(LOGIN_NEXT_SESSION_KEY, "") or settings.LOGIN_REDIRECT_URL
    return redirect(next_url)


@require_POST
def logout(request):
    auth_logout(request)
    return redirect("accounts:login")
```
Add the imports: `from django.contrib.auth import login as auth_login, logout as auth_logout` and remove the now-unused `HttpResponseNotFound` import.

`apps/accounts/urls.py`: add `path("logout/", views.logout, name="logout"),`.

- [ ] **Step 4: Write the templates and the home links**

`templates/accounts/verify.html`:
```html
{% extends "accounts/_auth_base.html" %}
{% block title %}Signing you in · {{ SITE_NAME }}{% endblock %}
{% block content %}
<h1 class="text-[20px] font-semibold leading-tight">Signing you in…</h1>
<p class="mt-2 text-ink-muted">Verifying the link and creating your session.</p>
<form id="verify-form" method="post" action="{% url 'accounts:verify' token %}" class="mt-6">
  {% csrf_token %}
  <button type="submit" class="rounded-md bg-accent px-4 py-2 font-semibold text-white hover:bg-accent-hover">Continue</button>
</form>
{% endblock %}
{% block scripts %}
<script nonce="{{ csp_nonce }}">document.getElementById("verify-form").submit();</script>
{% endblock %}
```

`templates/accounts/link_expired.html`:
```html
{% extends "accounts/_auth_base.html" %}
{% block title %}Link expired · {{ SITE_NAME }}{% endblock %}
{% block content %}
<p class="mono text-danger" aria-hidden="true">» ⊘</p>
<h1 class="mt-2 text-[20px] font-semibold leading-tight">This link no longer works</h1>
<p class="mt-2 text-ink-muted">Sign-in links expire after 15 minutes and can only be used once.</p>
<a href="{% url 'accounts:login' %}" class="mt-6 inline-block rounded-md bg-accent px-4 py-2 font-semibold text-white hover:bg-accent-hover">Send a new link</a>
{% endblock %}
```

`templates/core/home.html`: replace the last `<p class="mt-8 mono ...">` line with:
```html
  <p class="mt-8 mono text-ink-muted">{{ SHORT_DOMAIN }}»abc123</p>
  <div class="mt-8 flex items-center gap-4">
    {% if user.is_authenticated %}
      <span class="text-ink-muted">Signed in as <span class="mono text-ink">{{ user.email }}</span></span>
      <form method="post" action="{% url 'accounts:logout' %}">{% csrf_token %}<button type="submit" class="rounded-md border border-line px-3 py-2 font-medium hover:bg-surface-2">Sign out</button></form>
    {% else %}
      <a href="{% url 'accounts:login' %}" class="rounded-md bg-accent px-4 py-2 font-semibold text-white hover:bg-accent-hover">Sign in</a>
    {% endif %}
  </div>
```

- [ ] **Step 5: Run everything**

Run: `uv run pytest -v && uv run ruff check . && uv run ruff format --check . && uv run pre-commit run --all-files && uv run python manage.py makemigrations --check --dry-run`
Expected: all green, 0 warnings. Then start the dev server, open `/auth/login/`, submit an email, copy the link printed by the console email backend, open it and land on `/` signed in; sign out.

- [ ] **Step 6: Commit**

```bash
git add apps/accounts templates tests/accounts/test_views_verify.py
git commit -m "GH-<issue>-feat: verify magic links, sign out and home page session links"
```
