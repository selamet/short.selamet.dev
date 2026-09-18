from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from apps.core import ratelimit
from apps.workspaces.permissions import require_role

from . import codes as code_utils
from . import services, utm
from .forms import LinkForm, target_rows
from .models import Link

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


@require_role()
@require_http_methods(["GET", "POST"])
def create(request, slug):
    form = LinkForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        editable = {
            key: form.cleaned_data[key]
            for key in services.EDITABLE_FIELDS
            if key != "destination_url"
        }
        try:
            services.create_link(
                request.membership,
                destination_url=form.cleaned_data["destination_url"],
                code=form.cleaned_data["code"],
                tags=form.tag_names(),
                targets=target_rows(request.POST),
                **editable,
                expires_at=form.cleaned_data["expires_at"],
                max_clicks=form.cleaned_data["max_clicks"],
            )
        except ValidationError as error:
            form.add_error(None, error.messages[0])
        except services.InvalidOperation as error:
            form.add_error(None, str(error))
        else:
            return redirect("links:list", slug=slug)
    return render(request, "links/form.html", _form_context(request, form))


@require_role()
@require_http_methods(["GET", "POST"])
def edit(request, slug, code):
    link = get_object_or_404(Link, code__iexact=code, workspace=request.workspace)
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
        editable = {
            key: form.cleaned_data[key]
            for key in services.EDITABLE_FIELDS
            if key != "destination_url"
        }
        try:
            services.update_link(
                request.membership,
                link,
                destination_url=form.cleaned_data["destination_url"],
                code=form.cleaned_data["code"] or link.code,
                tags=form.tag_names(),
                targets=target_rows(request.POST),
                **editable,
                expires_at=form.cleaned_data["expires_at"],
                max_clicks=form.cleaned_data["max_clicks"],
            )
        except ValidationError as error:
            form.add_error(None, error.messages[0])
        except services.InvalidOperation as error:
            form.add_error(None, str(error))
        else:
            return redirect("links:list", slug=slug)
    return render(request, "links/form.html", _form_context(request, form, link))


@require_role()
@require_GET
def code_check(request, slug):
    raw = request.GET.get("code", "")
    if not raw:
        return render(request, "links/partials/code_check.html", {"state": "empty"})
    if not ratelimit.hit("link-code-check", str(request.user.pk), 60, 60):
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
    from .tasks import extract_metadata

    try:
        data = extract_metadata(request.POST.get("destination_url", ""))
    except ValidationError as error:
        return render(
            request, "links/partials/metadata.html", {"error": error.messages[0]}, status=422
        )
    except Exception:
        return render(
            request,
            "links/partials/metadata.html",
            {"error": "Could not reach that page. You can still save the link."},
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
    # Placeholder until Task 4 lands the full list view with filters and pagination;
    # create/edit redirect here so it must resolve, even though it renders a stub for now.
    return render(request, "links/list.html", {})
