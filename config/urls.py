from django.conf import settings
from django.contrib import admin
from django.urls import include, path

from apps.core import views as core_views

urlpatterns = [
    path(f"{settings.ADMIN_URL_PATH}/", admin.site.urls),
    path("auth/", include("apps.accounts.urls")),
    path("w/<slug:slug>/links/", include("apps.links.urls")),
    path("w/", include("apps.workspaces.urls")),
    path("", core_views.home, name="home"),
    path("health/", core_views.health, name="health"),
]
# Single-segment paths (e.g. /spring-drop, /spring-drop+) are short links: they never
# reach this URLconf because RedirectMiddleware serves them before the resolver runs.
