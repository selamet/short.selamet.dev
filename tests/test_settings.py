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
