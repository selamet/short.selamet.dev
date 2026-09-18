import pytest


@pytest.fixture(autouse=True)
def _clear_cache():
    from django.core.cache import cache

    cache.clear()
    yield
    cache.clear()


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """apps.links.tasks._open_stream is the one seam a metadata fetch uses to reach a
    destination over the network (see tests/links/test_tasks.py, which fakes it per
    test). Autouse here, suite-wide, rather than only where it was first needed
    (tests/redirects, for the deferred fetch a destination-changing update can trigger
    via django_capture_on_commit_callbacks): a test anywhere that reaches this seam
    without expecting to should fail loudly and locally, not silently touch the
    network."""

    def _forbidden(client, url, **kwargs):
        raise AssertionError("a test tried to reach the network")

    from apps.links import tasks as link_tasks

    monkeypatch.setattr(link_tasks, "_open_stream", _forbidden)
