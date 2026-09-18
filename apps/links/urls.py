from django.urls import path

from . import views

app_name = "links"

urlpatterns = [
    path("", views.link_list, name="list"),
    path("new/", views.create, name="create"),
    path("check-code/", views.code_check, name="code_check"),
    path("metadata/", views.metadata, name="metadata"),
    path("utm-preset/", views.utm_preset, name="utm_preset"),
    path("routing/", views.routing, name="routing"),
    path("card-preview/", views.card_preview, name="card_preview"),
    path("<str:code>/edit/", views.edit, name="edit"),
]
