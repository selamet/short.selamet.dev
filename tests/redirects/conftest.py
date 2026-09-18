import pytest

from apps.accounts.models import User
from apps.links import destinations
from apps.links import services as link_services
from apps.workspaces import services as workspace_services
from apps.workspaces.models import Membership, Role

IOS_UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15"
ANDROID_UA = "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36"
DESKTOP_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"


@pytest.fixture(autouse=True)
def _fake_dns(monkeypatch):
    """The service layer resolves every destination before saving it; stub the
    resolver so these tests never perform a real DNS lookup (see tests/links for the
    same pattern)."""
    monkeypatch.setattr(destinations, "resolve_host", lambda host, timeout: ["93.184.216.34"])


@pytest.fixture
def owner(db):
    return User.objects.create_user(email="owner@example.com")


@pytest.fixture
def membership(owner):
    workspace = workspace_services.create_workspace(owner, name="Acme", slug="acme")
    return Membership.objects.get(workspace=workspace, user=owner, role=Role.OWNER)


@pytest.fixture
def link(membership):
    return link_services.create_link(
        membership, destination_url="https://example.com/p", code="spring-drop"
    )
