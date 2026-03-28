import time

from request_limits import LimitWindow, _normalize_actor_hint, _register_hit, _hits


def test_register_hit_allows_within_limit():
    key = "test_allow"
    _hits.pop(key, None)
    window = LimitWindow(max_requests=5, window_seconds=60)
    result = _register_hit(key, window)
    assert result is None


def test_register_hit_blocks_over_limit():
    key = "test_block"
    _hits.pop(key, None)
    window = LimitWindow(max_requests=2, window_seconds=60)
    _register_hit(key, window)
    _register_hit(key, window)
    result = _register_hit(key, window)
    assert result is not None
    assert result > 0


def test_register_hit_resets_after_window():
    key = "test_reset"
    _hits.pop(key, None)
    window = LimitWindow(max_requests=1, window_seconds=1)
    _register_hit(key, window)
    time.sleep(1.1)
    result = _register_hit(key, window)
    assert result is None


def test_normalize_actor_hint_consistent():
    h1 = _normalize_actor_hint("user@example.com")
    h2 = _normalize_actor_hint("user@example.com")
    assert h1 == h2
    assert h1 is not None


def test_normalize_actor_hint_none():
    assert _normalize_actor_hint(None) is None
    assert _normalize_actor_hint("") is None
