import logging

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.tasks import task
from django.template.loader import render_to_string

from . import services
from .models import Invitation

logger = logging.getLogger(__name__)


@task
def send_invitation(invitation_id, raw_token):
    try:
        invitation = Invitation.objects.select_related("workspace", "invited_by").get(
            pk=invitation_id
        )
    except Invitation.DoesNotExist:
        logger.warning("invitation task skipped: invitation_id=%s no longer exists", invitation_id)
        return
    inviter = (
        invitation.invited_by.get_short_name() if invitation.invited_by else settings.SITE_NAME
    )
    context = {
        "url": services.invitation_url(raw_token),
        "site_name": settings.SITE_NAME,
        "short_domain": settings.SHORT_DOMAIN,
        "workspace": invitation.workspace,
        "inviter": inviter,
        "role": invitation.get_role_display(),
        "ttl_days": settings.INVITATION_TTL_DAYS,
    }
    message = EmailMultiAlternatives(
        subject=f"{inviter} invited you to {invitation.workspace.name} on {settings.SITE_NAME}",
        body=render_to_string("workspaces/email/invitation.txt", context),
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[invitation.email],
        headers={"Auto-Submitted": "auto-generated"},
    )
    message.attach_alternative(
        render_to_string("workspaces/email/invitation.html", context), "text/html"
    )
    message.send()
