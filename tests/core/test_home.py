import pytest


@pytest.mark.django_db
def test_home_renders_base_template(client):
    response = client.get("/")
    assert response.status_code == 200
    body = response.content.decode()
    assert 'data-theme="system"' in body
    assert "short" in body
    assert "Content-Security-Policy" in response.headers
    assert "nonce-" in response.headers["Content-Security-Policy"]
