import pytest
from django.contrib.auth import get_user_model

User = get_user_model()


@pytest.mark.django_db
def test_create_user_normalizes_email_and_has_no_usable_password():
    user = User.objects.create_user(email="Ada@Example.COM")
    assert user.email == "Ada@example.com"
    assert user.is_active is True
    assert user.is_staff is False
    assert user.has_usable_password() is False
    assert user.theme == "system"


@pytest.mark.django_db
def test_email_is_unique_case_insensitively():
    User.objects.create_user(email="ada@example.com")
    with pytest.raises(Exception):  # noqa: B017
        User.objects.create_user(email="ADA@example.com")


@pytest.mark.django_db
def test_create_superuser_sets_flags():
    admin = User.objects.create_superuser(email="root@example.com", password="x")
    assert admin.is_staff and admin.is_superuser and admin.has_usable_password()


def test_user_has_no_username_field():
    assert User.USERNAME_FIELD == "email"
    assert not hasattr(User, "username")
