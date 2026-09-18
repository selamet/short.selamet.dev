"""Intentionally empty.

Single-segment short-code paths (and their `+` preview variant) are claimed by
`RedirectMiddleware` before Django's URL resolver ever runs, so this app has no views
reached through routing. Kept only for structural consistency with the other apps; it
is never included from `config.urls`.
"""

app_name = "redirects"
urlpatterns = []
