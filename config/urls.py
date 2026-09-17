from django.conf import settings
from django.contrib import admin
from django.urls import include, path

from apps.core import views as core_views

urlpatterns = [
    path(f"{settings.ADMIN_URL_PATH}/", admin.site.urls),
    path("auth/", include("apps.accounts.urls")),
    path("w/", include("apps.workspaces.urls")),
    path("", core_views.home, name="home"),
    path("health/", core_views.health, name="health"),
]
