import pytest

from apps.links import services as link_services
from apps.redirects import cache as redirect_cache
from apps.redirects import resolver
from tests.redirects.conftest import DESKTOP_UA

# Invalidation is deliberately deferred to transaction.on_commit (see apps/links/services.py)
# so a rolled-back write never clears a good cache entry. Django's own test isolation wraps
# each test in a transaction that is rolled back rather than committed, so on_commit hooks
# registered during a plain `db`-fixture test never fire on their own (documented Django
# behaviour: https://docs.djangoproject.com/en/stable/topics/db/transactions/#use-in-tests).
# `django_capture_on_commit_callbacks` is pytest-django's supported way to exercise them
# anyway; the calls below that are expected to invalidate the cache are wrapped in it.


@pytest.mark.django_db
def test_updating_the_destination_invalidates_the_cache(
    membership, link, django_capture_on_commit_callbacks
):
    assert resolver.resolve(link.code, DESKTOP_UA).url == "https://example.com/p"
    with django_capture_on_commit_callbacks(execute=True):
        link_services.update_link(membership, link, destination_url="https://example.com/new")
    assert redirect_cache.get_payload(link.code) is None
    assert resolver.resolve(link.code, DESKTOP_UA).url == "https://example.com/new"


@pytest.mark.django_db
def test_changing_the_code_invalidates_both_codes(
    membership, link, django_capture_on_commit_callbacks
):
    old_code = link.code
    resolver.resolve(old_code, DESKTOP_UA)
    with django_capture_on_commit_callbacks(execute=True):
        link_services.update_link(membership, link, code="new-code")
    assert redirect_cache.get_payload(old_code) is None
    assert resolver.resolve(old_code, DESKTOP_UA) is None
    assert resolver.resolve("new-code", DESKTOP_UA) is not None


@pytest.mark.django_db
def test_archiving_and_restoring_invalidate(membership, link, django_capture_on_commit_callbacks):
    resolver.resolve(link.code, DESKTOP_UA)
    with django_capture_on_commit_callbacks(execute=True):
        link_services.archive_link(membership, link)
    assert redirect_cache.get_payload(link.code) is None
    assert resolver.resolve(link.code, DESKTOP_UA).status == "archived"
    with django_capture_on_commit_callbacks(execute=True):
        link_services.restore_link(membership, link)
    assert redirect_cache.get_payload(link.code) is None


@pytest.mark.django_db
def test_a_click_landing_after_an_edit_does_not_resurrect_the_old_payload(
    membership, link, django_capture_on_commit_callbacks
):
    resolver.resolve(link.code, DESKTOP_UA)
    with django_capture_on_commit_callbacks(execute=True):
        link_services.update_link(membership, link, destination_url="https://example.com/new")
    assert redirect_cache.get_payload(link.code) is None
    # A click enqueued just before the edit lands after it; bumping the counter must
    # not bring the invalidated payload back.
    redirect_cache.bump_click_count(link.code, seed=link.click_count)
    assert redirect_cache.get_payload(link.code) is None


@pytest.mark.django_db
def test_changing_targets_or_tags_invalidates(membership, link, django_capture_on_commit_callbacks):
    resolver.resolve(link.code, DESKTOP_UA)
    with django_capture_on_commit_callbacks(execute=True):
        link_services.set_targets(
            membership,
            link,
            [
                {
                    "platform": "ios",
                    "url": "https://m.example.com",
                    "app_url": "",
                    "fallback_url": "",
                }
            ],
        )
    assert redirect_cache.get_payload(link.code) is None
