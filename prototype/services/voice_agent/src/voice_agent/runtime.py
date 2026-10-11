"""Composition root of the voice agent. One process serves every tenant; each tenant gets its
own instances built from its own merged config sections."""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from zingly_agents import AgentsConfig, Supervisor, build_supervisor
from zingly_ai_router import AIRouter
from zingly_auth import AuthConfig, DefaultAuthService
from zingly_channel import ChannelConfig, TextChannel
from zingly_core import TenantConfigStore, identity_token
from zingly_handover import GenesysHandoverBuilder, HandoverConfig

from voice_agent.mcp_client import AuthLookupAdapter, McpToolClient


@dataclass
class GatewayConfig:
    max_concurrent_sessions: int = 500
    session_idle_timeout_s: float = 1800
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
    tools: McpToolClient
    handover: GenesysHandoverBuilder

    def new_router(self) -> AIRouter:
        return AIRouter.from_config(self.router_section)

    @classmethod
    def build(cls, store: TenantConfigStore, tenant_id: str, http: httpx.AsyncClient) -> "TenantRuntime":
        sec = lambda module: store.section(tenant_id, module)  # noqa: E731
        tools = McpToolClient(store.platform("mcp_server_url", "http://127.0.0.1:8100"), tenant_id, http)
        auth_cfg = AuthConfig.from_config(sec("auth"))
        key = identity_token.signing_key(tenant_id, auth_cfg.signing_key_env or None)
        auth = DefaultAuthService(auth_cfg, AuthLookupAdapter(tools), key)
        router_section = sec("ai_router")
        enabled = router_section.get("routing", {}).get("enabled_agents", ["rebooking", "flight_status", "faq"])
        supervisor = build_supervisor(AgentsConfig.from_config(sec("agents")), tools, auth, enabled)
        return cls(tenant_id, store.meta(tenant_id)["display_name"], GatewayConfig.from_config(sec("gateway")),
                   TextChannel(ChannelConfig.from_config(sec("channel"))), router_section, supervisor, auth,
                   tools, GenesysHandoverBuilder(HandoverConfig.from_config(sec("handover"))))


class Platform:
    def __init__(self, store: TenantConfigStore, http: httpx.AsyncClient):
        self.store = store
        self.http = http
        self.runtimes = {t: TenantRuntime.build(store, t, http) for t in store.tenant_ids}

    def runtime(self, tenant_id: str) -> TenantRuntime:
        return self.runtimes[tenant_id]
