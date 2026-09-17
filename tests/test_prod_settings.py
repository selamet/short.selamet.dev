"""Import config.settings.prod under placeholder env vars and check the hardening.

Each test forces a fresh import of config.settings.prod (and its config.settings.base
dependency) so that module-level code re-runs against the env vars set by that test,
then relies on monkeypatch to restore sys.modules to whatever it held before the test.
"""

import sys
from pathlib import Path

import environ
import pytest
from django.conf import Settings
from django.core.exceptions import ImproperlyConfigured

PLACEHOLDER_ENV = {
    "SECRET_KEY": "placeholder-secret-key",
    "DATABASE_URL": "sqlite:///x.db",
    "ALLOWED_HOSTS": "example.com",
    "EMAIL_URL": "smtp+tls://u:p@mail.example.com:587",
    "CACHE_URL": "locmemcache://",
}


def _build_prod_settings(monkeypatch, env_overrides):
    # Ignore a developer's local .env entirely: base.py would otherwise re-read it on
    # the fresh import below and could reintroduce a real TASKS_BACKEND/SECRET_KEY/etc.
    # value that this test never asked for.
    monkeypatch.setattr(environ.Env, "read_env", staticmethod(lambda *a, **k: None))
    for key, value in env_overrides.items():
        monkeypatch.setenv(key, value)
    # TASKS_BACKEND is intentionally not in the placeholder set: it must fall back to
    # prod's default rather than pick up whatever this process happened to load first.
    monkeypatch.delenv("TASKS_BACKEND", raising=False)
    # Force a fresh import: config.settings.base is already cached (loaded for the
    # test settings module), and would otherwise be reused as-is, ignoring the env
    # vars set above.
    monkeypatch.delitem(sys.modules, "config.settings.prod", raising=False)
    monkeypatch.delitem(sys.modules, "config.settings.base", raising=False)
    return Settings("config.settings.prod")


def test_prod_settings_harden_security_and_defaults(monkeypatch):
    settings = _build_prod_settings(monkeypatch, PLACEHOLDER_ENV)

    assert settings.DEBUG is False
    assert settings.SECURE_SSL_REDIRECT is True
    assert settings.SESSION_COOKIE_SECURE is True
    assert settings.CSRF_COOKIE_SECURE is True
    assert settings.SECURE_HSTS_SECONDS > 0
    assert settings.SECURE_REDIRECT_EXEMPT == [r"^health/$"]
    assert settings.MEDIA_ROOT == "/data/media"
    assert settings.TASKS["default"]["BACKEND"] == "django_tasks_db.backend.DatabaseBackend"

    # Settings construction never opens a database connection.
    assert not Path("x.db").exists()


def test_prod_settings_reject_console_email_backend(monkeypatch):
    env = {**PLACEHOLDER_ENV, "EMAIL_URL": "consolemail://"}

    with pytest.raises(ImproperlyConfigured):
        _build_prod_settings(monkeypatch, env)
