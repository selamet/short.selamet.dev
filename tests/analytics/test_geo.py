"""Tests for apps.analytics.geo: optional GeoLite2 lookups.

No test here reads a real GeoLite2 file or reaches the network: every case injects a
fake reader through the module's own lazily-opened cache instead."""

import pytest
from geoip2.errors import AddressNotFoundError

from apps.analytics import geo


class _FakeCountry:
    def __init__(self, iso_code):
        self.iso_code = iso_code


class _FakeCity:
    def __init__(self, name):
        self.name = name


class _FakeResponse:
    def __init__(self, country="US", city="Springfield"):
        self.country = _FakeCountry(country)
        self.city = _FakeCity(city)


class _FakeReader:
    """Stands in for geoip2.database.Reader. Counts how many times it is
    constructed, so a test can assert the real database is opened at most once."""

    instances = 0

    def __init__(self, path):
        type(self).instances += 1
        self.path = path

    def city(self, ip):
        return _FakeResponse()


class _RaisingReader:
    def __init__(self, path):
        pass

    def city(self, ip):
        raise ValueError("corrupt database")


class _MissReader:
    """Stands in for a Reader whose lookup misses: geoip2 puts the looked-up address
    straight into AddressNotFoundError's own message, exactly like the real library
    does, so a test against this proves the address never reaches the logs."""

    def __init__(self, path):
        pass

    def city(self, ip):
        raise AddressNotFoundError(f"The address {ip} is not in the database.")


@pytest.fixture(autouse=True)
def _reset_reader_cache():
    """geo.py caches its Reader at module level (opened once per process, see
    geo._get_reader), so tests must reset that cache before and after each run or
    they would leak state into one another."""
    geo._reader = geo._NOT_LOADED
    yield
    geo._reader = geo._NOT_LOADED


def test_configured_is_false_when_geoip_path_is_empty(settings):
    settings.GEOIP_PATH = ""
    assert geo.configured() is False


def test_lookup_returns_blanks_when_geoip_path_is_empty(settings):
    settings.GEOIP_PATH = ""
    assert geo.lookup("203.0.113.9") == {"country": "", "city": ""}


def test_configured_is_true_when_geoip_path_is_set(settings):
    settings.GEOIP_PATH = "/data/GeoLite2-City.mmdb"
    assert geo.configured() is True


def test_lookup_uses_an_injected_reader(settings, monkeypatch):
    settings.GEOIP_PATH = "/data/GeoLite2-City.mmdb"
    monkeypatch.setattr(geo, "Reader", _FakeReader)
    assert geo.lookup("203.0.113.9") == {"country": "US", "city": "Springfield"}


def test_a_lookup_failure_returns_blanks_and_logs_without_the_address(
    settings, monkeypatch, caplog
):
    settings.GEOIP_PATH = "/data/GeoLite2-City.mmdb"
    monkeypatch.setattr(geo, "Reader", _RaisingReader)
    assert geo.lookup("203.0.113.9") == {"country": "", "city": ""}
    assert "geoip lookup failed" in caplog.text
    assert "203.0.113.9" not in caplog.text


def test_a_miss_returns_blanks_and_logs_nothing_at_all(settings, monkeypatch, caplog):
    # AddressNotFoundError's own message contains the address (see _MissReader); a
    # miss is routine, not an error, so it must produce no log line whatsoever, not
    # merely one with the address scrubbed out.
    settings.GEOIP_PATH = "/data/GeoLite2-City.mmdb"
    monkeypatch.setattr(geo, "Reader", _MissReader)
    with caplog.at_level("WARNING"):
        assert geo.lookup("203.0.113.9") == {"country": "", "city": ""}
    assert caplog.text == ""
    assert "203.0.113.9" not in caplog.text


def test_a_database_that_fails_to_open_returns_blanks_and_logs(settings, monkeypatch, caplog):
    def boom(path):
        raise OSError("no such file")

    settings.GEOIP_PATH = "/data/missing.mmdb"
    monkeypatch.setattr(geo, "Reader", boom)
    assert geo.lookup("203.0.113.9") == {"country": "", "city": ""}
    assert "failed to open" in caplog.text


def test_the_reader_is_opened_once_and_reused(settings, monkeypatch):
    _FakeReader.instances = 0
    settings.GEOIP_PATH = "/data/GeoLite2-City.mmdb"
    monkeypatch.setattr(geo, "Reader", _FakeReader)
    geo.lookup("203.0.113.9")
    geo.lookup("203.0.113.10")
    geo.lookup("203.0.113.11")
    assert _FakeReader.instances == 1
