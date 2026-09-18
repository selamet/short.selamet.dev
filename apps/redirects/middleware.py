"""Claim short-code paths before the rest of the middleware stack runs.

A click should not cost a session lookup, a CSRF token or an authentication query, so
this sits directly after SecurityMiddleware and returns the response itself. Anything
that is not a single path segment, or that starts with a path the app owns, falls
through to the normal URL resolver.
"""

from django.conf import settings

from . import views

RESERVED_PREFIXES = ("auth", "w", "health", "static", "media", "api")


class RedirectMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        code = self._code_for(request.path)
        if code is None:
            return self.get_response(request)
        if code.endswith("+"):
            return views.preview(request, code[:-1])
        return views.redirect_view(request, code)

    def _code_for(self, path):
        if not path.startswith("/"):
            return None
        trimmed = path[1:].rstrip("/")
        if not trimmed or "/" in trimmed:
            return None
        first = trimmed.split("+")[0]
        if first in RESERVED_PREFIXES or first == settings.ADMIN_URL_PATH:
            return None
        return trimmed
