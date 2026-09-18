import logging

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from apps.core import ratelimit
from apps.workspaces.permissions import require_role

from . import codes as code_utils
from . import services, utm
from .forms import LinkForm, target_rows
from .models import Link, Tag

logger = logging.getLogger(__name__)

CARD_PLATFORMS = {"whatsapp": "WhatsApp", "x": "X", "linkedin": "LinkedIn", "slack": "Slack"}


def _form_context(request, form, link=None):
    return {
        "form": form,
        "link": link,
        "presets": utm.UTM_PRESETS,
        "platforms": CARD_PLATFORMS,
        "routing_enabled": bool(request.POST.get("routing_enabled"))
        or (link.is_routed if link else False),
        "targets": {t.platform: t for t in link.targets.all()} if link else {},
    }


def _save_link(request, form, link=None):
    """Create or update, mapping service errors onto the form. Returns the link or None."""
    editable = {
        key: form.cleaned_data[key] for key in services.EDITABLE_FIELDS if key != "destination_url"
    }
    kwargs = {
        "destination_url": form.cleaned_data["destination_url"],
        "tags": form.tag_names(),
        "targets": target_rows(request.POST),
        **editable,
        "expires_at": form.cleaned_data["expires_at"],
        "max_clicks": form.cleaned_data["max_clicks"],
    }
    try:
        if link is None:
            return services.create_link(
                request.membership, code=form.cleaned_data["code"], **kwargs
            )
        return services.update_link(
            request.membership, link, code=form.cleaned_data["code"] or link.code, **kwargs
        )
    except ValidationError as error:
        form.add_error(None, error.messages[0])
    except services.InvalidOperation as error:
        form.add_error(None, str(error))
    return None


@require_role()
@require_http_methods(["GET", "POST"])
def create(request, slug):
    form = LinkForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        if _save_link(request, form) is not None:
            return redirect("links:list", slug=slug)
    return render(request, "links/form.html", _form_context(request, form))


@require_role()
@require_http_methods(["GET", "POST"])
def edit(request, slug, code):
    link = get_object_or_404(
        Link, code=code_utils.normalize_code(code), workspace=request.workspace
    )
    initial = {
        "destination_url": link.destination_url,
        "code": link.code,
        "note": link.note,
        "tags": ", ".join(link.tags.values_list("name", flat=True)),
        "og_title": link.og_title,
        "og_description": link.og_description,
        "og_image_url": link.og_image_url,
        "expires_at": link.expires_at,
        "max_clicks": link.max_clicks,
        **{key: getattr(link, key) for key in services.UTM_FIELDS},
    }
    form = LinkForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        if _save_link(request, form, link) is not None:
            return redirect("links:list", slug=slug)
    return render(request, "links/form.html", _form_context(request, form, link))


@require_role()
@require_GET
def code_check(request, slug):
    raw = request.GET.get("code", "")
    if not raw:
        return render(request, "links/partials/code_check.html", {"state": "empty"})
    if not ratelimit.hit(
        "link-code-check",
        str(request.user.pk),
        settings.LINK_CODE_CHECK_RATE,
        settings.LINK_CODE_CHECK_RATE_WINDOW,
    ):
        return render(
            request,
            "links/partials/code_check.html",
            {"state": "invalid", "message": "Too many checks. Slow down."},
            status=429,
        )
    try:
        code = code_utils.validate_code(raw)
    except ValidationError as error:
        return render(
            request,
            "links/partials/code_check.html",
            {"state": "invalid", "message": error.messages[0]},
        )
    available = services.code_available(code)
    return render(
        request,
        "links/partials/code_check.html",
        {
            "state": "available" if available else "taken",
            "code": code,
            "message": "is available" if available else "is already taken.",
        },
    )


@require_role()
@require_POST
def metadata(request, slug):
    user_ok = ratelimit.hit(
        "link-metadata-user",
        str(request.user.pk),
        settings.LINK_METADATA_RATE,
        settings.LINK_METADATA_RATE_WINDOW,
    )
    workspace_ok = ratelimit.hit(
        "link-metadata-workspace",
        str(request.workspace.pk),
        settings.LINK_METADATA_RATE_PER_WORKSPACE,
        settings.LINK_METADATA_RATE_PER_WORKSPACE_WINDOW,
    )
    if not (user_ok and workspace_ok):
        return render(
            request,
            "links/partials/metadata.html",
            {"error": "Too many lookups. Try again in a moment."},
            status=429,
        )
    from .tasks import extract_metadata

    try:
        data = extract_metadata(request.POST.get("destination_url", ""))
    except Exception:
        # The failure reason (validation, DNS, connection, timeout, non-HTML, ...)
        # stays in the log only: the response must not tell a caller which kind of
        # address probing failed, or the fragment becomes a private-network oracle.
        logger.info(
            "metadata lookup failed workspace=%s user=%s",
            request.workspace.pk,
            request.user.pk,
            exc_info=True,
        )
        return render(
            request,
            "links/partials/metadata.html",
            {"error": "Could not read that page. You can still save the link."},
            status=422,
        )
    return render(request, "links/partials/metadata.html", data)


@require_role()
@require_POST
def utm_preset(request, slug):
    params = utm.apply_preset(
        request.POST.get("preset", ""), campaign=request.POST.get("utm_campaign", "")
    )
    values = {key: params.get(key, request.POST.get(key, "")) for key in services.UTM_FIELDS}
    final_url = utm.merge_utm(request.POST.get("destination_url", ""), values)
    context = {"values": values, "final_url": final_url}
    return render(request, "links/partials/utm_fields.html", context)


@require_role()
@require_POST
def routing(request, slug):
    values = {key: value for key, value in request.POST.items() if key.startswith("target_")}
    return render(
        request,
        "links/partials/routing.html",
        {"routing_enabled": bool(request.POST.get("routing_enabled")), "values": values},
    )


@require_role()
@require_POST
def card_preview(request, slug):
    platform = request.POST.get("platform", "whatsapp")
    return render(
        request,
        "links/partials/card_preview.html",
        {
            "platform": platform,
            "platform_label": CARD_PLATFORMS.get(platform, "WhatsApp"),
            "platforms": CARD_PLATFORMS,
            "og_title": request.POST.get("og_title", ""),
            "og_description": request.POST.get("og_description", ""),
            "og_image_url": request.POST.get("og_image_url", ""),
            "destination_url": request.POST.get("destination_url", ""),
        },
    )


@require_role()
@require_GET
def link_list(request, slug):
    query = (
        Link.objects.filter(workspace=request.workspace)
        .prefetch_related("tags", "targets")
        .order_by("-created_at")
    )
    status = request.GET.get("status", Link.Status.ACTIVE)
    if status in Link.Status.values:
        query = query.filter(status=status)
    tag = request.GET.get("tag", "")
    if tag:
        query = query.filter(tags__name__iexact=tag)
    search = request.GET.get("q", "").strip()
    if search:
        query = query.filter(
            Q(code__icontains=search)
            | Q(destination_url__icontains=search)
            | Q(title__icontains=search)
        )
    page = Paginator(query, 25).get_page(request.GET.get("page"))
    context = {
        "page": page,
        "status": status,
        "tag": tag,
        "q": search,
        "statuses": Link.Status.choices,
        "tags": Tag.objects.filter(workspace=request.workspace),
        "has_any": Link.objects.filter(workspace=request.workspace).exists(),
    }
    template = (
        "links/partials/rows.html" if request.headers.get("HX-Request") else "links/list.html"
    )
    return render(request, template, context)


@require_role()
@require_GET
def archive_confirm(request, slug, code):
    link = get_object_or_404(
        Link, code=code_utils.normalize_code(code), workspace=request.workspace
    )
    return render(
        request,
        "partials/confirm.html",
        {
            "title": "Archive this link?",
            "body": f"{services.short_url(link)} stops appearing in the list. "
            f"Existing clicks are kept and it can be restored.",
            "action": reverse("links:archive", args=[slug, link.code]),
            "target": f"#link-{link.pk}",
            "confirm_label": "Archive",
        },
    )


@require_role()
@require_POST
def archive(request, slug, code):
    link = get_object_or_404(
        Link, code=code_utils.normalize_code(code), workspace=request.workspace
    )
    services.archive_link(request.membership, link)
    if request.headers.get("HX-Request"):
        return render(request, "links/partials/row.html", {"link": link})
    return redirect("links:list", slug=slug)


@require_role()
@require_POST
def restore(request, slug, code):
    link = get_object_or_404(
        Link, code=code_utils.normalize_code(code), workspace=request.workspace
    )
    services.restore_link(request.membership, link)
    if request.headers.get("HX-Request"):
        return render(request, "links/partials/row.html", {"link": link})
    return redirect("links:list", slug=slug)
