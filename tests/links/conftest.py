import pytest

from apps.accounts.models import User
from apps.workspaces import services as workspace_services
from apps.workspaces.models import Membership, Role


@pytest.fixture
def owner(db):
    return User.objects.create_user(email="owner@example.com")


@pytest.fixture
def workspace(owner):
    return workspace_services.create_workspace(owner, name="Acme Social", slug="acme-social")


@pytest.fixture
def owner_membership(workspace, owner):
    return Membership.objects.get(workspace=workspace, user=owner)


@pytest.fixture
def other_workspace(db):
    user = User.objects.create_user(email="other@example.com")
    return workspace_services.create_workspace(user, name="Other", slug="other")


@pytest.fixture
def other_membership(other_workspace):
    return Membership.objects.get(workspace=other_workspace, role=Role.OWNER)
