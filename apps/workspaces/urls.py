from django.urls import path

from . import views

app_name = "workspaces"

urlpatterns = [
    path("", views.index, name="index"),
    path("new/", views.create, name="create"),
    path("check-slug/", views.check_slug, name="check_slug"),
    path("<slug:slug>/", views.dashboard, name="dashboard"),
]
