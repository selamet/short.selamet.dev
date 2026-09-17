from unittest import mock

import pytest


@pytest.mark.django_db
def test_health_ok(client):
    response = client.get("/health/")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok", "cache": "ok"}


@pytest.mark.django_db
def test_health_reports_cache_failure(client):
    with mock.patch("apps.core.views.cache.set", side_effect=RuntimeError("down")):
        response = client.get("/health/")
    assert response.status_code == 503
    assert response.json()["cache"] == "error"
    assert response.json()["status"] == "degraded"
