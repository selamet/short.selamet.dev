from django.conf import settings
from django.db import models
from django.db.models.functions import Lower


class Tag(models.Model):
    workspace = models.ForeignKey(
        "workspaces.Workspace", on_delete=models.CASCADE, related_name="tags"
    )
    name = models.CharField(max_length=40)
    color = models.CharField(max_length=7, blank=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                "workspace", Lower("name"), name="links_tag_workspace_name_unique"
            )
        ]

    def __str__(self):
        return self.name


class Link(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        DISABLED = "disabled", "Disabled"
        ARCHIVED = "archived", "Archived"

    workspace = models.ForeignKey(
        "workspaces.Workspace", on_delete=models.CASCADE, related_name="links"
    )
    code = models.CharField(max_length=40, unique=True)
    destination_url = models.URLField(max_length=2048)
    title = models.CharField(max_length=200, blank=True)
    favicon_url = models.URLField(max_length=1024, blank=True)
    note = models.TextField(blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)

    utm_source = models.CharField(max_length=100, blank=True)
    utm_medium = models.CharField(max_length=100, blank=True)
    utm_campaign = models.CharField(max_length=100, blank=True)
    utm_content = models.CharField(max_length=100, blank=True)
    utm_term = models.CharField(max_length=100, blank=True)

    og_title = models.CharField(max_length=200, blank=True)
    og_description = models.CharField(max_length=400, blank=True)
    og_image_url = models.URLField(max_length=1024, blank=True)
    og_overridden = models.BooleanField(default=False)
    og_fetched_at = models.DateTimeField(null=True, blank=True)

    expires_at = models.DateTimeField(null=True, blank=True)
    max_clicks = models.PositiveIntegerField(null=True, blank=True)
    click_count = models.PositiveIntegerField(default=0)

    tags = models.ManyToManyField(Tag, blank=True, related_name="links")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["workspace", "-created_at"]),
            models.Index(fields=["workspace", "status"]),
        ]
        constraints = [models.UniqueConstraint(Lower("code"), name="links_link_code_ci_unique")]

    def __str__(self):
        return self.code

    @property
    def is_routed(self):
        return self.targets.exists()


class LinkTarget(models.Model):
    class Platform(models.TextChoices):
        IOS = "ios", "iOS"
        ANDROID = "android", "Android"
        DESKTOP = "desktop", "Desktop"

    link = models.ForeignKey(Link, on_delete=models.CASCADE, related_name="targets")
    platform = models.CharField(max_length=10, choices=Platform.choices)
    url = models.URLField(max_length=2048, blank=True)
    app_url = models.CharField(max_length=2048, blank=True)
    fallback_url = models.URLField(max_length=2048, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["link", "platform"], name="links_target_platform_unique"
            )
        ]

    def __str__(self):
        return f"{self.link_id}:{self.platform}"
