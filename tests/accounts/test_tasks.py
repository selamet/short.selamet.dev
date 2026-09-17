import logging
import re
import smtplib

import pytest
from django.core import mail
from django.core.mail import EmailMultiAlternatives
from django.tasks import TaskResultStatus

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


@pytest.mark.django_db
def test_send_magic_link_marks_message_as_auto_generated():
    user = User.objects.create_user(email="ada@example.com")

    send_magic_link.enqueue(user.pk)

    message = mail.outbox[0]
    assert message.extra_headers.get("Auto-Submitted") == "auto-generated"


@pytest.mark.django_db
def test_deleted_user_logs_warning_and_sends_nothing(caplog):
    with caplog.at_level(logging.WARNING, logger="apps.accounts.tasks"):
        result = send_magic_link.enqueue(999999)

    assert result.status == TaskResultStatus.SUCCESSFUL
    assert len(mail.outbox) == 0
    assert any("no longer exists" in record.message for record in caplog.records)
    assert not any(record.exc_info for record in caplog.records)


@pytest.mark.django_db
def test_failed_send_is_logged_at_error(monkeypatch, caplog):
    def raise_smtp_exception(self, *args, **kwargs):
        raise smtplib.SMTPException("mail server unavailable")

    monkeypatch.setattr(EmailMultiAlternatives, "send", raise_smtp_exception)
    user = User.objects.create_user(email="ada@example.com")

    with caplog.at_level(logging.ERROR, logger="apps.accounts.tasks"):
        result = send_magic_link.enqueue(user.pk)

    assert result.status == TaskResultStatus.FAILED
    error_records = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert error_records
    assert "send_magic_link" in error_records[0].message
    assert "SMTPException" in caplog.text
