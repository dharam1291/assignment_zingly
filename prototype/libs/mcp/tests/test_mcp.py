import asyncio

from zingly_core import IdentityLevel, TenantContext
from zingly_mcp import Conflict, DeferredCommits, McpConfig, ReservationTools, build_registry
from zingly_mcp.tools import idempotency_key


class Guard:
    def check(self, tool, level):
        class D:
            allowed = tool != "rebook" or level >= IdentityLevel.VERIFIED
            reason = "needs verified"
        return D()


class Admission:
    def __init__(self, allow=True):
        self.allow = allow
        self.calls = []

    async def acquire(self, lane, wait_s=None):
        self.calls.append(lane)
        return self.allow


class Breaker:
    def allow(self): return True
    def record_success(self): pass
    def record_failure(self): pass


class Cache:
    """Minimal CachePort double: dict, no expiry."""
    def __init__(self):
        self.d = {}

    async def get_or_load(self, ctx, key, loader, ttl_s=None):
        k = ctx.key(key)
        if k in self.d:
            return L(self.d[k], "fresh")
        try:
            self.d[k] = await loader()
            return L(self.d[k], "origin")
        except Exception as e:
            return L(None, "miss", type(e).__name__)

    def peek(self, ctx, key):
        k = ctx.key(key)
        return L(self.d[k], "stale") if k in self.d else L(None, "miss")

    def put(self, ctx, key, value, ttl_s=None):
        self.d[ctx.key(key)] = value


class L:
    def __init__(self, value, source, error=None):
        self.value, self.source, self.error, self.as_of = value, source, error, 1.0
        self.found = source != "miss"


class Backend:
    def __init__(self):
        self.calls = 0

    async def flight(self, f):
        self.calls += 1
        return {"flight": f, "status": "CANCELLED", "origin": "LHR", "destination": "BOS"}

    async def booking(self, ref):
        self.calls += 1
        return {"ref": ref, "flight": "AT123"}

    async def rebook(self, ref, src, dst, key):
        self.calls += 1
        if dst == "FULL":
            raise Conflict("no seats")
        return {"status": "CONFIRMED", "new_flight": dst}


CTX = TenantContext("atlantica", "conv-1")


def make(allow=True, **cfg):
    backend, adm = Backend(), Admission(allow)
    tools = ReservationTools(McpConfig(**cfg), backend, adm, Cache(), Breaker(), DeferredCommits())
    return build_registry(tools, Guard()), backend, adm, tools


def test_guard_runs_before_any_backend_call():
    reg, backend, *_ = make()
    res = asyncio.run(reg.call(CTX, "rebook", {"booking_ref": "ABC123", "from_flight": "AT123",
                                               "to_flight": "AT127"}, IdentityLevel.LIKELY))
    assert res.status == "denied" and backend.calls == 0


def test_shared_reads_use_saved_copy_after_first_load():
    reg, backend, adm, _ = make()
    for _ in range(3):
        res = asyncio.run(reg.call(CTX, "get_flight_status", {"flight": "at123"}, IdentityLevel.UNKNOWN))
    assert res.status == "ok" and res.source == "saved_copy"
    assert backend.calls == 1 and adm.calls == ["P3"]


def test_booking_falls_back_to_saved_copy_when_lane_is_full():
    reg, backend, adm, tools = make(allow=False)
    tools.cache.put(CTX, "booking:ABC123", {"ref": "ABC123", "flight": "AT123"})
    res = asyncio.run(reg.call(CTX, "get_booking", {"booking_ref": "abc123"}, IdentityLevel.UNKNOWN))
    assert (res.status, res.source, res.detail) == ("stale", "saved_copy", "LaneFull")
    assert backend.calls == 0


def test_rebook_defers_when_p0_is_full_and_key_ignores_call_id():
    reg, backend, adm, tools = make(allow=False)
    args = {"booking_ref": "ABC123", "from_flight": "AT123", "to_flight": "AT127"}
    res = asyncio.run(reg.call(CTX, "rebook", args, IdentityLevel.VERIFIED))
    again = asyncio.run(reg.call(TenantContext("atlantica", "conv-2"), "rebook", args, IdentityLevel.VERIFIED))
    assert res.status == again.status == "deferred"
    assert len(tools.deferred.pending()) == 1  # same key, so one pending commit
    assert res.data["idempotency_key"] == idempotency_key("atlantica", "ABC123", "AT123", "AT127")
    assert idempotency_key("nordica", "ABC123", "AT123", "AT127") != res.data["idempotency_key"]


def test_protection_off_goes_straight_to_pss():
    reg, backend, adm, _ = make(protection_enabled=False)
    for _ in range(3):
        asyncio.run(reg.call(CTX, "get_flight_status", {"flight": "AT123"}, IdentityLevel.UNKNOWN))
    assert backend.calls == 3 and adm.calls == []
