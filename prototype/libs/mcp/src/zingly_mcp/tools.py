"""Reservation tools. Every PSS call goes: breaker -> priority lane -> PSS.

Two read patterns (design §5):
* shared data (flight status, alternatives): saved copy first, single-flight on a miss,
  stale "as of" copy if the lane is full.
* caller-ID hint: saved copy first too (pre-warmed from the passenger list), so it is free.
* booking lookup for verification: live first in lane P1, saved copy (pre-warmed
  passenger list) only as the fallback, labelled "as of".
Writes are never served from the copy: they go live in lane P0, or become a deferred commit.
"""

from __future__ import annotations

import hashlib
from typing import Any, Awaitable, Callable

from zingly_core import TenantContext

from zingly_mcp.backend import BackendError, BackendUnavailable, Conflict, NotFound, PssBackend
from zingly_mcp.config import McpConfig
from zingly_mcp.deferred import DeferredCommits, PendingCommit
from zingly_mcp.ports import AdmissionPort, BreakerPort, CachePort, GuardPort
from zingly_mcp.registry import Tool, ToolRegistry, ToolResult


class LaneFull(Exception):
    pass


class CircuitOpen(Exception):
    pass


def idempotency_key(tenant_id: str, booking_ref: str, from_flight: str, to_flight: str) -> str:
    """Excludes the call id, so a caller who drops and dials back cannot rebook twice (design §8)."""
    raw = "|".join([tenant_id, booking_ref.upper(), from_flight.upper(), to_flight.upper()])
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


class ReservationTools:
    def __init__(self, config: McpConfig, backend: PssBackend, admission: AdmissionPort,
                 cache: CachePort, breaker: BreakerPort, deferred: DeferredCommits):
        self.cfg = config
        self.backend = backend
        self.admission = admission
        self.cache = cache
        self.breaker = breaker
        self.deferred = deferred

    # ---- plumbing -------------------------------------------------------------------
    async def _pss(self, lane: str, call: Callable[[], Awaitable[Any]], wait_s: float | None = None) -> Any:
        if self.cfg.protection_enabled:
            if not self.breaker.allow():
                raise CircuitOpen(lane)
            if not await self.admission.acquire(lane, wait_s):
                raise LaneFull(lane)
        try:
            result = await call()
        except BackendUnavailable:
            self.breaker.record_failure()
            raise
        self.breaker.record_success()
        return result

    @staticmethod
    def _from_lookup(lookup: Any) -> ToolResult:
        if lookup.source == "fresh":
            return ToolResult("ok", lookup.value, "saved_copy", lookup.as_of)
        if lookup.source in ("origin", "coalesced"):
            return ToolResult("ok", lookup.value, "pss" if lookup.source == "origin" else "coalesced")
        if lookup.source == "stale":
            return ToolResult("stale", lookup.value, "saved_copy", lookup.as_of, lookup.error or "")
        if lookup.error == "NotFound":
            return ToolResult("not_found", source="pss")
        return ToolResult("unavailable", source="none", detail=lookup.error or "")

    async def _direct(self, call: Callable[[], Awaitable[Any]]) -> ToolResult:
        try:
            return ToolResult("ok", await call())
        except NotFound:
            return ToolResult("not_found")
        except BackendError as exc:
            return ToolResult("unavailable", source="none", detail=type(exc).__name__)

    async def _shared(self, ctx: TenantContext, key: str, lane: str,
                      call: Callable[[], Awaitable[Any]], ttl: float) -> ToolResult:
        if not self.cfg.protection_enabled:
            return await self._direct(call)
        lookup = await self.cache.get_or_load(ctx, key, lambda: self._pss(lane, call), ttl)
        return self._from_lookup(lookup)

    async def _live_first(self, ctx: TenantContext, key: str, lane: str,
                          call: Callable[[], Awaitable[Any]]) -> ToolResult:
        if not self.cfg.protection_enabled:
            return await self._direct(call)
        try:
            data = await self._pss(lane, call)
        except NotFound:
            return ToolResult("not_found")
        except (LaneFull, CircuitOpen, BackendError) as exc:
            saved = self.cache.peek(ctx, key)
            if saved.found:
                return ToolResult("stale", saved.value, "saved_copy", saved.as_of, type(exc).__name__)
            return ToolResult("unavailable", source="none", detail=type(exc).__name__)
        self.cache.put(ctx, key, data, self.cfg.booking_ttl_s)
        return ToolResult("ok", data)

    # ---- tools ----------------------------------------------------------------------
    async def get_flight_status(self, ctx: TenantContext, args: dict) -> ToolResult:
        flight = args["flight"].upper()
        return await self._shared(ctx, f"flight:{flight}", "P3",
                                  lambda: self.backend.flight(flight), self.cfg.status_ttl_s)

    async def find_bookings_by_phone(self, ctx: TenantContext, args: dict) -> ToolResult:
        # The caller-ID hint should be free: disrupted passengers are in the pre-warmed copy.
        phone = args["phone"]
        return await self._shared(ctx, f"phone:{phone}", "P1",
                                  lambda: self.backend.bookings_by_phone(phone), self.cfg.booking_ttl_s)

    async def get_booking(self, ctx: TenantContext, args: dict) -> ToolResult:
        ref = args["booking_ref"].upper()
        return await self._live_first(ctx, f"booking:{ref}", "P1", lambda: self.backend.booking(ref))

    async def get_alternatives(self, ctx: TenantContext, args: dict) -> ToolResult:
        origin, dest = args["origin"].upper(), args["destination"].upper()
        return await self._shared(ctx, f"alts:{origin}:{dest}", "P2",
                                  lambda: self.backend.alternatives(origin, dest), self.cfg.alternatives_ttl_s)

    async def rebook(self, ctx: TenantContext, args: dict) -> ToolResult:
        ref, src, dst = args["booking_ref"].upper(), args["from_flight"].upper(), args["to_flight"].upper()
        key = idempotency_key(ctx.tenant_id, ref, src, dst)
        try:
            data = await self._pss("P0", lambda: self.backend.rebook(ref, src, dst, key))
        except Conflict as exc:
            return ToolResult("conflict", detail=str(exc))
        except (LaneFull, CircuitOpen) as exc:
            if self.cfg.deferred_commit:
                self.deferred.add(PendingCommit(ctx.tenant_id, ref, src, dst, key))
                return ToolResult("deferred", {"idempotency_key": key}, "none", detail=type(exc).__name__)
            return ToolResult("unavailable", source="none", detail=type(exc).__name__)
        except BackendUnavailable:
            # Never blindly retry a timed-out write: read the booking first (design §8).
            check = await self.get_booking(ctx, {"booking_ref": ref})
            if check.status == "ok" and check.data.get("flight") == dst:
                return ToolResult("ok", {"status": "CONFIRMED", "new_flight": dst, "recovered": True})
            return ToolResult("unavailable", source="none", detail="rebook timed out; booking unchanged")
        except BackendError as exc:
            return ToolResult("unavailable", source="none", detail=type(exc).__name__)
        if self.cfg.protection_enabled:
            saved = self.cache.peek(ctx, f"booking:{ref}")
            if saved.found:
                self.cache.put(ctx, f"booking:{ref}", {**saved.value, "flight": dst}, self.cfg.booking_ttl_s)
        return ToolResult("ok", data)

    # ---- background jobs (not exposed to agents) ------------------------------------
    async def prewarm(self, ctx: TenantContext, flight: str) -> dict:
        """Disruption event: load status, passenger list and alternatives once, at low priority."""
        if not self.cfg.protection_enabled:
            return {"skipped": "protection disabled"}
        wait = self.cfg.prewarm_wait_s
        status = await self._pss("P3", lambda: self.backend.flight(flight), wait)
        self.cache.put(ctx, f"flight:{flight}", status, self.cfg.status_ttl_s)
        manifest = await self._pss("P3", lambda: self.backend.passengers(flight), wait)
        by_phone: dict[str, list] = {}
        for booking in manifest:
            self.cache.put(ctx, f"booking:{booking['ref']}", booking, self.cfg.booking_ttl_s)
            by_phone.setdefault(booking["phone"], []).append(booking)
        for phone, bookings in by_phone.items():
            self.cache.put(ctx, f"phone:{phone}", bookings, self.cfg.booking_ttl_s)
        origin, dest = status["origin"], status["destination"]
        alts = await self._pss("P3", lambda: self.backend.alternatives(origin, dest), wait)
        self.cache.put(ctx, f"alts:{origin}:{dest}", alts, self.cfg.alternatives_ttl_s)
        return {"flight": flight, "status": status["status"], "bookings": len(manifest),
                "alternatives": len(alts), "pss_requests": 3}

    async def commit_deferred(self, item: PendingCommit) -> str:
        # Background job: a short wait lets it soak up spare capacity without starving callers.
        if not await self.admission.acquire("P0", 1.0):
            return "retry"
        try:
            await self.backend.rebook(item.booking_ref, item.from_flight, item.to_flight, item.idempotency_key)
        except Conflict as exc:
            item.detail = str(exc)
            return "failed"
        except BackendError:
            return "retry"
        item.detail = "confirmed; SMS sent"
        return "confirmed"


def _schema(**props: str) -> dict:
    return {"type": "object", "properties": {k: {"type": "string", "description": v} for k, v in props.items()},
            "required": list(props)}


def build_registry(tools: ReservationTools, guard: GuardPort) -> ToolRegistry:
    reg = ToolRegistry(guard)
    reg.register(Tool("get_flight_status", "Status of a flight", _schema(flight="Flight number, e.g. AT123"),
                      "P3", tools.get_flight_status))
    reg.register(Tool("find_bookings_by_phone", "Bookings whose contact number matches the caller ID",
                      _schema(phone="E.164 number"), "P1", tools.find_bookings_by_phone))
    reg.register(Tool("get_booking", "A booking by reference", _schema(booking_ref="Six characters"),
                      "P1", tools.get_booking))
    reg.register(Tool("get_alternatives", "Alternative flights on a route",
                      _schema(origin="IATA code", destination="IATA code"), "P2", tools.get_alternatives))
    reg.register(Tool("rebook", "Move a booking to another flight (hold and commit)",
                      _schema(booking_ref="Six characters", from_flight="Disrupted flight", to_flight="New flight"),
                      "P0", tools.rebook))
    return reg
