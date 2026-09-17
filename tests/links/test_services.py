import pytest
from django.core.exceptions import ValidationError

from apps.links import services
from apps.links.models import Link, Tag


def test_create_link_generates_a_code_and_defaults(owner_membership, settings):
    settings.SHORT_DOMAIN = "sho.rt"
    link = services.create_link(owner_membership, destination_url="https://example.com/p")
    assert len(link.code) == settings.LINK_CODE_LENGTH
    assert link.status == Link.Status.ACTIVE
    assert link.workspace == owner_membership.workspace
    assert link.created_by == owner_membership.user
    assert services.short_url(link) == f"https://sho.rt/{link.code}"


def test_create_link_accepts_a_custom_code_case_insensitively(owner_membership):
    link = services.create_link(
        owner_membership, destination_url="https://example.com", code="Spring-Drop"
    )
    assert link.code == "spring-drop"
    with pytest.raises(ValidationError):
        services.create_link(
            owner_membership, destination_url="https://example.com", code="SPRING-DROP"
        )


def test_create_link_rejects_reserved_codes_and_bad_destinations(owner_membership):
    with pytest.raises(ValidationError):
        services.create_link(owner_membership, destination_url="https://example.com", code="admin")
    with pytest.raises(ValidationError):
        services.create_link(owner_membership, destination_url="javascript:alert(1)")


def test_create_link_stores_utm_and_tags(owner_membership):
    link = services.create_link(
        owner_membership,
        destination_url="https://example.com",
        utm_source="instagram",
        utm_medium="bio",
        utm_campaign="spring26",
        tags=["campaign", "ig-bio"],
    )
    assert link.utm_source == "instagram"
    assert sorted(link.tags.values_list("name", flat=True)) == ["campaign", "ig-bio"]
    assert Tag.objects.filter(workspace=link.workspace).count() == 2
    again = services.create_link(
        owner_membership, destination_url="https://example.com/2", tags=["Campaign"]
    )
    assert Tag.objects.filter(workspace=link.workspace).count() == 2
    assert again.tags.first().name == "campaign"


def test_set_targets_replaces_rows_and_validates(owner_membership):
    link = services.create_link(owner_membership, destination_url="https://example.com")
    services.set_targets(
        link,
        [
            {
                "platform": "ios",
                "url": "",
                "app_url": "instagram://user?username=acme",
                "fallback_url": "https://m.example.com/ios",
            },
            {
                "platform": "android",
                "url": "https://m.example.com/android",
                "app_url": "",
                "fallback_url": "",
            },
        ],
    )
    assert set(link.targets.values_list("platform", flat=True)) == {"ios", "android"}
    services.set_targets(link, [])
    assert link.targets.count() == 0
    with pytest.raises(ValidationError):
        services.set_targets(
            link, [{"platform": "ios", "url": "", "app_url": "instagram://x", "fallback_url": ""}]
        )
    with pytest.raises(ValidationError):
        services.set_targets(
            link,
            [
                {
                    "platform": "desktop",
                    "url": "javascript:alert(1)",
                    "app_url": "",
                    "fallback_url": "",
                }
            ],
        )


def test_update_link_changes_code_and_keeps_history(owner_membership):
    link = services.create_link(
        owner_membership, destination_url="https://example.com", code="first-code"
    )
    updated = services.update_link(
        owner_membership, link, destination_url="https://example.com/x", code="second-code"
    )
    assert updated.code == "second-code"
    assert Link.objects.count() == 1


def test_archive_and_restore(owner_membership):
    link = services.create_link(owner_membership, destination_url="https://example.com")
    services.archive_link(owner_membership, link)
    link.refresh_from_db()
    assert link.status == Link.Status.ARCHIVED
    services.restore_link(owner_membership, link)
    link.refresh_from_db()
    assert link.status == Link.Status.ACTIVE


def test_services_reject_a_link_from_another_workspace(owner_membership, other_membership):
    link = services.create_link(owner_membership, destination_url="https://example.com")
    with pytest.raises(services.InvalidOperation):
        services.update_link(other_membership, link, destination_url="https://evil.example")
    with pytest.raises(services.InvalidOperation):
        services.archive_link(other_membership, link)


def test_code_available_ignores_archived_links_never(owner_membership):
    link = services.create_link(
        owner_membership, destination_url="https://example.com", code="taken"
    )
    services.archive_link(owner_membership, link)
    assert services.code_available("taken") is False
    assert services.code_available("taken", exclude=link) is True
