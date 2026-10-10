import asyncio

from zingly_core import TenantContext
from zingly_saved_copy import InMemorySavedCopy, SavedCopyConfig

A, B = TenantContext("a"), TenantContext("b")


class Clock:
    now = 0.0

    def __call__(self):
        return self.now


def test_fifty_concurrent_misses_make_one_origin_call():
    store = InMemorySavedCopy()
    calls = 0

    async def loader():
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.05)
        return ["AT127", "AT131"]

    async def run():
        return await asyncio.gather(*(store.get_or_load(A, "alts", loader) for _ in range(50)))

    results = asyncio.run(run())
    assert calls == 1
    assert {r.source for r in results} == {"origin", "coalesced"}
    assert all(r.value == ["AT127", "AT131"] for r in results)
    assert store.stats("a") == {"coalesced": 49, "origin_load": 1}


def test_fresh_hit_then_stale_fallback_when_origin_fails():
    clock = Clock()
    store = InMemorySavedCopy(SavedCopyConfig(default_ttl_s=25), clock=clock)
    store.put(A, "alts", "v1")
    hit = asyncio.run(store.get_or_load(A, "alts", None))
    assert hit.source == "fresh"

    clock.now = 30

    async def failing():
        raise TimeoutError("lane full")

    stale = asyncio.run(store.get_or_load(A, "alts", failing))
    assert (stale.source, stale.value, stale.error) == ("stale", "v1", "TimeoutError")


def test_tenants_are_isolated():
    store = InMemorySavedCopy()
    store.put(A, "booking:ABC123", "atlantica data")
    assert store.peek(B, "booking:ABC123").source == "miss"
