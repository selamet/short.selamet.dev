from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from apps.core import ratelimit

from . import services
from .forms import DeleteForm, InviteForm, RoleForm, TransferForm, WorkspaceForm
from .models import Invitation, Membership, Role
from .permissions import matrix_rows, require_role


@login_required
def post_login(request):
    """Route a signed-in user to their workspace, or to onboarding when they have none."""
    membership = request.user.memberships.select_related("workspace").order_by("created_at").first()
    if membership is None:
        return redirect("workspaces:create")
    return redirect("workspaces:dashboard", slug=membership.workspace.slug)


@login_required
@require_GET
def index(request):
    return render(request, "workspaces/index.html")


@login_required
@require_http_methods(["GET", "POST"])
def create(request):
    form = WorkspaceForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            workspace = services.create_workspace(
                request.user,
                name=form.cleaned_data["name"],
                slug=form.cleaned_data["slug"],
                timezone=form.cleaned_data["timezone"],
            )
        except ValidationError as error:
            form.add_error("slug", error.messages[0])
        else:
            return redirect("workspaces:dashboard", slug=workspace.slug)
    return render(request, "workspaces/create.html", {"form": form})


@login_required
@require_GET
def check_slug(request):
    allowed = ratelimit.hit(
        "slug-check",
        str(request.user.pk),
        limit=settings.SLUG_CHECK_RATE,
        window=settings.SLUG_CHECK_RATE_WINDOW,
    )
    if not allowed:
        context = {"state": "invalid", "message": "Too many checks. Slow down."}
        return render(request, "workspaces/partials/slug_check.html", context, status=429)
    try:
        slug = services.validate_slug(request.GET.get("slug", ""))
    except ValidationError as error:
        context = {"state": "invalid", "message": error.messages[0]}
    else:
        available = services.slug_is_available(slug)
        context = {
            "state": "available" if available else "taken",
            "slug": slug,
            "message": "available" if available else "This slug is already taken.",
        }
    return render(request, "workspaces/partials/slug_check.html", context)


@require_role()
@require_GET
def dashboard(request, slug):
    return render(request, "workspaces/dashboard.html")


@login_required
@require_http_methods(["GET", "POST"])
def invitation_accept(request, token):
    try:
        invitation = services.get_pending_invitation(token)
    except services.InvalidInvitation:
        return render(request, "workspaces/invitation_invalid.html", status=410)
    if request.user.email.lower() != invitation.email.lower():
        return render(
            request, "workspaces/invitation_mismatch.html", {"invitation": invitation}, status=403
        )
    if request.method == "POST":
        try:
            membership = services.accept_invitation(request.user, token)
        except services.InvalidInvitation:
            return render(request, "workspaces/invitation_invalid.html", status=410)
        except services.InvitationEmailMismatch:
            return render(
                request,
                "workspaces/invitation_mismatch.html",
                {"invitation": invitation},
                status=403,
            )
        messages.success(request, f"You joined {membership.workspace.name}.")
        return redirect("workspaces:dashboard", slug=membership.workspace.slug)
    return render(
        request, "workspaces/invitation_accept.html", {"invitation": invitation, "token": token}
    )


@login_required
@require_POST
def invitation_decline(request, token):
    try:
        invitation = services.get_pending_invitation(token)
    except services.InvalidInvitation:
        return render(request, "workspaces/invitation_invalid.html", status=410)
    if request.user.email.lower() != invitation.email.lower():
        return render(
            request, "workspaces/invitation_mismatch.html", {"invitation": invitation}, status=403
        )
    try:
        services.decline_invitation(request.user, token)
    except services.InvalidInvitation:
        return render(request, "workspaces/invitation_invalid.html", status=410)
    except services.InvitationEmailMismatch:
        return render(
            request, "workspaces/invitation_mismatch.html", {"invitation": invitation}, status=403
        )
    return redirect("workspaces:index")


@require_role(Role.OWNER, Role.ADMIN)
@require_http_methods(["GET", "POST"])
def settings_general(request, slug):
    workspace = request.workspace
    initial = {"name": workspace.name, "slug": workspace.slug, "timezone": workspace.timezone}
    form = WorkspaceForm(request.POST or None, initial=initial, instance=workspace)
    if request.method == "POST" and form.is_valid():
        try:
            services.update_workspace(request.membership, **form.cleaned_data)
        except ValidationError as error:
            form.add_error("slug", error.messages[0])
        else:
            messages.success(request, "Saved.")
            return redirect("workspaces:settings_general", slug=workspace.slug)
    return render(request, "workspaces/settings/general.html", {"form": form, "section": "general"})


def _members_context(request, form=None):
    return {
        "section": "members",
        "form": form or InviteForm(),
        "members": request.workspace.memberships.select_related("user").order_by("created_at"),
        "invitations": request.workspace.invitations.filter(
            accepted_at__isnull=True, expires_at__gt=timezone.now()
        ),
        "matrix_rows": matrix_rows(),
    }


@require_role(Role.OWNER, Role.ADMIN)
@require_http_methods(["GET", "POST"])
def settings_members(request, slug):
    form = InviteForm(request.POST or None)
    is_hx = request.headers.get("HX-Request")
    if request.method == "POST" and form.is_valid():
        try:
            services.invite(
                request.membership, form.cleaned_data["email"], form.cleaned_data["role"]
            )
        except services.InvalidOperation as error:
            form.add_error("email", str(error))
        else:
            if is_hx:
                return render(
                    request,
                    "workspaces/settings/partials/invite_response.html",
                    _members_context(request),
                )
            messages.success(request, "Invitation sent.")
            return redirect("workspaces:settings_members", slug=slug)
    if request.method == "POST" and is_hx:
        return render(
            request, "workspaces/settings/partials/invite_form.html", {"form": form}, status=422
        )
    return render(request, "workspaces/settings/members.html", _members_context(request, form))


@require_role(Role.OWNER, Role.ADMIN)
@require_POST
def member_role(request, slug, pk):
    target = get_object_or_404(
        Membership.objects.select_related("user"), pk=pk, workspace=request.workspace
    )
    form = RoleForm(request.POST)
    if not form.is_valid():
        return HttpResponseBadRequest("invalid role")
    try:
        services.change_role(request.membership, target, form.cleaned_data["role"])
    except services.InvalidOperation as error:
        if request.headers.get("HX-Request"):
            return render(
                request, "workspaces/settings/partials/member_row.html", {"m": target}, status=422
            )
        return HttpResponseBadRequest(str(error))
    if request.headers.get("HX-Request"):
        return render(request, "workspaces/settings/partials/member_row.html", {"m": target})
    return redirect("workspaces:settings_members", slug=slug)


@require_role(Role.OWNER, Role.ADMIN)
@require_GET
def member_remove_confirm(request, slug, pk):
    target = get_object_or_404(
        Membership.objects.select_related("user"), pk=pk, workspace=request.workspace
    )
    context = {
        "title": "Remove member?",
        "body": f"{target.user.get_short_name()} will immediately lose access to "
        f"{request.workspace.name}.",
        "action": reverse("workspaces:member_remove", args=[slug, pk]),
        "target": f"#member-{pk}",
        "confirm_label": "Remove",
    }
    return render(request, "partials/confirm.html", context)


@require_role(Role.OWNER, Role.ADMIN)
@require_POST
def member_remove(request, slug, pk):
    target = get_object_or_404(
        Membership.objects.select_related("user"), pk=pk, workspace=request.workspace
    )
    try:
        services.remove_member(request.membership, target)
    except services.InvalidOperation as error:
        if request.headers.get("HX-Request"):
            return render(
                request, "workspaces/settings/partials/member_row.html", {"m": target}, status=422
            )
        return HttpResponseBadRequest(str(error))
    if request.headers.get("HX-Request"):
        return render(request, "workspaces/settings/partials/removed.html")
    return redirect("workspaces:settings_members", slug=slug)


@require_role(Role.OWNER, Role.ADMIN)
@require_GET
def invitation_revoke_confirm(request, slug, pk):
    invitation = get_object_or_404(Invitation, pk=pk, workspace=request.workspace)
    context = {
        "title": "Revoke invitation?",
        "body": f"{invitation.email} will no longer be able to accept this invitation.",
        "action": reverse("workspaces:invitation_revoke", args=[slug, pk]),
        "target": f"#invitation-{pk}",
        "confirm_label": "Revoke",
    }
    return render(request, "partials/confirm.html", context)


@require_role(Role.OWNER, Role.ADMIN)
@require_POST
def invitation_revoke(request, slug, pk):
    invitation = get_object_or_404(Invitation, pk=pk, workspace=request.workspace)
    services.revoke_invitation(request.membership, invitation)
    if request.headers.get("HX-Request"):
        return render(request, "workspaces/settings/partials/removed.html")
    return redirect("workspaces:settings_members", slug=slug)


@require_role(Role.OWNER)
@require_GET
def settings_danger(request, slug):
    candidates = request.workspace.memberships.exclude(pk=request.membership.pk).select_related(
        "user"
    )
    return render(
        request,
        "workspaces/settings/danger.html",
        {"section": "danger", "candidates": candidates, "form": DeleteForm()},
    )


@require_role(Role.OWNER)
@require_POST
def transfer(request, slug):
    form = TransferForm(request.POST)
    if not form.is_valid():
        return HttpResponseBadRequest("choose a member")
    target = get_object_or_404(
        Membership, pk=form.cleaned_data["membership"], workspace=request.workspace
    )
    try:
        services.transfer_ownership(request.membership, target)
    except services.InvalidOperation as error:
        candidates = request.workspace.memberships.exclude(pk=request.membership.pk).select_related(
            "user"
        )
        return render(
            request,
            "workspaces/settings/danger.html",
            {
                "section": "danger",
                "candidates": candidates,
                "form": DeleteForm(),
                "transfer_error": str(error),
            },
        )
    messages.success(request, f"{target.user.email} is now the owner.")
    return redirect("workspaces:settings_general", slug=slug)


@require_role(Role.OWNER)
@require_POST
def delete(request, slug):
    form = DeleteForm(request.POST)
    if form.is_valid():
        try:
            services.delete_workspace(request.membership, form.cleaned_data["confirm_slug"])
        except services.InvalidOperation as error:
            form.add_error("confirm_slug", str(error))
        else:
            messages.success(request, "Workspace deleted.")
            return redirect("workspaces:index")
    candidates = request.workspace.memberships.exclude(pk=request.membership.pk).select_related(
        "user"
    )
    return render(
        request,
        "workspaces/settings/danger.html",
        {"section": "danger", "candidates": candidates, "form": form},
    )
