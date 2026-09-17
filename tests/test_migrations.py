from io import StringIO

import pytest
from django.core.management import call_command


@pytest.mark.django_db
def test_no_missing_migrations():
    out = StringIO()
    call_command("makemigrations", "--check", "--dry-run", stdout=out)
    assert "No changes detected" in out.getvalue()


def test_every_app_is_installed():
    from django.apps import apps

    for label in ["core", "accounts", "workspaces", "links", "redirects", "analytics", "api"]:
        assert apps.is_installed(f"apps.{label}")
