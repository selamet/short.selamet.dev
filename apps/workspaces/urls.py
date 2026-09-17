from django.urls import path

from . import views

app_name = "workspaces"

urlpatterns = [
    path("", views.index, name="index"),
    path("new/", views.create, name="create"),
    path("check-slug/", views.check_slug, name="check_slug"),
    path("invitations/<str:token>/", views.invitation_accept, name="invitation_accept"),
    path("invitations/<str:token>/decline/", views.invitation_decline, name="invitation_decline"),
    path("<slug:slug>/settings/", views.settings_general, name="settings_general"),
    path("<slug:slug>/settings/members/", views.settings_members, name="settings_members"),
    path("<slug:slug>/settings/members/<int:pk>/role/", views.member_role, name="member_role"),
    path(
        "<slug:slug>/settings/members/<int:pk>/remove/confirm/",
        views.member_remove_confirm,
        name="member_remove_confirm",
    ),
    path(
        "<slug:slug>/settings/members/<int:pk>/remove/",
        views.member_remove,
        name="member_remove",
    ),
    path(
        "<slug:slug>/settings/invitations/<int:pk>/revoke/confirm/",
        views.invitation_revoke_confirm,
        name="invitation_revoke_confirm",
    ),
    path(
        "<slug:slug>/settings/invitations/<int:pk>/revoke/",
        views.invitation_revoke,
        name="invitation_revoke",
    ),
    path("<slug:slug>/settings/danger/", views.settings_danger, name="settings_danger"),
    path("<slug:slug>/settings/transfer/", views.transfer, name="transfer"),
    path("<slug:slug>/settings/delete/", views.delete, name="delete"),
    path("<slug:slug>/", views.dashboard, name="dashboard"),
]
