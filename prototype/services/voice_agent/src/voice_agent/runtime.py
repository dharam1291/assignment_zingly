"""Composition root. One process serves every tenant; each tenant gets its own instances,
built from its own merged config sections, so limits, caches and lockouts never mix."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from zingly_agents import AgentsConfig, Supervisor, build_supervisor
from zingly_ai_router import AIRouter
from zingly_auth import AuthConfig, DefaultAuthService
from zingly_channel import ChannelConfig, TextChannel
from zingly_core import IdentityLevel, TenantConfigStore, TenantContext
from zingly_handover import GenesysHandoverBuilder, HandoverConfig
from zingly_mcp import DeferredCommits, HttpPssBackend, McpConfig, ReservationTools, ToolRegistry, build_registry
from zingly_policy import BreakerConfig, CountingBreaker, LaneAdmission, LanesConfig, LevelGuard
from zingly_saved_copy import InMemorySavedCopy, SavedCopyConfig


class AuthLookupAdapter:
    """auth.BookingLookupPort -> MCP tools. Auth looks up as UNKNOWN: it is what grants levels."""

    def __init__(self, registry: ToolRegistry):
        self._registry = registry

    async def find_by_phone(self, ctx: TenantContext, phone: str) -> Any:
        return await self._registry.call(ctx, "find_bookings_by_phone", {"phone": phone}, IdentityLevel.UNKNOWN)

    async def get_booking(self, ctx: TenantContext, booking_ref: str) -> Any:
        return await self._registry.call(ctx, "get_booking", {"booking_ref": booking_ref}, IdentityLevel.UNKNOWN)


@dataclass
class GatewayConfig:
    max_concurrent_sessions: int = 500
    webhook_secret_env: str = ""

    @classmethod
    def from_config(cls, section: dict) -> "GatewayConfig":
        known = {k: section[k] for k in cls.__dataclass_fields__ if k in section}
        return cls(**known)


@dataclass
class TenantRuntime:
    tenant_id: str
    display_name: str
    gateway: GatewayConfig
    channel: TextChannel
    router_section: dict
    supervisor: Supervisor
    auth: DefaultAuthService
    registry: ToolRegistry
    tools: ReservationTools
    admission: LaneAdmission
    breaker: CountingBreaker
    saved_copy: InMemorySavedCopy
    deferred: DeferredCommits
    handover: GenesysHandoverBuilder

    def new_router(self) -> AIRouter:
        return AIRouter.from_config(self.router_section)

    @classmethod
    def build(cls, store: TenantConfigStore, tenant_id: str, http: httpx.AsyncClient) -> "TenantRuntime":
        sec = lambda module: store.section(tenant_id, module)  # noqa: E731
        meta = store.meta(tenant_id)

        policy = sec("policy")
        admission = LaneAdmission(LanesConfig.from_config(policy))
        breaker = CountingBreaker(BreakerConfig.from_config(policy))
        guard = LevelGuard.from_config(policy)

        saved_copy = InMemorySavedCopy(SavedCopyConfig.from_config(sec("saved_copy")))
        mcp_cfg = McpConfig.from_config(sec("mcp"))
        backend = HttpPssBackend(mcp_cfg.pss_base_url, mcp_cfg.airline_code, http, mcp_cfg.timeout_s)
        deferred = DeferredCommits()
        tools = ReservationTools(mcp_cfg, backend, admission, saved_copy, breaker, deferred)
        registry = build_registry(tools, guard)

        auth = DefaultAuthService(AuthConfig.from_config(sec("auth")), AuthLookupAdapter(registry))
        router_section = sec("ai_router")
        enabled = router_section.get("routing", {}).get("enabled_agents", ["rebooking", "flight_status", "faq"])
        supervisor = build_supervisor(AgentsConfig.from_config(sec("agents")), registry, auth, enabled)

        return cls(tenant_id, meta["display_name"], GatewayConfig.from_config(sec("gateway")),
                   TextChannel(ChannelConfig.from_config(sec("channel"))), router_section, supervisor, auth,
                   registry, tools, admission, breaker, saved_copy, deferred,
                   GenesysHandoverBuilder(HandoverConfig.from_config(sec("handover"))))


class Platform:
    def __init__(self, store: TenantConfigStore, http: httpx.AsyncClient):
        self.store = store
        self.http = http
        self.runtimes = {t: TenantRuntime.build(store, t, http) for t in store.tenant_ids}

    def runtime(self, tenant_id: str) -> TenantRuntime:
        return self.runtimes[tenant_id]
