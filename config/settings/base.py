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
