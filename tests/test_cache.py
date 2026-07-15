import pytest

from app.cache import Cache


@pytest.fixture
def cache(tmp_path):
    return Cache(tmp_path / "test-cache.db")


def test_get_miss_returns_none(cache):
    assert cache.get("nope", ttl=60) is None


def test_set_then_fresh_get(cache):
    cache.set("k", {"a": 1})
    value, age = cache.get("k", ttl=60)
    assert value == {"a": 1}
    assert age < 5


def test_expired_entry_is_a_miss_but_stale_readable(cache):
    cache.set("k", "old")
    assert cache.get("k", ttl=0) is None
    value, _age = cache.get_stale("k")
    assert value == "old"


def test_fetch_populates_and_reuses(cache):
    calls = []

    def fetch_fn():
        calls.append(1)
        return "fresh"

    value, _ = cache.fetch("k", 60, fetch_fn)
    assert value == "fresh"
    value, _ = cache.fetch("k", 60, fetch_fn)
    assert value == "fresh"
    assert len(calls) == 1


def test_fetch_serves_stale_when_upstream_fails(cache):
    cache.set("k", "stale-but-usable")

    def boom():
        raise RuntimeError("yahoo is down")

    value, age = cache.fetch("k", ttl=0, fetch_fn=boom)
    assert value == "stale-but-usable"
    assert age >= 0


def test_fetch_raises_when_no_stale_fallback(cache):
    def boom():
        raise RuntimeError("yahoo is down")

    with pytest.raises(RuntimeError):
        cache.fetch("k", ttl=60, fetch_fn=boom)
