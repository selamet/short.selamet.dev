from django.conf import settings
from django.urls import path
from django.contrib import admin

urlpatterns = [
    path(f"{settings.ADMIN_URL_PATH}/", admin.site.urls),
]
