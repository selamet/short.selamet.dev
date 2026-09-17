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
