from django.db import models


class ClickEvent(models.Model):
    """One redirect served. Raw addresses are never stored, only a daily-salted hash.

    `country` and `city` are deliberately left blank by `record_click`: geographic
    resolution needs a GeoLite2 database, and that setup belongs to the analytics issue
    that owns it, not to this one.
    """

    link = models.ForeignKey("links.Link", on_delete=models.CASCADE, related_name="clicks")
    # Denormalized from link.workspace by the task, not the redirect path: it saves
    # every workspace-scoped analytics query a join back through links.Link, and adding
    # it now costs nothing because this table is still empty.
    workspace = models.ForeignKey(
        "workspaces.Workspace", on_delete=models.CASCADE, related_name="clicks"
    )
    occurred_at = models.DateTimeField(db_index=True)
    ip_hash = models.CharField(max_length=64, blank=True)
    country = models.CharField(max_length=2, blank=True)
    city = models.CharField(max_length=80, blank=True)
    device_type = models.CharField(max_length=20, blank=True)
    os = models.CharField(max_length=40, blank=True)
    browser = models.CharField(max_length=60, blank=True)
    referrer_host = models.CharField(max_length=255, blank=True)
    referrer_url = models.CharField(max_length=1024, blank=True)
    utm_source = models.CharField(max_length=100, blank=True)
    utm_medium = models.CharField(max_length=100, blank=True)
    utm_campaign = models.CharField(max_length=100, blank=True)
    utm_content = models.CharField(max_length=100, blank=True)
    utm_term = models.CharField(max_length=100, blank=True)
    target_platform = models.CharField(max_length=10, blank=True)
    is_bot = models.BooleanField(default=False)
    user_agent = models.CharField(max_length=256, blank=True)

    class Meta:
        ordering = ["-occurred_at"]
        indexes = [
            models.Index(fields=["link", "-occurred_at"]),
            models.Index(fields=["workspace", "occurred_at"]),
        ]

    def __str__(self):
        return f"click {self.link_id} @ {self.occurred_at:%Y-%m-%d %H:%M}"
