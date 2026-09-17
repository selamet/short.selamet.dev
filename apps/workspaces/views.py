from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from . import services
from .forms import WorkspaceForm
from .permissions import require_role


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
        workspace = services.create_workspace(
            request.user,
            name=form.cleaned_data["name"],
            slug=form.cleaned_data["slug"],
            timezone=form.cleaned_data["timezone"],
        )
        return redirect("workspaces:dashboard", slug=workspace.slug)
    return render(request, "workspaces/create.html", {"form": form})


@login_required
@require_GET
def check_slug(request):
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
    if request.method == "POST":
        membership = services.accept_invitation(request.user, token)
        messages.success(request, f"You joined {membership.workspace.name}.")
        return redirect("workspaces:dashboard", slug=membership.workspace.slug)
    return render(
        request, "workspaces/invitation_accept.html", {"invitation": invitation, "token": token}
    )


@login_required
@require_POST
def invitation_decline(request, token):
    try:
        services.decline_invitation(token)
    except services.InvalidInvitation:
        return render(request, "workspaces/invitation_invalid.html", status=410)
    return redirect("workspaces:index")
