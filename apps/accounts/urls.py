from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("verify/<str:token>/", views.verify, name="verify"),
]
