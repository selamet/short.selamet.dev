import logging

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login as auth_login
from django.contrib.auth import logout as auth_logout
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from apps.core.http import client_ip

from . import services
from .forms import LoginForm

logger = logging.getLogger("apps.accounts.views")

PENDING_EMAIL_SESSION_KEY = "magic_link_email"
LOGIN_NEXT_SESSION_KEY = "login_next"
RATE_LIMIT_MESSAGE = "Too many sign-in links requested. Please wait a few minutes and try again."


def _inbox_context(email, rate_limited=False):
    return {
        "email": email,
        "cooldown": services.cooldown_remaining(email),
        "rate_limited": rate_limited,
        "rate_limit_message": RATE_LIMIT_MESSAGE,
    }


def _safe_next(request, candidate):
    if candidate and url_has_allowed_host_and_scheme(
        candidate, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return candidate
    return ""


@never_cache
@require_http_methods(["GET", "POST"])
def login(request):
    if request.user.is_authenticated:
        return redirect(settings.LOGIN_REDIRECT_URL)
    next_url = _safe_next(request, request.GET.get("next") or request.POST.get("next"))
    form = LoginForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = services.request_magic_link(form.cleaned_data["email"], client_ip(request))
        if user is not None:
            # Store the normalized address so later pages and the cooldown key agree.
            request.session[PENDING_EMAIL_SESSION_KEY] = user.email
            if next_url:
                request.session[LOGIN_NEXT_SESSION_KEY] = next_url
            else:
                request.session.pop(LOGIN_NEXT_SESSION_KEY, None)
            return redirect("accounts:check_inbox")
        form.add_error(None, RATE_LIMIT_MESSAGE)
    return render(request, "accounts/login.html", {"form": form, "next": next_url})


@never_cache
@require_GET
def check_inbox(request):
    email = request.session.get(PENDING_EMAIL_SESSION_KEY)
    if not email:
        return redirect("accounts:login")
    return render(request, "accounts/check_inbox.html", _inbox_context(email))


@require_POST
def resend(request):
    email = request.session.get(PENDING_EMAIL_SESSION_KEY)
    if not email:
        return redirect("accounts:login")
    rate_limited = False
    if services.cooldown_remaining(email) == 0:
        rate_limited = services.request_magic_link(email, client_ip(request)) is None
    context = _inbox_context(email, rate_limited=rate_limited)
    if request.headers.get("HX-Request"):
        return render(request, "accounts/partials/resend.html", context)
    if rate_limited:
        messages.error(request, RATE_LIMIT_MESSAGE)
    return redirect("accounts:check_inbox")


@never_cache
@require_http_methods(["GET", "POST"])
def verify(request, token):
    if request.method == "GET":
        # Consuming on POST keeps email link scanners (which only GET) from burning the token.
        return render(request, "accounts/verify.html", {"token": token})
    try:
        user = services.consume_magic_link(token)
    except services.InvalidMagicLink:
        logger.warning("magic link rejected")
        return render(request, "accounts/link_expired.html", status=410)
    logger.info("magic link sign-in user_id=%s", user.pk)
    auth_login(request, user)
    request.session.pop(PENDING_EMAIL_SESSION_KEY, None)
    next_url = request.session.pop(LOGIN_NEXT_SESSION_KEY, "") or settings.LOGIN_REDIRECT_URL
    return redirect(next_url)


@require_POST
def logout(request):
    auth_logout(request)
    return redirect("accounts:login")
