"""The MCP server over the real protocol (official SDK client, Streamable HTTP)."""

import asyncio

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from zingly_core import IdentityLevel, identity_token


async def session_call(s, tenant, tool, args, token=None):
    async with streamable_http_client(f"{s['mcp']}/{tenant}/mcp", http_client=s["http"], terminate_on_close=False) as (r, w, _):
        async with ClientSession(r, w) as session:
            await session.initialize()
            meta = {"identity_token": token} if token else None
            res = await session.call_tool(tool, args, meta=meta)
            return res.structuredContent


def test_tools_list_and_schema(stack):
    async def run():
        async with stack() as s:
            async with streamable_http_client(f"{s['mcp']}/atlantica/mcp", http_client=s["http"],
                                              terminate_on_close=False) as (r, w, _):
                async with ClientSession(r, w) as session:
                    info = await session.initialize()
                    tools = {t.name: t for t in (await session.list_tools()).tools}
                    return info.serverInfo.name, tools

    name, tools = asyncio.run(run())
    assert name == "zingly-reservations-atlantica"
    assert set(tools) == {"get_flight_status", "get_alternatives", "lookup_caller_id", "verify_booking",
                          "get_booking", "rebook"}
    assert tools["rebook"].annotations.readOnlyHint is False and tools["rebook"].outputSchema
    assert "booking_ref" in tools["rebook"].inputSchema["properties"]
    assert "identity_token" not in tools["rebook"].inputSchema["properties"]  # never a model-visible argument


def test_identity_token_guard_scope_and_tenant(stack):
    key = identity_token.signing_key("atlantica")
    args = {"booking_ref": "ABC123", "from_flight": "AT123", "to_flight": "AT127"}

    async def run():
        async with stack() as s:
            out = {"none": await session_call(s, "atlantica", "rebook", args)}
            other = identity_token.issue(key, "atlantica", "c", IdentityLevel.VERIFIED, "ZZZ999")
            out["other_booking"] = await session_call(s, "atlantica", "rebook", args, other)
            own = identity_token.issue(key, "atlantica", "c", IdentityLevel.VERIFIED, "ABC123")
            out["wrong_tenant"] = await session_call(s, "nordica", "rebook", args, own)
            out["forged"] = await session_call(s, "atlantica", "rebook", args, own[:-2] + "00")
            out["own"] = await session_call(s, "atlantica", "rebook", args, own)
            out["hint"] = await session_call(s, "atlantica", "lookup_caller_id", {"phone": "+447700900001"})
            return out

    out = asyncio.run(run())
    assert out["none"]["status"] == "denied" and "needs verified" in out["none"]["detail"]
    assert out["other_booking"]["status"] == "denied" and "not the one" in out["other_booking"]["detail"]
    assert out["wrong_tenant"]["status"] == "denied" and "identity token rejected" in out["wrong_tenant"]["detail"]  # per-tenant keys
    assert out["forged"]["status"] == "denied" and "signature" in out["forged"]["detail"]
    assert out["own"]["status"] == "ok" and out["own"]["data"]["new_flight"] == "AT127"
    assert out["hint"]["data"] == [{"flight": "AT127", "ref_masked": "A***23"}]  # masked only; already moved by the rebook


def test_prewarm_then_reads_cost_no_pss_requests(stack):
    async def run():
        async with stack() as s:
            h = s["http"]
            await h.post(f"{s['mcp']}/admin/atlantica/prewarm", json={"flight": "AT123"})
            before = (await h.get(f"{s['pss']}/stats")).json()["atlantica"]["requests"]
            for _ in range(5):
                res = await session_call(s, "atlantica", "get_alternatives", {"origin": "LHR", "destination": "BOS"})
                assert res["source"] == "saved_copy"
            after = (await h.get(f"{s['pss']}/stats")).json()["atlantica"]["requests"]
            return after - before

    assert asyncio.run(run()) == 0
