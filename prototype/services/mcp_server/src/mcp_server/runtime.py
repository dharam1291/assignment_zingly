"""Composition root of the MCP server: one runtime per tenant from the shared config file."""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from zingly_core import IdentityClaims, InvalidToken, TenantConfigStore, identity_token, tracing
from zingly_mcp import DeferredCommits, HttpPssBackend, McpConfig, ReservationTools, ToolRegistry, build_registry
from zingly_policy import BreakerConfig, CountingBreaker, LaneAdmission, LanesConfig, LevelGuard
from zingly_saved_copy import InMemorySavedCopy, SavedCopyConfig


@dataclass
class TenantTools:
    tenant_id: str
    registry: ToolRegistry
    tools: ReservationTools
    admission: LaneAdmission
    breaker: CountingBreaker
    saved_copy: InMemorySavedCopy
    deferred: DeferredCommits
    signing_key: bytes

    def identify(self, token: str | None) -> tuple[IdentityClaims, str | None]:
        """Level comes only from a valid signed token; anything else is UNKNOWN."""
        if not token:
            return IdentityClaims.anonymous(self.tenant_id), None
        try:
            return identity_token.verify(self.signing_key, token, self.tenant_id), None
        except (InvalidToken, ValueError, KeyError) as exc:
            return IdentityClaims.anonymous(self.tenant_id), f"identity token rejected: {exc}"

    def stats(self) -> dict:
        results: dict[str, int] = {}
        for a in self.registry.audit:
            key = f"{a['tool']}:{a['status']}:{a['source']}"
            results[key] = results.get(key, 0) + 1
        return {"lanes": self.admission.stats(), "saved_copy": self.saved_copy.stats(self.tenant_id),
                "deferred_commits": self.deferred.summary(), "breaker": self.breaker.state,
                "protection_enabled": self.tools.cfg.protection_enabled, "tool_results": results}


def build_tenant(store: TenantConfigStore, tenant_id: str, http: httpx.AsyncClient) -> TenantTools:
    policy = store.section(tenant_id, "policy")
    admission = LaneAdmission(LanesConfig.from_config(policy))
    breaker = CountingBreaker(BreakerConfig.from_config(policy))
    saved_copy = InMemorySavedCopy(SavedCopyConfig.from_config(store.section(tenant_id, "saved_copy")))
    cfg = McpConfig.from_config(store.section(tenant_id, "mcp"))
    backend = HttpPssBackend(cfg.pss_base_url, cfg.airline_code, http, cfg.timeout_s)
    deferred = DeferredCommits()
    tools = ReservationTools(cfg, backend, admission, saved_copy, breaker, deferred)
    registry = build_registry(tools, LevelGuard.from_config(policy))
    key = identity_token.signing_key(tenant_id, store.section(tenant_id, "auth").get("signing_key_env") or None)
    return TenantTools(tenant_id, registry, tools, admission, breaker, saved_copy, deferred, key)


class Runtimes:
    def __init__(self, store: TenantConfigStore, http: httpx.AsyncClient):
        self.store = store
        self.http = http
        self.by_tenant = {t: build_tenant(store, t, http) for t in store.tenant_ids}

    def __getitem__(self, tenant_id: str) -> TenantTools:
        return self.by_tenant[tenant_id]

    def reset(self, tenant_id: str) -> None:
        self.by_tenant[tenant_id] = build_tenant(self.store, tenant_id, self.http)

    async def drain_deferred(self) -> None:
        for rt in list(self.by_tenant.values()):
            if rt.deferred.pending():
                with tracing.span("mcp.drain_deferred", "mcp-server", tenant=rt.tenant_id):
                    await rt.deferred.drain(rt.tools.commit_deferred)
