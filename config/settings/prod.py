from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F401
from .base import MAILERS, env

DEBUG = False

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
USE_X_FORWARDED_HOST = True
SECURE_SSL_REDIRECT = env.bool("SECURE_SSL_REDIRECT", default=True)
# The container HEALTHCHECK hits /health/ over plain http; keep it working even
# when SECURE_SSL_REDIRECT is on.
SECURE_REDIRECT_EXEMPT = [r"^health/$"]
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 60 * 60 * 24 * 365
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"

CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=[])

MEDIA_ROOT = env("MEDIA_ROOT", default="/data/media")

if MAILERS["default"]["BACKEND"].endswith("console.EmailBackend"):
    raise ImproperlyConfigured(
        "EMAIL_URL must point at a real mail server in production (got the console backend)."
    )

TASKS = {
    "default": {
        "BACKEND": env("TASKS_BACKEND", default="django_tasks_db.backend.DatabaseBackend"),
    }
}

SENTRY_DSN = env("SENTRY_DSN", default="")
if SENTRY_DSN:
    import sentry_sdk

    sentry_sdk.init(dsn=SENTRY_DSN, traces_sample_rate=0.0, send_default_pii=False)
