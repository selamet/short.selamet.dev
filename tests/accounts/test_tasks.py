import re

import pytest
from django.core import mail

from apps.accounts import services
from apps.accounts.models import MagicLink, User
from apps.accounts.tasks import send_magic_link


@pytest.mark.django_db
def test_send_magic_link_creates_link_and_emails_both_parts():
    user = User.objects.create_user(email="ada@example.com")

    send_magic_link.enqueue(user.pk, ip_hash="h")

    link = MagicLink.objects.get(user=user)
    assert link.ip_hash == "h"
    assert len(mail.outbox) == 1
    message = mail.outbox[0]
    assert message.to == ["ada@example.com"]
    assert message.subject == "Your sign-in link to short"
    urls = re.findall(r"https://sho\.rt/auth/verify/[A-Za-z0-9_-]+/", message.body)
    assert len(urls) == 1
    raw = urls[0].rsplit("/", 2)[1]
    assert link.token_hash == services.hash_token(raw)
    html, mimetype = message.alternatives[0]
    assert mimetype == "text/html"
    assert urls[0] in html
    assert "<img" not in html
    assert "15 minutes" in message.body and "15 minutes" in html
