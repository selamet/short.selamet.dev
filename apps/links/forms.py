from django import forms

from . import codes as code_utils
from . import destinations
from .models import LinkTarget


class LinkForm(forms.Form):
    destination_url = forms.CharField(max_length=2048)
    code = forms.CharField(max_length=40, required=False)
    note = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}))
    tags = forms.CharField(max_length=400, required=False)

    utm_source = forms.CharField(max_length=100, required=False)
    utm_medium = forms.CharField(max_length=100, required=False)
    utm_campaign = forms.CharField(max_length=100, required=False)
    utm_content = forms.CharField(max_length=100, required=False)
    utm_term = forms.CharField(max_length=100, required=False)

    og_title = forms.CharField(max_length=200, required=False)
    og_description = forms.CharField(max_length=400, required=False)
    og_image_url = forms.CharField(max_length=1024, required=False)

    expires_at = forms.DateTimeField(required=False)
    max_clicks = forms.IntegerField(required=False, min_value=1)

    def clean_destination_url(self):
        # Surfaces the destination check as a field error at form-validation time; the
        # service layer re-validates (with DNS) before saving, since DNS can change.
        return destinations.validate_destination(self.cleaned_data.get("destination_url", ""))

    def clean_code(self):
        value = (self.cleaned_data.get("code") or "").strip()
        if not value:
            return ""
        return code_utils.validate_code(value)

    def clean_og_image_url(self):
        # An override image on a private/local address is as unwanted as a
        # destination on one; same rules, no DNS check (this isn't an outbound fetch).
        value = (self.cleaned_data.get("og_image_url") or "").strip()
        if not value:
            return ""
        return destinations.validate_destination(value)

    def tag_names(self):
        raw = self.cleaned_data.get("tags", "")
        return [part.strip() for part in raw.split(",") if part.strip()]


def target_rows(post):
    """Read the three fixed device rows out of the POST, or none when routing is off."""
    if not post.get("routing_enabled"):
        return []
    rows = []
    for platform in LinkTarget.Platform.values:
        rows.append(
            {
                "platform": platform,
                "url": post.get(f"target_{platform}_url", ""),
                "app_url": post.get(f"target_{platform}_app_url", ""),
                "fallback_url": post.get(f"target_{platform}_fallback_url", ""),
            }
        )
    return rows
