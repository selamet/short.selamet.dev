# Project Scaffold, Settings, Tooling and CI — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A runnable, tested, containerized Django 6 skeleton for **short** with settings, the custom user model, all app packages, a health endpoint, the Tailwind/HTMX front-end pipeline, Docker files and GitHub Actions CI.

**Architecture:** One Django project (`config/`) with seven apps under `apps/`. Settings are split into `base`, `dev`, `prod`, `test` and read everything from environment variables through django-environ. The custom `User` model ships in this scaffold because `AUTH_USER_MODEL` cannot change after the first migration. Static assets are built with the Tailwind v4 standalone CLI; HTMX and Chart.js are vendored files.

**Tech Stack:** Python 3.13, Django 6.1, django-environ, psycopg 3, django-tasks-db, django-ninja (installed, wired later), pytest + pytest-django + factory_boy, ruff, uv, Tailwind v4 standalone CLI, HTMX 2, Chart.js 4, Docker, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-09-17-short-design.md`

## Global Constraints

- Everything in the repo is English: code, comments, docs, commit messages, issues, PRs.
- Commit messages: `GH-1-<type>: description` where type ∈ feat, fix, core, chore, refactor, test, docs. Branch: `GH-1`. No AI attribution lines anywhere.
- No server hostnames, IPs or credentials in the repository. Every runtime value comes from environment variables listed in `.env.example`.
- PostgreSQL via PgBouncer transaction pooling: `CONN_MAX_AGE = 0`, `DISABLE_SERVER_SIDE_CURSORS = True`.
- Redis only through Django's cache API, `KEY_PREFIX = "short"`, URLs use `rediss://` in production.
- Tasks: `django.tasks` API; `ImmediateBackend` in dev/test, `django_tasks_db.backend.DatabaseBackend` in prod.
- Tailwind v4 standalone CLI (no Node), compiled CSS is not committed.
- Tests: pytest, run with `uv run pytest`. Lint: `uv run ruff check .` and `uv run ruff format --check .`.
- Django 6 CSP middleware enabled with nonces; inline scripts in templates must carry `nonce="{{ csp_nonce }}"`.

---

## File structure

```
pyproject.toml                 # project metadata, deps, ruff, pytest config
uv.lock
manage.py
.env.example
.pre-commit-config.yaml
.github/workflows/ci.yml
Dockerfile
compose.yaml                   # production: web + worker
compose.dev.yaml               # local: postgres + redis
docker/entrypoint.sh
scripts/tailwind.sh            # downloads the standalone CLI, builds CSS
scripts/vendor.sh              # downloads htmx + chart.js into static/vendor
config/__init__.py
config/settings/__init__.py
config/settings/base.py
config/settings/dev.py
config/settings/prod.py
config/settings/test.py
config/urls.py
config/asgi.py
config/wsgi.py
apps/__init__.py
apps/core/{__init__,apps,views}.py
apps/accounts/{__init__,apps,models,managers,admin}.py + migrations/0001_initial.py
apps/workspaces/{__init__,apps}.py
apps/links/{__init__,apps}.py
apps/redirects/{__init__,apps}.py
apps/analytics/{__init__,apps}.py
apps/api/{__init__,apps}.py
templates/base.html
templates/core/home.html
static/src/app.css             # Tailwind input with @theme tokens
static/js/app.js               # theme + copy + toast helpers (tiny)
static/vendor/.gitkeep
tests/__init__.py
tests/conftest.py
tests/test_settings.py
tests/accounts/test_user_model.py
tests/core/test_health.py
tests/core/test_home.py
CONTRIBUTING.md
README.md (update)
```

---

### Task 1: Python project, settings package and manage.py

**Files:**
- Create: `pyproject.toml`, `manage.py`, `.env.example`, `config/__init__.py`, `config/settings/__init__.py`, `config/settings/base.py`, `config/settings/dev.py`, `config/settings/prod.py`, `config/settings/test.py`, `config/urls.py`, `config/asgi.py`, `config/wsgi.py`, `apps/__init__.py`, `tests/__init__.py`, `tests/conftest.py`, `tests/test_settings.py`

**Interfaces:**
- Produces: settings modules `config.settings.{base,dev,prod,test}`; `SHORT_DOMAIN` setting (string, e.g. `sho.rt`); `env` helper in `config.settings.base`.

- [ ] **Step 1: Create the branch**

```bash
git checkout -b GH-1
```

- [ ] **Step 2: Write pyproject.toml**

```toml
[project]
name = "short"
version = "0.1.0"
description = "Open-source, self-hostable URL shortener for social media teams."
readme = "README.md"
license = "MIT"
requires-python = ">=3.13"
dependencies = [
    "django>=6.1,<6.2",
    "django-environ>=0.14",
    "psycopg[binary]>=3.3",
    "redis>=6",
    "django-tasks-db>=0.13",
    "django-ninja>=1.7",
    "whitenoise>=6.8",
    "gunicorn>=23",
]

[dependency-groups]
dev = [
    "pytest>=8.3",
    "pytest-django>=4.14",
    "factory-boy>=3.3",
    "ruff>=0.16",
    "pre-commit>=4",
]

[tool.ruff]
target-version = "py313"
line-length = 100
exclude = ["**/migrations/*"]

[tool.ruff.lint]
select = ["E", "F", "I", "B", "UP", "DJ", "S", "T20"]
ignore = ["S101"]

[tool.ruff.lint.per-file-ignores]
"tests/**" = ["S105", "S106"]
"config/settings/*" = ["F403", "F405"]

[tool.pytest.ini_options]
DJANGO_SETTINGS_MODULE = "config.settings.test"
python_files = ["test_*.py"]
testpaths = ["tests"]
addopts = "-ra --strict-markers"
```

- [ ] **Step 3: Write manage.py, config package and wsgi/asgi**

`manage.py`:
```python
#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""

import os
import sys


def main():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")
    from django.core.management import execute_from_command_line

    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
```

`config/__init__.py` and `config/settings/__init__.py`: empty files.

`config/wsgi.py`:
```python
import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.prod")

application = get_wsgi_application()
```

`config/asgi.py`:
```python
import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.prod")

application = get_asgi_application()
```

`config/urls.py` (health and home views are added in Tasks 4 and 5; keep admin only for now):
```python
from django.conf import settings
from django.urls import path
from django.contrib import admin

urlpatterns = [
    path(f"{settings.ADMIN_URL_PATH}/", admin.site.urls),
]
```

- [ ] **Step 4: Write config/settings/base.py**

```python
"""Base settings shared by every environment. Values come from the environment."""

from pathlib import Path

import environ
from django.utils.csp import CSP

BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env()
if (BASE_DIR / ".env").exists():
    environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("SECRET_KEY")
DEBUG = False
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=[])

# The public short-link domain, without scheme (e.g. "sho.rt").
SHORT_DOMAIN = env("SHORT_DOMAIN", default="localhost:8000")
SITE_NAME = "short"

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "whitenoise.runserver_nostatic",
    "django.contrib.staticfiles",
    "django_tasks_db",
    "apps.core",
    "apps.accounts",
    "apps.workspaces",
    "apps.links",
    "apps.redirects",
    "apps.analytics",
    "apps.api",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.csp.ContentSecurityPolicyMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.template.context_processors.csp",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.core.context_processors.site",
            ],
        },
    },
]

# PostgreSQL behind PgBouncer (transaction pooling): no persistent connections,
# no server-side cursors.
DATABASES = {
    "default": {
        **env.db("DATABASE_URL"),
        "CONN_MAX_AGE": 0,
        "DISABLE_SERVER_SIDE_CURSORS": True,
    }
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Redis is shared and ACL-scoped to the "short:*" key space.
CACHES = {
    "default": {
        **env.cache("CACHE_URL", default="locmemcache://"),
        "KEY_PREFIX": "short",
    }
}

TASKS = {
    "default": {
        "BACKEND": env(
            "TASKS_BACKEND", default="django.tasks.backends.immediate.ImmediateBackend"
        ),
    }
}

AUTH_USER_MODEL = "accounts.User"
LOGIN_URL = "/auth/login/"
LOGIN_REDIRECT_URL = "/"

AUTH_PASSWORD_VALIDATORS = []

LANGUAGE_CODE = "en"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}
MEDIA_URL = "/media/"
MEDIA_ROOT = env("MEDIA_ROOT", default=str(BASE_DIR / "media"))

EMAIL_CONFIG = env.email("EMAIL_URL", default="consolemail://")
vars().update(EMAIL_CONFIG)
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="short <no-reply@localhost>")

ADMIN_URL_PATH = env("ADMIN_URL_PATH", default="admin")

SECURE_CSP = {
    "default-src": [CSP.SELF],
    "script-src": [CSP.SELF, CSP.NONCE],
    "style-src": [CSP.SELF, CSP.NONCE, "https://fonts.googleapis.com"],
    "font-src": [CSP.SELF, "https://fonts.gstatic.com"],
    "img-src": [CSP.SELF, "data:", "https:"],
    "connect-src": [CSP.SELF],
    "frame-ancestors": [CSP.NONE],
    "base-uri": [CSP.SELF],
    "form-action": [CSP.SELF],
}

X_FRAME_OPTIONS = "DENY"
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = False
SESSION_COOKIE_SAMESITE = "Lax"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"plain": {"format": "%(asctime)s %(levelname)s %(name)s %(message)s"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "plain"}},
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", default="INFO")},
}
```

- [ ] **Step 5: Write dev, prod and test settings**

`config/settings/dev.py`:
```python
from .base import *  # noqa: F401

DEBUG = True
ALLOWED_HOSTS = ["*"]
INTERNAL_IPS = ["127.0.0.1"]
```

`config/settings/prod.py`:
```python
from .base import *  # noqa: F401
from .base import env

DEBUG = False

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
USE_X_FORWARDED_HOST = True
SECURE_SSL_REDIRECT = env.bool("SECURE_SSL_REDIRECT", default=True)
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 60 * 60 * 24 * 365
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"

CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=[])

TASKS = {
    "default": {
        "BACKEND": env("TASKS_BACKEND", default="django_tasks_db.backend.DatabaseBackend"),
    }
}

SENTRY_DSN = env("SENTRY_DSN", default="")
if SENTRY_DSN:
    import sentry_sdk

    sentry_sdk.init(dsn=SENTRY_DSN, traces_sample_rate=0.0, send_default_pii=False)
```

`config/settings/test.py`:
```python
import os

os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("DATABASE_URL", "postgres://short:short@localhost:5432/short")
os.environ.setdefault("CACHE_URL", "locmemcache://")

from .base import *  # noqa: E402, F401

DEBUG = False
ALLOWED_HOSTS = ["testserver", "localhost", "sho.rt"]
SHORT_DOMAIN = "sho.rt"
TASKS = {"default": {"BACKEND": "django.tasks.backends.immediate.ImmediateBackend"}}
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}
```

Add `sentry-sdk>=2` to `[project].dependencies` in `pyproject.toml` (prod imports it lazily but it must be installed).

- [ ] **Step 6: Write .env.example**

```dotenv
# --- Core -------------------------------------------------------------
SECRET_KEY=change-me-to-a-long-random-string
DJANGO_SETTINGS_MODULE=config.settings.dev
ALLOWED_HOSTS=localhost,127.0.0.1
# Public short-link domain without scheme.
SHORT_DOMAIN=localhost:8000
# Path segment for the Django admin (https://<host>/<ADMIN_URL_PATH>/).
ADMIN_URL_PATH=admin

# --- Data stores --------------------------------------------------------
# Local (compose.dev.yaml):
DATABASE_URL=postgres://short:short@localhost:5432/short
CACHE_URL=redis://localhost:6379/0
# Production example (PgBouncer + TLS Redis):
# DATABASE_URL=postgresql://short_app:PASSWORD@db.example.com:5432/short?sslmode=verify-full
# CACHE_URL=rediss://short:PASSWORD@redis.example.com:6379/0

# --- Background tasks ---------------------------------------------------
# dev/test: django.tasks.backends.immediate.ImmediateBackend
# prod:     django_tasks_db.backend.DatabaseBackend
TASKS_BACKEND=django.tasks.backends.immediate.ImmediateBackend

# --- Email --------------------------------------------------------------
# consolemail:// prints to stdout. SMTP example:
# EMAIL_URL=smtp+tls://user:password@smtp.example.com:587
EMAIL_URL=consolemail://
DEFAULT_FROM_EMAIL=short <no-reply@example.com>

# --- Production only ----------------------------------------------------
# CSRF_TRUSTED_ORIGINS=https://sho.rt
# SECURE_SSL_REDIRECT=true
# SENTRY_DSN=
# MEDIA_ROOT=/data/media
LOG_LEVEL=INFO
```

- [ ] **Step 7: Write the test scaffolding and the settings smoke test**

`tests/__init__.py`: empty.

`tests/conftest.py`:
```python
import pytest


@pytest.fixture(autouse=True)
def _clear_cache():
    from django.core.cache import cache

    cache.clear()
    yield
    cache.clear()
```

`tests/test_settings.py`:
```python
from django.conf import settings


def test_short_domain_is_configured():
    assert settings.SHORT_DOMAIN == "sho.rt"


def test_database_is_pgbouncer_safe():
    db = settings.DATABASES["default"]
    assert db["CONN_MAX_AGE"] == 0
    assert db["DISABLE_SERVER_SIDE_CURSORS"] is True


def test_cache_keys_are_prefixed_for_redis_acl():
    assert settings.CACHES["default"]["KEY_PREFIX"] == "short"


def test_tasks_use_immediate_backend_in_tests():
    assert settings.TASKS["default"]["BACKEND"].endswith("ImmediateBackend")
```

- [ ] **Step 8: Install dependencies and run the smoke test (expect failure: apps missing)**

```bash
uv sync
uv run pytest tests/test_settings.py -v
```
Expected: errors because `apps.core` etc. do not exist yet (`ModuleNotFoundError`). That is the red state for Tasks 2 and 3; continue.

- [ ] **Step 9: Commit**

```bash
git add pyproject.toml uv.lock manage.py .env.example config tests apps/__init__.py
git commit -m "GH-1-chore: add project settings, manage.py and test scaffolding"
```

---

### Task 2: core app and the custom User model

**Files:**
- Create: `apps/core/__init__.py`, `apps/core/apps.py`, `apps/core/context_processors.py`, `apps/accounts/__init__.py`, `apps/accounts/apps.py`, `apps/accounts/managers.py`, `apps/accounts/models.py`, `apps/accounts/admin.py`, `apps/accounts/migrations/__init__.py`, `apps/accounts/migrations/0001_initial.py` (generated), `tests/accounts/__init__.py`, `tests/accounts/test_user_model.py`

**Interfaces:**
- Produces: `apps.accounts.models.User` with fields `email` (unique, USERNAME_FIELD), `display_name`, `theme` (choices `system|light|dark`), `is_active`, `is_staff`, `date_joined`; manager `User.objects.create_user(email, **extra)` and `create_superuser(email, password)`; `apps.core.context_processors.site(request)` returning `{"SITE_NAME": ..., "SHORT_DOMAIN": ...}`.

- [ ] **Step 1: Write the failing test**

`tests/accounts/__init__.py`: empty.

`tests/accounts/test_user_model.py`:
```python
import pytest
from django.contrib.auth import get_user_model

User = get_user_model()


@pytest.mark.django_db
def test_create_user_normalizes_email_and_has_no_usable_password():
    user = User.objects.create_user(email="Ada@Example.COM")
    assert user.email == "Ada@example.com"
    assert user.is_active is True
    assert user.is_staff is False
    assert user.has_usable_password() is False
    assert user.theme == "system"


@pytest.mark.django_db
def test_email_is_unique_case_insensitively():
    User.objects.create_user(email="ada@example.com")
    with pytest.raises(Exception):
        User.objects.create_user(email="ADA@example.com")


@pytest.mark.django_db
def test_create_superuser_sets_flags():
    admin = User.objects.create_superuser(email="root@example.com", password="x")
    assert admin.is_staff and admin.is_superuser and admin.has_usable_password()


def test_user_has_no_username_field():
    assert User.USERNAME_FIELD == "email"
    assert not hasattr(User, "username")
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
uv run pytest tests/accounts -v
```
Expected: FAIL / errors with `ModuleNotFoundError: No module named 'apps.core'`.

- [ ] **Step 3: Write the core app**

`apps/core/__init__.py`: empty.

`apps/core/apps.py`:
```python
from django.apps import AppConfig


class CoreConfig(AppConfig):
    name = "apps.core"
    label = "core"
```

`apps/core/context_processors.py`:
```python
from django.conf import settings


def site(request):
    return {"SITE_NAME": settings.SITE_NAME, "SHORT_DOMAIN": settings.SHORT_DOMAIN}
```

- [ ] **Step 4: Write the accounts app**

`apps/accounts/__init__.py`: empty.

`apps/accounts/apps.py`:
```python
from django.apps import AppConfig


class AccountsConfig(AppConfig):
    name = "apps.accounts"
    label = "accounts"
```

`apps/accounts/managers.py`:
```python
from django.contrib.auth.base_user import BaseUserManager


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create(self, email, password, **extra):
        if not email:
            raise ValueError("An email address is required.")
        email = self.normalize_email(email)
        user = self.model(email=email, **extra)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra):
        extra.setdefault("is_staff", False)
        extra.setdefault("is_superuser", False)
        return self._create(email, password, **extra)

    def create_superuser(self, email, password, **extra):
        extra["is_staff"] = True
        extra["is_superuser"] = True
        return self._create(email, password, **extra)
```

`apps/accounts/models.py`:
```python
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.db import models
from django.db.models.functions import Lower
from django.utils import timezone

from .managers import UserManager


class User(AbstractBaseUser, PermissionsMixin):
    class Theme(models.TextChoices):
        SYSTEM = "system", "System"
        LIGHT = "light", "Light"
        DARK = "dark", "Dark"

    email = models.EmailField(unique=True)
    display_name = models.CharField(max_length=80, blank=True)
    theme = models.CharField(max_length=10, choices=Theme.choices, default=Theme.SYSTEM)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    date_joined = models.DateTimeField(default=timezone.now)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    class Meta:
        constraints = [
            models.UniqueConstraint(Lower("email"), name="accounts_user_email_ci_unique"),
        ]

    def __str__(self):
        return self.email

    @property
    def short_name(self):
        return self.display_name or self.email.split("@")[0]
```

`apps/accounts/admin.py`:
```python
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    ordering = ("email",)
    list_display = ("email", "display_name", "is_staff", "is_active", "date_joined")
    search_fields = ("email", "display_name")
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Profile", {"fields": ("display_name", "theme")}),
        ("Permissions", {"fields": ("is_active", "is_staff", "is_superuser", "groups")}),
        ("Dates", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = ((None, {"fields": ("email", "password1", "password2")}),)
```

`apps/accounts/migrations/__init__.py`: empty.

- [ ] **Step 5: Create the remaining empty apps so settings import cleanly** (their contents are finished in Task 3, but `INSTALLED_APPS` needs them now)

For each of `workspaces`, `links`, `redirects`, `analytics`, `api` create `apps/<name>/__init__.py` (empty) and `apps/<name>/apps.py`:
```python
from django.apps import AppConfig


class WorkspacesConfig(AppConfig):  # rename per app: LinksConfig, RedirectsConfig, AnalyticsConfig, ApiConfig
    name = "apps.workspaces"        # apps.links, apps.redirects, apps.analytics, apps.api
    label = "workspaces"            # links, redirects, analytics, api
```

- [ ] **Step 6: Start local Postgres, generate the migration, run tests**

Write `compose.dev.yaml` now (it is also part of Task 6's deliverable, but tests need it):
```yaml
services:
  postgres:
    image: postgres:17-alpine
    environment:
      POSTGRES_USER: short
      POSTGRES_PASSWORD: short
      POSTGRES_DB: short
    ports:
      - "127.0.0.1:5432:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U short"]
      interval: 5s
      timeout: 3s
      retries: 10
  redis:
    image: redis:7-alpine
    ports:
      - "127.0.0.1:6379:6379"
volumes:
  pgdata:
```

```bash
docker compose -f compose.dev.yaml up -d
cp .env.example .env
uv run python manage.py makemigrations accounts
uv run pytest tests/accounts tests/test_settings.py -v
```
Expected: `0001_initial.py` created under `apps/accounts/migrations/`; all tests PASS.

- [ ] **Step 7: Commit**

```bash
git add apps compose.dev.yaml tests/accounts
git commit -m "GH-1-feat: add core and accounts apps with email-based User model"
```

---

### Task 3: Remaining app packages and migration hygiene check

**Files:**
- Modify: `apps/workspaces/apps.py`, `apps/links/apps.py`, `apps/redirects/apps.py`, `apps/analytics/apps.py`, `apps/api/apps.py` (verify each has the correct class name, `name` and `label` from Task 2 Step 5)
- Create: `apps/<name>/migrations/__init__.py` for workspaces, links, analytics (apps that will have models); `tests/test_migrations.py`

**Interfaces:**
- Produces: importable packages `apps.workspaces`, `apps.links`, `apps.redirects`, `apps.analytics`, `apps.api`.

- [ ] **Step 1: Write the failing test**

`tests/test_migrations.py`:
```python
from io import StringIO

import pytest
from django.core.management import call_command


@pytest.mark.django_db
def test_no_missing_migrations():
    out = StringIO()
    call_command("makemigrations", "--check", "--dry-run", stdout=out)
    assert "No changes detected" in out.getvalue()


def test_every_app_is_installed():
    from django.apps import apps

    for label in ["core", "accounts", "workspaces", "links", "redirects", "analytics", "api"]:
        assert apps.is_installed(f"apps.{label}")
```

- [ ] **Step 2: Run the test**

```bash
uv run pytest tests/test_migrations.py -v
```
Expected: PASS if Task 2 was completed correctly. If `test_every_app_is_installed` fails, fix the `name` attribute of the failing AppConfig.

- [ ] **Step 3: Add migrations packages and run ruff**

```bash
mkdir -p apps/workspaces/migrations apps/links/migrations apps/analytics/migrations
touch apps/workspaces/migrations/__init__.py apps/links/migrations/__init__.py apps/analytics/migrations/__init__.py
uv run ruff check . && uv run ruff format .
uv run pytest -v
```
Expected: ruff clean, all tests PASS.

- [ ] **Step 4: Commit**

```bash
git add apps tests/test_migrations.py
git commit -m "GH-1-chore: add remaining app packages and migration check"
```

---

### Task 4: Health endpoint

**Files:**
- Create: `apps/core/views.py`, `apps/core/urls.py`, `tests/core/__init__.py`, `tests/core/test_health.py`
- Modify: `config/urls.py`

**Interfaces:**
- Produces: `GET /health/` → `200 {"status": "ok", "database": "ok", "cache": "ok"}` or `503` with the failing component set to `"error"`.

- [ ] **Step 1: Write the failing test**

`tests/core/__init__.py`: empty.

`tests/core/test_health.py`:
```python
from unittest import mock

import pytest


@pytest.mark.django_db
def test_health_ok(client):
    response = client.get("/health/")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok", "cache": "ok"}


@pytest.mark.django_db
def test_health_reports_cache_failure(client):
    with mock.patch("apps.core.views.cache.set", side_effect=RuntimeError("down")):
        response = client.get("/health/")
    assert response.status_code == 503
    assert response.json()["cache"] == "error"
    assert response.json()["status"] == "degraded"
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
uv run pytest tests/core/test_health.py -v
```
Expected: FAIL with 404.

- [ ] **Step 3: Implement the view**

`apps/core/views.py`:
```python
import logging

from django.core.cache import cache
from django.db import connection
from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

logger = logging.getLogger(__name__)


def _check_database():
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
        cursor.fetchone()


def _check_cache():
    cache.set("health", "ok", timeout=5)
    if cache.get("health") != "ok":
        raise RuntimeError("cache read-back failed")


@never_cache
@require_GET
def health(request):
    result = {"status": "ok"}
    for name, check in (("database", _check_database), ("cache", _check_cache)):
        try:
            check()
            result[name] = "ok"
        except Exception:
            logger.exception("health check failed: %s", name)
            result[name] = "error"
            result["status"] = "degraded"
    status = 200 if result["status"] == "ok" else 503
    return JsonResponse(result, status=status)
```

`apps/core/urls.py`:
```python
from django.urls import path

from . import views

app_name = "core"

urlpatterns = [
    path("health/", views.health, name="health"),
]
```

`config/urls.py`:
```python
from django.conf import settings
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path(f"{settings.ADMIN_URL_PATH}/", admin.site.urls),
    path("", include("apps.core.urls")),
]
```

- [ ] **Step 4: Run the tests**

```bash
uv run pytest tests/core/test_health.py -v
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/core config/urls.py tests/core
git commit -m "GH-1-feat: add health endpoint"
```

---

### Task 5: Base template, Tailwind pipeline, vendored JS and home placeholder

**Files:**
- Create: `scripts/tailwind.sh`, `scripts/vendor.sh`, `static/src/app.css`, `static/js/app.js`, `static/vendor/.gitkeep`, `templates/base.html`, `templates/core/home.html`, `tests/core/test_home.py`
- Modify: `apps/core/views.py`, `apps/core/urls.py`, `.gitignore`

**Interfaces:**
- Produces: `templates/base.html` with blocks `title`, `head`, `content`, `scripts`; CSS variables `--bg --surface --surface-2 --line --ink --ink-muted --accent --accent-hover --danger --ok --warn`; `GET /` renders the placeholder home page.

- [ ] **Step 1: Write the failing test**

`tests/core/test_home.py`:
```python
import pytest


@pytest.mark.django_db
def test_home_renders_base_template(client):
    response = client.get("/")
    assert response.status_code == 200
    body = response.content.decode()
    assert 'data-theme="system"' in body
    assert "short" in body
    assert "Content-Security-Policy" in response.headers
    assert "nonce-" in response.headers["Content-Security-Policy"]
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
uv run pytest tests/core/test_home.py -v
```
Expected: FAIL with 404.

- [ ] **Step 3: Write the Tailwind input with the design tokens**

`static/src/app.css`:
```css
@import "tailwindcss";

@source "../../templates/**/*.html";
@source "../../apps/**/*.py";

@theme {
  --font-sans: "IBM Plex Sans", system-ui, sans-serif;
  --font-mono: "IBM Plex Mono", ui-monospace, monospace;

  --color-bg: var(--bg);
  --color-surface: var(--surface);
  --color-surface-2: var(--surface-2);
  --color-line: var(--line);
  --color-ink: var(--ink);
  --color-ink-muted: var(--ink-muted);
  --color-accent: var(--accent);
  --color-accent-hover: var(--accent-hover);
  --color-danger: var(--danger);
  --color-ok: var(--ok);
  --color-warn: var(--warn);

  --radius-sm: 4px;
  --radius-md: 6px;
  --radius-lg: 8px;
  --radius-xl: 12px;

  --shadow-e1: 0 1px 2px rgba(0, 0, 0, 0.08);
  --shadow-e3: 0 8px 24px rgba(0, 0, 0, 0.14);
}

:root,
:root[data-theme="light"] {
  --bg: #e9e6e0;
  --surface: #ffffff;
  --surface-2: #f4f2ee;
  --line: rgba(0, 0, 0, 0.14);
  --ink: #1b1a18;
  --ink-muted: #77736c;
  --accent: #d8552a;
  --accent-hover: #c04a22;
  --danger: #b22020;
  --ok: #2f6f4e;
  --warn: #b8471f;
  color-scheme: light;
}

:root[data-theme="dark"] {
  --bg: #141312;
  --surface: #1b1a18;
  --surface-2: #232120;
  --line: rgba(255, 255, 255, 0.14);
  --ink: #e9e6e0;
  --ink-muted: #8d8880;
  --accent: #ef6a3d;
  --accent-hover: #f37d55;
  --danger: #e06666;
  --ok: #5bbd8c;
  --warn: #e0884f;
  color-scheme: dark;
}

@media (prefers-color-scheme: dark) {
  :root[data-theme="system"] {
    --bg: #141312;
    --surface: #1b1a18;
    --surface-2: #232120;
    --line: rgba(255, 255, 255, 0.14);
    --ink: #e9e6e0;
    --ink-muted: #8d8880;
    --accent: #ef6a3d;
    --accent-hover: #f37d55;
    --danger: #e06666;
    --ok: #5bbd8c;
    --warn: #e0884f;
    color-scheme: dark;
  }
}

@layer base {
  body {
    @apply bg-bg text-ink font-sans text-[13px] antialiased;
  }
  .mono {
    @apply font-mono;
  }
}
```

- [ ] **Step 4: Write the build and vendor scripts**

`scripts/tailwind.sh`:
```bash
#!/usr/bin/env bash
# Downloads the Tailwind v4 standalone CLI (no Node required) and builds static/css/app.css.
# Usage: scripts/tailwind.sh [--watch]
set -euo pipefail

TAILWIND_VERSION="${TAILWIND_VERSION:-v4.3.3}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BIN_DIR="$ROOT/.bin"
BIN="$BIN_DIR/tailwindcss"

os="$(uname -s | tr '[:upper:]' '[:lower:]')"
arch="$(uname -m)"
case "$os-$arch" in
  darwin-arm64) asset="tailwindcss-macos-arm64" ;;
  darwin-x86_64) asset="tailwindcss-macos-x64" ;;
  linux-aarch64|linux-arm64) asset="tailwindcss-linux-arm64" ;;
  linux-x86_64) asset="tailwindcss-linux-x64" ;;
  *) echo "unsupported platform: $os-$arch" >&2; exit 1 ;;
esac

if [ ! -x "$BIN" ] || [ "$(cat "$BIN_DIR/.version" 2>/dev/null)" != "$TAILWIND_VERSION" ]; then
  mkdir -p "$BIN_DIR"
  curl -fsSL "https://github.com/tailwindlabs/tailwindcss/releases/download/${TAILWIND_VERSION}/${asset}" -o "$BIN"
  chmod +x "$BIN"
  echo "$TAILWIND_VERSION" > "$BIN_DIR/.version"
fi

mkdir -p "$ROOT/static/css"
exec "$BIN" -i "$ROOT/static/src/app.css" -o "$ROOT/static/css/app.css" --minify "$@"
```

`scripts/vendor.sh`:
```bash
#!/usr/bin/env bash
# Downloads pinned front-end libraries into static/vendor (no CDN at runtime).
set -euo pipefail

HTMX_VERSION="${HTMX_VERSION:-2.0.8}"
CHARTJS_VERSION="${CHARTJS_VERSION:-4.5.1}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEST="$ROOT/static/vendor"
mkdir -p "$DEST"

curl -fsSL "https://cdn.jsdelivr.net/npm/htmx.org@${HTMX_VERSION}/dist/htmx.min.js" -o "$DEST/htmx.min.js"
curl -fsSL "https://cdn.jsdelivr.net/npm/chart.js@${CHARTJS_VERSION}/dist/chart.umd.js" -o "$DEST/chart.umd.js"
echo "htmx ${HTMX_VERSION}, chart.js ${CHARTJS_VERSION} → $DEST"
```

Check that the pinned htmx 2.0.x version exists before committing: `curl -fsI https://cdn.jsdelivr.net/npm/htmx.org@2.0.8/dist/htmx.min.js`. If it 404s, pick the newest `2.0.x` from `https://data.jsdelivr.com/v1/package/npm/htmx.org` and update the default.

```bash
chmod +x scripts/tailwind.sh scripts/vendor.sh
scripts/vendor.sh
scripts/tailwind.sh
```
Expected: `static/vendor/htmx.min.js`, `static/vendor/chart.umd.js`, `static/css/app.css` exist.

Append to `.gitignore`:
```
# Built assets and downloaded tooling
/static/css/
/.bin/
```
`static/vendor/` **is committed** (pinned, reproducible, self-host friendly).

- [ ] **Step 5: Write the base template, tiny JS and the home page**

`static/js/app.js`:
```javascript
// Theme, clipboard and toast helpers. Kept intentionally small; HTMX does the rest.
(function () {
  const root = document.documentElement;

  function toast(message, kind) {
    const host = document.getElementById("toasts");
    if (!host) return;
    const el = document.createElement("div");
    el.className = "toast toast-" + (kind || "info");
    el.setAttribute("role", "status");
    el.textContent = message;
    host.appendChild(el);
    setTimeout(() => el.remove(), 2600);
  }

  document.addEventListener("click", async (event) => {
    const trigger = event.target.closest("[data-copy]");
    if (!trigger) return;
    event.preventDefault();
    try {
      await navigator.clipboard.writeText(trigger.getAttribute("data-copy"));
      toast("Copied", "success");
    } catch (_) {
      toast("Copy failed", "error");
    }
  });

  document.addEventListener("htmx:afterRequest", (event) => {
    const message = event.detail.xhr && event.detail.xhr.getResponseHeader("X-Toast");
    if (message) toast(message, "success");
  });

  window.short = { toast, setTheme: (value) => root.setAttribute("data-theme", value) };
})();
```

`templates/base.html`:
```html
{% load static %}<!doctype html>
<html lang="en" data-theme="{{ request.user.theme|default:'system' }}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{% block title %}{{ SITE_NAME }}{% endblock %}</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&family=IBM+Plex+Sans:wght@400;500;600&display=swap">
  <link rel="stylesheet" href="{% static 'css/app.css' %}">
  <link rel="icon" href="{% static 'favicon.svg' %}" type="image/svg+xml">
  <meta name="csrf-token" content="{{ csrf_token }}">
  {% block head %}{% endblock %}
</head>
<body hx-headers='{"X-CSRFToken": "{{ csrf_token }}"}'>
  {% block body %}
  <main class="mx-auto max-w-6xl px-4">{% block content %}{% endblock %}</main>
  {% endblock %}
  <div id="toasts" class="fixed bottom-4 right-4 flex flex-col gap-2" aria-live="polite"></div>
  <div id="modal"></div>
  <script src="{% static 'vendor/htmx.min.js' %}" nonce="{{ csp_nonce }}"></script>
  <script src="{% static 'js/app.js' %}" nonce="{{ csp_nonce }}"></script>
  {% block scripts %}{% endblock %}
</body>
</html>
```

`static/favicon.svg`:
```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><rect width="32" height="32" rx="6" fill="#1b1a18"/><text x="16" y="23" text-anchor="middle" font-family="IBM Plex Mono, monospace" font-size="22" font-weight="600" fill="#d8552a">»</text></svg>
```

`templates/core/home.html`:
```html
{% extends "base.html" %}
{% block title %}{{ SITE_NAME }} · short links built for people who post all day{% endblock %}
{% block content %}
<section class="py-24">
  <p class="mono text-accent text-[13px]">»</p>
  <h1 class="mt-4 text-[28px] font-semibold leading-[1.15] tracking-[-0.025em]">Short links built for people who post all day.</h1>
  <p class="mt-4 max-w-xl text-ink-muted">Open-source, self-hostable URL shortener for social media teams. Landing page and dashboard arrive in later issues.</p>
  <p class="mt-8 mono text-ink-muted">{{ SHORT_DOMAIN }}»abc123</p>
</section>
{% endblock %}
```

Add the view and route. `apps/core/views.py` (append):
```python
from django.shortcuts import render


def home(request):
    return render(request, "core/home.html")
```

`apps/core/urls.py`:
```python
from django.urls import path

from . import views

app_name = "core"

urlpatterns = [
    path("", views.home, name="home"),
    path("health/", views.health, name="health"),
]
```

- [ ] **Step 6: Run the tests and the dev server**

```bash
uv run pytest tests/core -v
uv run python manage.py runserver
```
Expected: tests PASS; `http://localhost:8000/` shows the placeholder with the dark/light tokens applied (toggle the OS theme to verify `system` mode). Stop the server.

- [ ] **Step 7: Commit**

```bash
git add scripts static templates apps/core tests/core .gitignore
git commit -m "GH-1-feat: add base template, Tailwind pipeline and vendored front-end assets"
```

---

### Task 6: Dockerfile, production compose and entrypoint

**Files:**
- Create: `Dockerfile`, `.dockerignore`, `docker/entrypoint.sh`, `compose.yaml`
- Modify: `compose.dev.yaml` (already created in Task 2; verify content)

**Interfaces:**
- Produces: image that runs `gunicorn config.wsgi` as `web` and `python manage.py db_worker` as `worker`; entrypoint runs `migrate` only when `RUN_MIGRATIONS=1`.

- [ ] **Step 1: Write .dockerignore**

```
.git
.venv
.bin
.env
.env.*
!.env.example
__pycache__
*.pyc
.pytest_cache
.ruff_cache
staticfiles
media
docs
node_modules
```

- [ ] **Step 2: Write the Dockerfile**

```dockerfile
# syntax=docker/dockerfile:1.7

# --- assets: build Tailwind CSS with the standalone CLI (no Node) ---------------
FROM debian:bookworm-slim AS assets
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY scripts/tailwind.sh scripts/tailwind.sh
COPY static static
COPY templates templates
COPY apps apps
RUN bash scripts/tailwind.sh

# --- python deps ------------------------------------------------------------------
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS deps
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/opt/venv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev --no-install-project

# --- runtime ------------------------------------------------------------------------
FROM python:3.13-slim-bookworm AS runtime
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PATH="/opt/venv/bin:$PATH" \
    DJANGO_SETTINGS_MODULE=config.settings.prod
RUN apt-get update && apt-get install -y --no-install-recommends libpq5 curl && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 app
WORKDIR /app
COPY --from=deps /opt/venv /opt/venv
COPY --chown=app:app . .
COPY --from=assets --chown=app:app /app/static/css/app.css static/css/app.css
RUN SECRET_KEY=build DATABASE_URL=sqlite:///build.db python manage.py collectstatic --noinput \
    && rm -f build.db && chmod +x docker/entrypoint.sh && mkdir -p /data/media && chown -R app:app /data
USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s CMD curl -fsS http://127.0.0.1:8000/health/ || exit 1
ENTRYPOINT ["docker/entrypoint.sh"]
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3", "--timeout", "30", "--access-logfile", "-"]
```

- [ ] **Step 3: Write the entrypoint**

`docker/entrypoint.sh`:
```bash
#!/usr/bin/env bash
set -euo pipefail

if [ "${RUN_MIGRATIONS:-0}" = "1" ]; then
  echo ">>> applying migrations"
  python manage.py migrate --noinput
fi

exec "$@"
```

- [ ] **Step 4: Write compose.yaml (production)**

```yaml
# Production stack. TLS and routing are handled by the host's reverse proxy,
# which forwards the public domain to the port published in a host-side override
# (for example 127.0.0.1:8107 -> web:8000). Postgres and Redis are external.
services:
  web:
    build: .
    image: short:latest
    env_file: .env
    environment:
      RUN_MIGRATIONS: "1"
    volumes:
      - media:/data/media
    restart: unless-stopped
  worker:
    image: short:latest
    env_file: .env
    command: ["python", "manage.py", "db_worker", "--reload"]
    volumes:
      - media:/data/media
    depends_on:
      web:
        condition: service_healthy
    restart: unless-stopped
volumes:
  media:
```

Check the exact `db_worker` flags before committing: `uv run python manage.py db_worker --help`. Remove `--reload` if it is not a supported option and use the documented flags for interval/queue names instead.

- [ ] **Step 5: Build the image and smoke-test it**

```bash
docker build -t short:latest .
docker run --rm -e SECRET_KEY=x -e DATABASE_URL=sqlite:////tmp/x.db -e ALLOWED_HOSTS=localhost -e SECURE_SSL_REDIRECT=false -p 8000:8000 short:latest &
sleep 5 && curl -fsS http://localhost:8000/health/ ; echo
docker stop $(docker ps -q --filter ancestor=short:latest)
```
Expected: build succeeds; health returns JSON with `"database": "ok"` (sqlite) and `"cache": "ok"` (locmem).

- [ ] **Step 6: Commit**

```bash
git add Dockerfile .dockerignore docker compose.yaml compose.dev.yaml
git commit -m "GH-1-chore: add Dockerfile, entrypoint and compose files"
```

---

### Task 7: CI, pre-commit and contributor docs

**Files:**
- Create: `.github/workflows/ci.yml`, `.pre-commit-config.yaml`, `CONTRIBUTING.md`
- Modify: `README.md`

- [ ] **Step 1: Write the CI workflow**

`.github/workflows/ci.yml`:
```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v6
        with:
          enable-cache: true
      - run: uv sync --frozen
      - run: uv run ruff check .
      - run: uv run ruff format --check .

  test:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:17-alpine
        env:
          POSTGRES_USER: short
          POSTGRES_PASSWORD: short
          POSTGRES_DB: short
        ports: ["5432:5432"]
        options: >-
          --health-cmd "pg_isready -U short"
          --health-interval 5s
          --health-timeout 3s
          --health-retries 10
    env:
      SECRET_KEY: ci-secret
      DATABASE_URL: postgres://short:short@localhost:5432/short
      CACHE_URL: locmemcache://
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v6
        with:
          enable-cache: true
      - run: uv sync --frozen
      - run: uv run pytest -v

  docker:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: docker/setup-buildx-action@v3
      - uses: docker/build-push-action@v6
        with:
          context: .
          push: false
          tags: short:ci
          cache-from: type=gha
          cache-to: type=gha,mode=max
```

- [ ] **Step 2: Write pre-commit config**

`.pre-commit-config.yaml`:
```yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.16.8
    hooks:
      - id: ruff
        args: [--fix]
      - id: ruff-format
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v5.0.0
    hooks:
      - id: end-of-file-fixer
      - id: trailing-whitespace
      - id: check-yaml
      - id: check-added-large-files
        args: [--maxkb=1500]
```

```bash
uv run pre-commit install
uv run pre-commit run --all-files
```
Expected: all hooks pass (fix anything they change and re-run).

- [ ] **Step 3: Write CONTRIBUTING.md**

```markdown
# Contributing

Thanks for helping build **short**.

## Local setup

    docker compose -f compose.dev.yaml up -d   # Postgres + Redis
    cp .env.example .env
    uv sync
    scripts/vendor.sh                           # htmx + chart.js (already committed, re-run to upgrade)
    scripts/tailwind.sh --watch &               # CSS
    uv run python manage.py migrate
    uv run python manage.py runserver

## Checks

    uv run ruff check . && uv run ruff format --check .
    uv run pytest

## Workflow

- Every change starts from a GitHub issue. Branch name `GH-<issue>`.
- Commit messages: `GH-<issue>-<type>: description` (`feat`, `fix`, `core`, `chore`, `refactor`, `test`, `docs`).
- Open a pull request that says `Closes #<issue>`, what changed and how it was tested.
- Everything in the repository is written in English.
- Tests first: add or update a test with every behavior change.
```

- [ ] **Step 4: Update README.md**

Replace the `## Status` section with:
```markdown
## Status

Early development. Follow the [issues](../../issues) for the roadmap and `docs/superpowers/specs/` for the design.

## Quick start (development)

    docker compose -f compose.dev.yaml up -d
    cp .env.example .env
    uv sync && scripts/tailwind.sh
    uv run python manage.py migrate
    uv run python manage.py runserver

See [CONTRIBUTING.md](CONTRIBUTING.md) for the full workflow. Self-hosting docs arrive with the deployment issue.
```

- [ ] **Step 5: Run everything once more, push, open the PR**

```bash
uv run ruff check . && uv run ruff format --check . && uv run pytest -v
git add .github .pre-commit-config.yaml CONTRIBUTING.md README.md
git commit -m "GH-1-chore: add CI workflow, pre-commit and contributor docs"
git push -u origin GH-1
```

Open the PR with `gh pr create` (title `GH-1: Project scaffold, settings, tooling and CI`, body with Summary / Changes / Testing sections and `Closes #1`, assignee `selamet`). Wait for CI to be green.
