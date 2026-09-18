from django.db import models


class Dimension(models.TextChoices):
    COUNTRY = "country", "Country"
    CITY = "city", "City"
    REFERRER = "referrer", "Referrer"
    DEVICE = "device", "Device"
    OS = "os", "Operating system"
    BROWSER = "browser", "Browser"
    UTM_SOURCE = "utm_source", "UTM source"
    UTM_MEDIUM = "utm_medium", "UTM medium"
    UTM_CAMPAIGN = "utm_campaign", "UTM campaign"
    TARGET_PLATFORM = "target_platform", "Target platform"


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


class DailyLinkStat(models.Model):
    """One row per link per day. The dashboard reads these, never the raw events."""

    link = models.ForeignKey("links.Link", on_delete=models.CASCADE, related_name="daily_stats")
    workspace = models.ForeignKey(
        "workspaces.Workspace", on_delete=models.CASCADE, related_name="daily_stats"
    )
    date = models.DateField()
    clicks = models.PositiveIntegerField(default=0)
    unique_clicks = models.PositiveIntegerField(default=0)
    bot_clicks = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-date"]
        constraints = [
            models.UniqueConstraint(fields=["link", "date"], name="analytics_daily_stat_unique")
        ]
        indexes = [models.Index(fields=["workspace", "-date"])]

    def __str__(self):
        return f"stats {self.link_id} @ {self.date}"


class DailyLinkBreakdown(models.Model):
    """One row per link, day, dimension and value."""

    link = models.ForeignKey(
        "links.Link", on_delete=models.CASCADE, related_name="daily_breakdowns"
    )
    workspace = models.ForeignKey(
        "workspaces.Workspace", on_delete=models.CASCADE, related_name="daily_breakdowns"
    )
    date = models.DateField()
    dimension = models.CharField(max_length=20, choices=Dimension.choices)
    value = models.CharField(max_length=255)
    clicks = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-clicks"]
        constraints = [
            models.UniqueConstraint(
                fields=["link", "date", "dimension", "value"],
                name="analytics_daily_breakdown_unique",
            )
        ]
        indexes = [models.Index(fields=["workspace", "date", "dimension"])]

    def __str__(self):
        return f"breakdown {self.link_id} @ {self.date} {self.dimension}={self.value}"


class DailyClickIdentity(models.Model):
    """One row per link, day and visitor identity (a hash of ip_hash + user_agent).

    Exists solely so "is this click unique today" is an atomic INSERT against this
    table's own unique constraint, rather than a read-then-decide query that two
    concurrent workers could both pass at once (see apps.analytics.rollups
    ._claim_identity). Purged together with the raw ClickEvent rows it is derived
    from; it carries no information a rebuild cannot regenerate.
    """

    link = models.ForeignKey(
        "links.Link", on_delete=models.CASCADE, related_name="daily_identities"
    )
    workspace = models.ForeignKey(
        "workspaces.Workspace", on_delete=models.CASCADE, related_name="daily_identities"
    )
    date = models.DateField()
    identity = models.CharField(max_length=64)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["link", "date", "identity"], name="analytics_daily_identity_unique"
            )
        ]
        indexes = [models.Index(fields=["workspace", "date"])]

    def __str__(self):
        return f"identity {self.link_id} @ {self.date} {self.identity[:8]}"
