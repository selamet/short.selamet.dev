from apps.core import ratelimit


def test_hit_allows_up_to_limit_then_blocks():
    assert ratelimit.hit("t", "a", limit=2, window=60) is True
    assert ratelimit.hit("t", "a", limit=2, window=60) is True
    assert ratelimit.hit("t", "a", limit=2, window=60) is False


def test_hit_isolates_identities_and_scopes():
    assert ratelimit.hit("t", "a", limit=1, window=60) is True
    assert ratelimit.hit("t", "b", limit=1, window=60) is True
    assert ratelimit.hit("other", "a", limit=1, window=60) is True
