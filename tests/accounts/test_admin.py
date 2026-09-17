import pytest
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.accounts.admin import MagicLinkAdmin
from apps.accounts.models import MagicLink

User = get_user_model()


@pytest.fixture
def superuser_client(client, db):
    superuser = User.objects.create_superuser(email="admin@example.com", password="x")
    client.force_login(superuser)
    return client


@pytest.mark.django_db
def test_admin_add_page_renders(superuser_client):
    response = superuser_client.get(reverse("admin:accounts_user_add"))
    assert response.status_code == 200


@pytest.mark.django_db
def test_admin_change_page_renders(superuser_client):
    user = User.objects.create_user(email="member@example.com")
    response = superuser_client.get(reverse("admin:accounts_user_change", args=[user.pk]))
    assert response.status_code == 200


@pytest.mark.django_db
def test_admin_can_create_user_without_a_password(superuser_client):
    response = superuser_client.post(
        reverse("admin:accounts_user_add"),
        {"email": "new@example.com"},
    )
    assert response.status_code == 302
    created = User.objects.get(email="new@example.com")
    assert created.has_usable_password() is False


def test_magic_link_admin_disallows_delete():
    magic_link_admin = MagicLinkAdmin(MagicLink, admin.site)
    assert magic_link_admin.has_delete_permission(None) is False
