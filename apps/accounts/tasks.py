from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.tasks import task
from django.template.loader import render_to_string

from . import services
from .models import User


@task
def send_magic_link(user_id, ip_hash=""):
    """Create a fresh magic link for the user and email it. The raw token exists only here."""
    user = User.objects.get(pk=user_id)
    raw_token = services.create_magic_link(user, ip_hash=ip_hash)
    context = {
        "url": services.magic_link_url(raw_token),
        "site_name": settings.SITE_NAME,
        "short_domain": settings.SHORT_DOMAIN,
        "ttl_minutes": settings.MAGIC_LINK_TTL_MINUTES,
    }
    message = EmailMultiAlternatives(
        subject=f"Your sign-in link to {settings.SITE_NAME}",
        body=render_to_string("accounts/email/magic_link.txt", context),
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[user.email],
    )
    message.attach_alternative(
        render_to_string("accounts/email/magic_link.html", context), "text/html"
    )
    message.send()
