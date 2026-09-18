from django.core.cache import cache

from apps.links import services as link_services
from apps.redirects import cache as redirect_cache


def test_payload_round_trip_is_json_safe(link):
    payload = redirect_cache.payload_from_link(link)
    redirect_cache.set_payload(link.code, payload)
    assert redirect_cache.get_payload(link.code) == payload
    assert payload["destination_url"] == link.destination_url
    assert payload["status"] == link.status
    assert payload["targets"] == {}


def test_payload_carries_targets_and_utm(membership, link):
    link_services.update_link(
        membership,
        link,
        utm_source="instagram",
        utm_medium="bio",
        targets=[
            {
                "platform": "ios",
                "url": "",
                "app_url": "instagram://x",
                "fallback_url": "https://m.example.com",
            },
        ],
    )
    payload = redirect_cache.payload_from_link(link)
    assert payload["utm"]["utm_source"] == "instagram"
    assert payload["targets"]["ios"]["app_url"] == "instagram://x"


def test_miss_sentinel_and_invalidate(db):
    redirect_cache.set_miss("nope")
    assert redirect_cache.get_payload("nope") == redirect_cache.MISS
    redirect_cache.invalidate("nope")
    assert redirect_cache.get_payload("nope") is None


def test_get_payload_survives_a_broken_cache(link, monkeypatch, caplog):
    def boom(*args, **kwargs):
        raise RuntimeError("cache down")

    monkeypatch.setattr(cache, "get", boom)
    assert redirect_cache.get_payload(link.code) is None
    assert "cache unavailable" in caplog.text
