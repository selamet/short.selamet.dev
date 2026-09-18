from datetime import UTC, date, datetime

from apps.core.privacy import daily_salt, ensure_daily_salt, hash_ip, salt_timeout


def test_hash_ip_is_stable_within_a_day_and_never_the_raw_ip():
    first = hash_ip("203.0.113.9")
    assert first == hash_ip("203.0.113.9")
    assert len(first) == 64
    assert "203.0.113.9" not in first


def test_hash_ip_of_empty_is_empty():
    assert hash_ip("") == ""


def test_daily_salt_differs_per_day():
    assert daily_salt(date(2026, 1, 1)) != daily_salt(date(2026, 1, 2))


def test_ensure_daily_salt_creates_one_when_none_exists():
    day = date(2026, 5, 5)
    assert ensure_daily_salt(day) == daily_salt(day)


def test_ensure_daily_salt_never_replaces_one_already_in_use():
    day = date(2026, 5, 6)
    existing = daily_salt(day)
    ensure_daily_salt(day)
    assert daily_salt(day) == existing


def test_salt_timeout_for_today_is_at_most_25_hours():
    midnight = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)
    assert salt_timeout(midnight) <= 25 * 60 * 60


def test_salt_timeout_shrinks_toward_end_of_day():
    midnight = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)
    late_evening = datetime(2026, 1, 1, 23, 0, 0, tzinfo=UTC)
    assert salt_timeout(late_evening) < salt_timeout(midnight)
