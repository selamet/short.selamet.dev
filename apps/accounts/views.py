import time

from django.conf import settings
from django.contrib.auth import login as auth_login
from django.contrib.auth import logout as auth_logout
from django.core.cache import cache
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_http_methods, require_POST

from apps.core import ratelimit
from apps.core.http import client_ip
from apps.core.privacy import hash_ip

from . import services
from .forms import LoginForm
from .tasks import send_magic_link

PENDING_EMAIL_SESSION_KEY = "magic_link_email"
LOGIN_NEXT_SESSION_KEY = "login_next"
RATE_LIMIT_MESSAGE = "Too many sign-in links requested. Please wait a few minutes and try again."


def _cooldown_key(email):
    return f"magic-link-cooldown:{email.lower()}"


def _start_cooldown(email):
    seconds = settings.MAGIC_LINK_RESEND_COOLDOWN_SECONDS
    if seconds:
        cache.set(_cooldown_key(email), time.time() + seconds, timeout=seconds)


def _cooldown_remaining(email):
    expires = cache.get(_cooldown_key(email))
    return max(0, int(expires - time.time())) if expires else 0


def _request_magic_link(request, email):
    """Enqueue a link for the email unless a rate limit is hit. Returns the user, or None."""
    ip = client_ip(request)
    allowed_for_email = ratelimit.hit("magic-link-email", email.lower(), limit=3, window=600)
    allowed_for_ip = ratelimit.hit("magic-link-ip", ip, limit=20, window=3600)
    if not (allowed_for_email and allowed_for_ip):
        return None
    user = services.get_or_create_user(email)
    send_magic_link.enqueue(user.pk, ip_hash=hash_ip(ip))
    _start_cooldown(user.email)
    return user


def _safe_next(request, candidate):
    if candidate and url_has_allowed_host_and_scheme(
        candidate, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return candidate
    return ""


@require_http_methods(["GET", "POST"])
def login(request):
    if request.user.is_authenticated:
        return redirect(settings.LOGIN_REDIRECT_URL)
    next_url = _safe_next(request, request.GET.get("next") or request.POST.get("next"))
    form = LoginForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = _request_magic_link(request, form.cleaned_data["email"])
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


def check_inbox(request):
    email = request.session.get(PENDING_EMAIL_SESSION_KEY)
    if not email:
        return redirect("accounts:login")
    return render(
        request,
        "accounts/check_inbox.html",
        {"email": email, "cooldown": _cooldown_remaining(email)},
    )


@require_POST
def resend(request):
    email = request.session.get(PENDING_EMAIL_SESSION_KEY)
    if not email:
        return redirect("accounts:login")
    if _cooldown_remaining(email) == 0:
        _request_magic_link(request, email)
    context = {"email": email, "cooldown": _cooldown_remaining(email)}
    if request.headers.get("HX-Request"):
        return render(request, "accounts/partials/resend.html", context)
    return redirect("accounts:check_inbox")


@require_http_methods(["GET", "POST"])
def verify(request, token):
    if request.method == "GET":
        # Consuming on POST keeps email link scanners (which only GET) from burning the token.
        return render(request, "accounts/verify.html", {"token": token})
    try:
        user = services.consume_magic_link(token)
    except services.InvalidMagicLink:
        return render(request, "accounts/link_expired.html", status=410)
    auth_login(request, user)
    request.session.pop(PENDING_EMAIL_SESSION_KEY, None)
    next_url = request.session.pop(LOGIN_NEXT_SESSION_KEY, "") or settings.LOGIN_REDIRECT_URL
    return redirect(next_url)


@require_POST
def logout(request):
    auth_logout(request)
    return redirect("accounts:login")
