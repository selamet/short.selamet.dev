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

# Absolute origin used in emails and other links generated outside a request.
SITE_URL = env("SITE_URL", default=f"http://{SHORT_DOMAIN}")
# Number of reverse proxies in front of the app that append to X-Forwarded-For;
# 0 = trust REMOTE_ADDR only.
TRUSTED_PROXY_HOPS = env.int("TRUSTED_PROXY_HOPS", default=1)
MAGIC_LINK_TTL_MINUTES = 15
MAGIC_LINK_RESEND_COOLDOWN_SECONDS = 45
INVITATION_TTL_DAYS = 7
# Magic link request rate limits, enforced in apps.accounts.services.request_magic_link.
MAGIC_LINK_RATE_PER_EMAIL = env.int("MAGIC_LINK_RATE_PER_EMAIL", default=3)
MAGIC_LINK_RATE_PER_EMAIL_WINDOW = env.int("MAGIC_LINK_RATE_PER_EMAIL_WINDOW", default=600)
MAGIC_LINK_RATE_PER_IP = env.int("MAGIC_LINK_RATE_PER_IP", default=20)
MAGIC_LINK_RATE_PER_IP_WINDOW = env.int("MAGIC_LINK_RATE_PER_IP_WINDOW", default=3600)
# Workspace invitation rate limits, enforced in apps.workspaces.services.invite.
INVITE_RATE_PER_WORKSPACE = env.int("INVITE_RATE_PER_WORKSPACE", default=20)
INVITE_RATE_PER_WORKSPACE_WINDOW = env.int("INVITE_RATE_PER_WORKSPACE_WINDOW", default=3600)
INVITE_RATE_PER_USER = env.int("INVITE_RATE_PER_USER", default=30)
INVITE_RATE_PER_USER_WINDOW = env.int("INVITE_RATE_PER_USER_WINDOW", default=3600)
# Slug availability check rate limit, enforced in apps.workspaces.views.check_slug.
SLUG_CHECK_RATE = env.int("SLUG_CHECK_RATE", default=60)
SLUG_CHECK_RATE_WINDOW = env.int("SLUG_CHECK_RATE_WINDOW", default=60)
LINK_CODE_LENGTH = env.int("LINK_CODE_LENGTH", default=7)
BLOCKED_LINK_DOMAINS = env.list("BLOCKED_LINK_DOMAINS", default=[])
LINK_RATE_PER_USER = env.int("LINK_RATE_PER_USER", default=30)
LINK_RATE_PER_USER_WINDOW = env.int("LINK_RATE_PER_USER_WINDOW", default=60)
LINK_RATE_PER_WORKSPACE = env.int("LINK_RATE_PER_WORKSPACE", default=300)
LINK_RATE_PER_WORKSPACE_WINDOW = env.int("LINK_RATE_PER_WORKSPACE_WINDOW", default=3600)
# Short-code availability check rate limit: N checks per user per window seconds.
LINK_CODE_CHECK_RATE = env.int("LINK_CODE_CHECK_RATE", default=60)
LINK_CODE_CHECK_RATE_WINDOW = env.int("LINK_CODE_CHECK_RATE_WINDOW", default=60)
LINK_METADATA_TIMEOUT = env.float("LINK_METADATA_TIMEOUT", default=5.0)
LINK_METADATA_MAX_BYTES = env.int("LINK_METADATA_MAX_BYTES", default=2 * 1024 * 1024)
# Overall wall-clock budget for a metadata fetch, across every redirect hop.
LINK_METADATA_TOTAL_TIMEOUT = env.float("LINK_METADATA_TOTAL_TIMEOUT", default=10.0)
# Maximum redirect hops a metadata fetch will follow before giving up.
LINK_METADATA_MAX_REDIRECTS = env.int("LINK_METADATA_MAX_REDIRECTS", default=3)
# Budget for resolving a single host, counted against LINK_METADATA_TOTAL_TIMEOUT.
LINK_METADATA_DNS_TIMEOUT = env.float("LINK_METADATA_DNS_TIMEOUT", default=2.0)
# Metadata lookup rate limits, separate from the outbound fetch limits above: cap how
# often the dashboard may trigger a synchronous fetch at all, per user and per
# workspace.
LINK_METADATA_RATE = env.int("LINK_METADATA_RATE", default=20)
LINK_METADATA_RATE_WINDOW = env.int("LINK_METADATA_RATE_WINDOW", default=60)
LINK_METADATA_RATE_PER_WORKSPACE = env.int("LINK_METADATA_RATE_PER_WORKSPACE", default=60)
LINK_METADATA_RATE_PER_WORKSPACE_WINDOW = env.int(
    "LINK_METADATA_RATE_PER_WORKSPACE_WINDOW", default=60
)
REDIRECT_CACHE_TTL = env.int("REDIRECT_CACHE_TTL", default=3600)
REDIRECT_MISS_TTL = env.int("REDIRECT_MISS_TTL", default=60)
# Per-IP rate limit on the redirect path, enforced in apps.redirects.middleware before
# a code is resolved.
REDIRECT_RATE_PER_IP = env.int("REDIRECT_RATE_PER_IP", default=20)
REDIRECT_RATE_PER_IP_WINDOW = env.int("REDIRECT_RATE_PER_IP_WINDOW", default=1)
DEEP_LINK_FALLBACK_MS = env.int("DEEP_LINK_FALLBACK_MS", default=1500)
# How long ClickEvent rows are kept before the retention purge task (owned by the
# analytics issue) deletes them.
CLICK_EVENT_RETENTION_DAYS = env.int("CLICK_EVENT_RETENTION_DAYS", default=90)
# How many rows the nightly purge_click_events task deletes per batch, so purging a
# large backlog never holds one long-running DELETE.
ANALYTICS_PURGE_BATCH_SIZE = env.int("ANALYTICS_PURGE_BATCH_SIZE", default=5000)
# The largest `limit` apps.analytics.queries.breakdown/leaderboard/recent_clicks will
# honor, so a dashboard request can never turn into an unbounded query.
ANALYTICS_QUERY_MAX_LIMIT = env.int("ANALYTICS_QUERY_MAX_LIMIT", default=100)
# Path to a GeoLite2 City .mmdb file. Optional: leave empty (the default) to run
# without geographic resolution, which is the case for a fresh self-hosted install
# until an operator downloads a database and sets this (see docs/self-hosting.md).
GEOIP_PATH = env("GEOIP_PATH", default="")

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
    # CSP has to run before RedirectMiddleware: its process_request is what makes the
    # nonce a rendered redirect page uses available, and since RedirectMiddleware can
    # return a response without ever calling further down the chain, CSP's
    # process_response is the only place that response still passes through on its way
    # out, which is what actually attaches the Content-Security-Policy header. It does
    # no session, database or authentication work, so the hot path stays as cheap as
    # the constraint intends.
    "django.middleware.csp.ContentSecurityPolicyMiddleware",
    # Ordering is the point: short-code paths are claimed here, before session, CSRF,
    # authentication or messages middleware ever run, so a click never pays for any of
    # that work.
    "apps.redirects.middleware.RedirectMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
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
                "apps.workspaces.context_processors.workspace",
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


def cache_from_url(url):
    """Translate a CACHE_URL into a Django CACHES entry, forcing the built-in Redis client."""
    scheme = url.split("://", 1)[0]
    cfg = environ.Env.cache_url_config(url)
    if scheme in ("redis", "rediss"):
        cfg["BACKEND"] = "django.core.cache.backends.redis.RedisCache"
    cfg["KEY_PREFIX"] = "short"
    return cfg


# Redis is shared and ACL-scoped to the "short:*" key space.
CACHES = {"default": cache_from_url(env("CACHE_URL", default="locmemcache://"))}

TASKS = {
    "default": {
        "BACKEND": env("TASKS_BACKEND", default="django.tasks.backends.immediate.ImmediateBackend"),
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


def _mailer_from_url(url):
    """Translate an EMAIL_URL into a Django 6 MAILERS entry."""
    cfg = environ.Env.email_url_config(url)
    options = {}
    for setting, option in (
        ("EMAIL_HOST", "host"),
        ("EMAIL_PORT", "port"),
        ("EMAIL_HOST_USER", "username"),
        ("EMAIL_HOST_PASSWORD", "password"),
        ("EMAIL_USE_TLS", "use_tls"),
        ("EMAIL_USE_SSL", "use_ssl"),
        ("EMAIL_FILE_PATH", "file_path"),
    ):
        if setting in cfg and cfg[setting] not in (None, ""):
            options[option] = cfg[setting]
    return {"BACKEND": cfg["EMAIL_BACKEND"], "OPTIONS": options}


MAILERS = {"default": _mailer_from_url(env("EMAIL_URL", default="consolemail://"))}
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
