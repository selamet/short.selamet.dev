from django.contrib import admin

from .models import ClickEvent


@admin.register(ClickEvent)
class ClickEventAdmin(admin.ModelAdmin):
    """Read-only: click events are written by `record_click`, never by hand."""

    list_display = ("link", "occurred_at", "country", "device_type", "is_bot")
    list_select_related = ("link",)
    list_filter = ("is_bot", "device_type", "country")
    search_fields = ("link__code",)
    date_hierarchy = "occurred_at"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
