from django.urls import path

from . import views

app_name = "workspaces"

urlpatterns = [
    path("", views.index, name="index"),
    path("new/", views.create, name="create"),
    path("check-slug/", views.check_slug, name="check_slug"),
    path("invitations/<str:token>/", views.invitation_accept, name="invitation_accept"),
    path("invitations/<str:token>/decline/", views.invitation_decline, name="invitation_decline"),
    path("<slug:slug>/", views.dashboard, name="dashboard"),
]
