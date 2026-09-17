from datetime import date

from apps.core.privacy import daily_salt, hash_ip


def test_hash_ip_is_stable_within_a_day_and_never_the_raw_ip():
    first = hash_ip("203.0.113.9")
    assert first == hash_ip("203.0.113.9")
    assert len(first) == 64
    assert "203.0.113.9" not in first


def test_hash_ip_of_empty_is_empty():
    assert hash_ip("") == ""


def test_daily_salt_differs_per_day():
    assert daily_salt(date(2026, 1, 1)) != daily_salt(date(2026, 1, 2))
