import pytest

from apps.accounts.models import User
from apps.workspaces import services
from apps.workspaces.models import Membership, Role


@pytest.fixture
def owner(db):
    return User.objects.create_user(email="owner@example.com")


@pytest.fixture
def workspace(owner):
    return services.create_workspace(owner, name="Acme Social", slug="acme-social")


@pytest.fixture
def owner_membership(workspace, owner):
    return Membership.objects.get(workspace=workspace, user=owner)


@pytest.fixture
def admin_membership(workspace):
    user = User.objects.create_user(email="admin@example.com")
    return Membership.objects.create(workspace=workspace, user=user, role=Role.ADMIN)


@pytest.fixture
def member_membership(workspace):
    user = User.objects.create_user(email="member@example.com")
    return Membership.objects.create(workspace=workspace, user=user, role=Role.MEMBER)


@pytest.fixture
def outsider(db):
    return User.objects.create_user(email="outsider@example.com")
