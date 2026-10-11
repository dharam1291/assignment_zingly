import asyncio

from zingly_core import IdentityClaims, IdentityLevel, TenantContext
from zingly_mcp import Conflict, NotFound, DeferredCommits, McpConfig, ReservationTools, build_registry
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
        if ref != "ABC123":
            raise NotFound(ref)
        return {"ref": ref, "flight": "AT123", "surname": "Smith"}

    async def rebook(self, ref, src, dst, key):
        self.calls += 1
        if dst == "FULL":
            raise Conflict("no seats")
        return {"status": "CONFIRMED", "new_flight": dst}


CTX = TenantContext("atlantica", "conv-1")


def who(level=IdentityLevel.UNKNOWN, ref=None):
    return IdentityClaims("atlantica", "conv-1", level, ref, 0)


def make(allow=True, **cfg):
    backend, adm = Backend(), Admission(allow)
    tools = ReservationTools(McpConfig(**cfg), backend, adm, Cache(), Breaker(), DeferredCommits())
    return build_registry(tools, Guard()), backend, adm, tools


def test_guard_runs_before_any_backend_call():
    reg, backend, *_ = make()
    res = asyncio.run(reg.call(CTX, "rebook", {"booking_ref": "ABC123", "from_flight": "AT123",
                                               "to_flight": "AT127"}, who(IdentityLevel.LIKELY)))
    assert res.status == "denied" and backend.calls == 0


def test_shared_reads_use_saved_copy_after_first_load():
    reg, backend, adm, _ = make()
    for _ in range(3):
        res = asyncio.run(reg.call(CTX, "get_flight_status", {"flight": "at123"}, who()))
    assert res.status == "ok" and res.source == "saved_copy"
    assert backend.calls == 1 and adm.calls == ["P3"]


def test_booking_falls_back_to_saved_copy_when_lane_is_full():
    reg, backend, adm, tools = make(allow=False)
    tools.cache.put(CTX, "booking:ABC123", {"ref": "ABC123", "flight": "AT123"})
    res = asyncio.run(reg.call(CTX, "get_booking", {"booking_ref": "abc123"}, who(IdentityLevel.VERIFIED, "ABC123")))
    assert (res.status, res.source, res.detail) == ("stale", "saved_copy", "LaneFull")
    assert backend.calls == 0


def test_rebook_defers_when_p0_is_full_and_key_ignores_call_id():
    reg, backend, adm, tools = make(allow=False)
    args = {"booking_ref": "ABC123", "from_flight": "AT123", "to_flight": "AT127"}
    res = asyncio.run(reg.call(CTX, "rebook", args, who(IdentityLevel.VERIFIED, "ABC123")))
    again = asyncio.run(reg.call(TenantContext("atlantica", "conv-2"), "rebook", args, who(IdentityLevel.VERIFIED, "ABC123")))
    assert res.status == again.status == "deferred"
    assert len(tools.deferred.pending()) == 1  # same key, so one pending commit
    assert res.data["idempotency_key"] == idempotency_key("atlantica", "ABC123", "AT123", "AT127")
    assert idempotency_key("nordica", "ABC123", "AT123", "AT127") != res.data["idempotency_key"]


def test_protection_off_goes_straight_to_pss():
    reg, backend, adm, _ = make(protection_enabled=False)
    for _ in range(3):
        asyncio.run(reg.call(CTX, "get_flight_status", {"flight": "AT123"}, who()))
    assert backend.calls == 3 and adm.calls == []


def test_booking_scoped_tools_only_act_on_the_verified_booking():
    reg, backend, *_ = make()
    args = {"booking_ref": "ABC123", "from_flight": "AT123", "to_flight": "AT127"}
    other = asyncio.run(reg.call(CTX, "rebook", args, who(IdentityLevel.VERIFIED, "ZZZ999")))
    assert other.status == "denied" and backend.calls == 0
    own = asyncio.run(reg.call(CTX, "rebook", args, who(IdentityLevel.VERIFIED, "ABC123")))
    assert own.status == "ok"


def test_verify_booking_never_leaks_and_never_says_which_part_was_wrong():
    reg, *_ = make()
    ok = asyncio.run(reg.call(CTX, "verify_booking", {"booking_ref": "abc 123", "surname": "smith"}, who()))
    wrong_name = asyncio.run(reg.call(CTX, "verify_booking", {"booking_ref": "ABC123", "surname": "Jones"}, who()))
    missing = asyncio.run(reg.call(CTX, "verify_booking", {"booking_ref": "ZZZ999", "surname": "Smith"}, who()))
    assert ok.data["match"] and ok.data["booking"]["ref"] == "ABC123"
    assert wrong_name.data == missing.data == {"match": False}
    assert wrong_name.status == missing.status == "ok"


def test_timed_out_write_with_unreadable_state_is_reconciled_not_guessed():
    from zingly_mcp import BackendUnavailable

    class Down(Backend):
        async def rebook(self, *a):
            raise BackendUnavailable("timeout")

        async def booking(self, ref):
            raise BackendUnavailable("timeout")

    tools = ReservationTools(McpConfig(), Down(), Admission(), Cache(), Breaker(), DeferredCommits())
    reg = build_registry(tools, Guard())
    args = {"booking_ref": "ABC123", "from_flight": "AT123", "to_flight": "AT127"}
    res = asyncio.run(reg.call(CTX, "rebook", args, who(IdentityLevel.VERIFIED, "ABC123")))
    assert res.status == "unavailable" and "outcome unknown" in res.detail
    assert res.data["reconciliation"] == "queued" and len(tools.deferred.pending()) == 1


def test_verify_booking_is_throttled_per_booking_whoever_asks():
    reg, *_ = make(verify_max_failures=3)
    for n in range(3):  # three different "callers" guessing surnames for the same booking
        ctx = TenantContext("atlantica", f"conv-{n}")
        asyncio.run(reg.call(ctx, "verify_booking", {"booking_ref": "ABC123", "surname": f"Guess{n}"}, who()))
    blocked = asyncio.run(reg.call(CTX, "verify_booking", {"booking_ref": "ABC123", "surname": "Smith"}, who()))
    assert blocked.status == "denied" and "too many" in blocked.detail
    other = asyncio.run(reg.call(TenantContext("nordica"), "verify_booking",
                                 {"booking_ref": "ABC123", "surname": "Smith"}, who()))
    assert other.status != "denied"  # throttle is per tenant
