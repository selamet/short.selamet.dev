"""Claim short-code paths before the rest of the middleware stack runs.

A click should not cost a session lookup, a CSRF token or an authentication query, so
this sits directly after SecurityMiddleware and returns the response itself. Anything
that is not a single path segment, or that starts with a path the app owns, falls
through to the normal URL resolver.

A per-IP rate limit is enforced here too, before a code is ever resolved, so a burst
past the limit is rejected without touching the cache, the database or a template.
"""

from django.conf import settings
from django.http import HttpResponse

from apps.core import ratelimit
from apps.core.http import client_ip
from apps.links import codes as code_utils

from . import views

RESERVED_PREFIXES = ("auth", "w", "health", "static", "media", "api")


class RedirectMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        code = self._code_for(request.path)
        if code is None:
            return self.get_response(request)
        if not ratelimit.hit(
            "redirect",
            client_ip(request),
            settings.REDIRECT_RATE_PER_IP,
            settings.REDIRECT_RATE_PER_IP_WINDOW,
        ):
            # Bare response, no template: rendering is exactly the cost this limit
            # exists to avoid paying on every request in a burst.
            response = HttpResponse(status=429)
            response["Retry-After"] = "1"
            response["Cache-Control"] = "no-store"
            return response
        is_preview = code.endswith("+")
        # Normalized once, here, so the redirect and the preview page agree on the
        # same code: without this, "/%20spring-drop" and "/spring-drop///" resolved to
        # the same link but were treated as different cache entries, and the preview
        # page rendered whatever un-normalized code the visitor typed.
        code = code_utils.normalize_code(code[:-1] if is_preview else code)
        if is_preview:
            return views.preview(request, code)
        return views.redirect_view(request, code)

    def _code_for(self, path):
        if not path.startswith("/"):
            return None
        trimmed = path[1:].rstrip("/")
        if not trimmed or "/" in trimmed:
            return None
        # A single segment with a dot looks like a static file (favicon.ico,
        # robots.txt), never a short code: codes never contain a dot (see
        # codes.CODE_RE). Fall through to the normal URL stack instead of claiming it
        # here and rendering a branded 404 for what is really a missing static asset.
        if "." in trimmed:
            return None
        first = trimmed.split("+")[0]
        if first in RESERVED_PREFIXES or first == settings.ADMIN_URL_PATH:
            return None
        return trimmed
