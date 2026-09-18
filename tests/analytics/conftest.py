"""Reuses the membership/link fixtures (and the DNS fake they depend on) from
tests/redirects/conftest.py instead of redefining them for a second app."""

from tests.redirects.conftest import _fake_dns, link, membership, owner  # noqa: F401
