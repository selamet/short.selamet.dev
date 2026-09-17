from django.contrib import admin

from .models import Invitation, Membership, Workspace


class MembershipInline(admin.TabularInline):
    model = Membership
    extra = 0
    autocomplete_fields = ("user",)


@admin.register(Workspace)
class WorkspaceAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "timezone", "created_at")
    search_fields = ("name", "slug")
    inlines = [MembershipInline]


@admin.register(Invitation)
class InvitationAdmin(admin.ModelAdmin):
    list_display = ("email", "workspace", "role", "expires_at", "accepted_at")
    list_select_related = ("workspace",)
    readonly_fields = ("token_hash",)
    search_fields = ("email", "workspace__slug")
