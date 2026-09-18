"""The redirect hot path.

These are plain functions rather than class-based views, called from the middleware
before the rest of the stack runs. Nothing here writes to the database.
"""

import logging

from django.conf import settings
from django.db import DatabaseError
from django.http import HttpResponseRedirect
from django.shortcuts import render
from django.utils import timezone

from apps.analytics import attribution
from apps.analytics.tasks import record_click
from apps.core.http import client_ip
from apps.core.privacy import hash_ip
from apps.links.models import Link

from . import platforms, resolver

logger = logging.getLogger(__name__)


def _no_store(response):
    response["Cache-Control"] = "no-store"
    return response


def _error_page(request, template, status):
    return _no_store(render(request, template, status=status))


def _record(request, resolution):
    # Split here, not in the task: the production task backend persists its arguments
    # to the database, and the raw referrer (which can carry credentials in its
    # userinfo) and the raw query string must never land there.
    referrer_host, referrer_url = attribution.split_referrer(
        request.META.get("HTTP_REFERER", "")[:1024]
    )
    utm = attribution.utm_from_query_string(request.META.get("QUERY_STRING", "")[:1024])
    try:
        record_click.enqueue(
            resolution.link_id,
            occurred_at=timezone.now().isoformat(),
            # Hashed here, not in the task: the production task backend persists its
            # arguments to the database, and an IP address must never land there raw.
            ip_hash=hash_ip(client_ip(request)),
            user_agent=request.META.get("HTTP_USER_AGENT", "")[:256],
            referrer_host=referrer_host,
            referrer_url=referrer_url,
            target_platform=resolution.platform,
            **utm,
        )
    except Exception:
        # A click we cannot record is worth less than a redirect we fail to serve.
        logger.warning("click was not recorded for link_id=%s", resolution.link_id, exc_info=True)


def redirect_view(request, code):
    user_agent = request.META.get("HTTP_USER_AGENT", "")
    try:
        resolution = resolver.resolve(code, user_agent)
    except DatabaseError:
        logger.exception("database unavailable while resolving %s", code)
        response = _error_page(request, "redirects/errors/unavailable.html", 503)
        response["Retry-After"] = "5"
        return response
    if resolution is None:
        return _error_page(request, "redirects/errors/not_found.html", 404)
    if resolution.status != Link.Status.ACTIVE:
        return _error_page(request, "redirects/errors/disabled.html", 403)
    if resolution.expired:
        return _error_page(request, "redirects/errors/expired.html", 410)
    if platforms.is_crawler(user_agent):
        return _no_store(render(request, "redirects/crawler_card.html", {"resolution": resolution}))
    _record(request, resolution)
    if resolution.app_url:
        return _no_store(
            render(
                request,
                "redirects/deep_link.html",
                {"resolution": resolution, "fallback_ms": settings.DEEP_LINK_FALLBACK_MS},
            )
        )
    return _no_store(HttpResponseRedirect(resolution.url))


def preview(request, code):
    resolution = resolver.resolve(code, request.META.get("HTTP_USER_AGENT", ""))
    if resolution is None:
        return _error_page(request, "redirects/errors/not_found.html", 404)
    if resolution.status != Link.Status.ACTIVE:
        return _error_page(request, "redirects/errors/disabled.html", 403)
    if resolution.expired:
        return _error_page(request, "redirects/errors/expired.html", 410)
    return _no_store(
        render(request, "redirects/preview.html", {"resolution": resolution, "code": code})
    )
