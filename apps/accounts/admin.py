from django import forms
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import User


class UserCreationForm(forms.ModelForm):
    """Minimal add-user form: auth is magic-link only, so there is no password to collect."""

    class Meta:
        model = User
        fields = ("email",)

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_unusable_password()
        if commit:
            user.save()
        return user


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    add_form = UserCreationForm
    ordering = ("email",)
    list_display = ("email", "display_name", "is_staff", "is_active", "date_joined")
    search_fields = ("email", "display_name")
    fieldsets = (
        (None, {"fields": ("email",)}),
        ("Profile", {"fields": ("display_name", "theme")}),
        (
            "Permissions",
            {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")},
        ),
        ("Dates", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = ((None, {"fields": ("email",)}),)
