from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("login/", views.login, name="login"),
    path("check-inbox/", views.check_inbox, name="check_inbox"),
    path("resend/", views.resend, name="resend"),
    path("verify/<str:token>/", views.verify, name="verify"),
    path("logout/", views.logout, name="logout"),
]
