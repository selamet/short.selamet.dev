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
