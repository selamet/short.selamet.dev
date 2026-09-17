from django.contrib import admin

from .models import Link, LinkTarget, Tag


class LinkTargetInline(admin.TabularInline):
    model = LinkTarget
    extra = 0


@admin.register(Link)
class LinkAdmin(admin.ModelAdmin):
    list_display = ("code", "workspace", "destination_url", "status", "click_count", "created_at")
    list_select_related = ("workspace",)
    list_filter = ("status",)
    search_fields = ("code", "destination_url", "title")
    readonly_fields = ("click_count", "og_fetched_at", "created_at", "updated_at")
    inlines = [LinkTargetInline]


@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    list_display = ("name", "workspace")
    list_select_related = ("workspace",)
    search_fields = ("name",)
