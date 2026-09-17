from django.conf import settings

from config.settings.base import _mailer_from_url, cache_from_url


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


def test_mailers_is_configured_without_deprecated_email_settings():
    assert settings.MAILERS["default"]["BACKEND"].endswith("locmem.EmailBackend")
    assert not hasattr(settings, "EMAIL_BACKEND")


def test_mailer_from_url_maps_smtp_url_to_mailers_options():
    mailer = _mailer_from_url("smtp+tls://user:secret@mail.example.com:587")
    assert mailer == {
        "BACKEND": "django.core.mail.backends.smtp.EmailBackend",
        "OPTIONS": {
            "host": "mail.example.com",
            "port": 587,
            "username": "user",
            "password": "secret",
            "use_tls": True,
        },
    }


def test_mailer_from_url_maps_consolemail_url_with_no_options():
    mailer = _mailer_from_url("consolemail://")
    assert mailer == {
        "BACKEND": "django.core.mail.backends.console.EmailBackend",
        "OPTIONS": {},
    }


def test_mailer_from_url_maps_filemail_url_to_file_path_option():
    mailer = _mailer_from_url("filemail:////data/mail")
    assert mailer == {
        "BACKEND": "django.core.mail.backends.filebased.EmailBackend",
        "OPTIONS": {"file_path": "/data/mail"},
    }


def test_cache_from_url_forces_the_builtin_redis_backend():
    cache = cache_from_url("rediss://user:pw@host:6379/0")
    assert cache["BACKEND"] == "django.core.cache.backends.redis.RedisCache"
    assert cache["KEY_PREFIX"] == "short"
