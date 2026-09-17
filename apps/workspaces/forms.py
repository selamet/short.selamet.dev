import zoneinfo

from django import forms
from django.core.exceptions import ValidationError

from . import services
from .models import Role

TIMEZONE_CHOICES = [
    (tz, tz) for tz in sorted(zoneinfo.available_timezones()) if "/" in tz or tz == "UTC"
]


class WorkspaceForm(forms.Form):
    name = forms.CharField(max_length=80)
    slug = forms.CharField(max_length=40)
    timezone = forms.ChoiceField(choices=TIMEZONE_CHOICES, initial="UTC")

    def __init__(self, *args, instance=None, **kwargs):
        self.instance = instance
        super().__init__(*args, **kwargs)

    def clean_slug(self):
        slug = services.validate_slug(self.cleaned_data["slug"])
        current = self.instance.slug if self.instance else None
        if slug != current and not services.slug_is_available(slug):
            raise ValidationError("This slug is already taken.")
        return slug


class InviteForm(forms.Form):
    email = forms.EmailField(max_length=254)
    role = forms.ChoiceField(
        choices=[(Role.MEMBER, "Member"), (Role.ADMIN, "Admin")], initial=Role.MEMBER
    )


class RoleForm(forms.Form):
    role = forms.ChoiceField(choices=[(Role.MEMBER, "Member"), (Role.ADMIN, "Admin")])


class TransferForm(forms.Form):
    membership = forms.IntegerField()


class DeleteForm(forms.Form):
    confirm_slug = forms.CharField(max_length=40)
