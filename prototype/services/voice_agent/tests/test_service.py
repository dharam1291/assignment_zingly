"""The voice agent end to end: gateway -> router -> agents -> MCP client -> MCP server -> PSS."""

import asyncio

ATL, NOR = "+448000001234", "+4780001234"


async def start(s, dialed, caller, call_id="call-1"):
    h = s["http"]
    r = (await h.post(f"{s['va']}/v1/conversations", json={"call_id": call_id, "dialed_number": dialed,
                                                           "caller_number": caller})).json()
    cid = r["conversation_id"]

    async def say(text):
        return (await h.post(f"{s['va']}/v1/conversations/{cid}/utterances", json={"text": text})).json()

    return r, say


def test_end_to_end_rebooking_through_mcp(stack):
    async def run():
        async with stack() as s:
            h = s["http"]
            warm = (await h.post(f"{s['va']}/v1/events/disruption", json={"tenant_id": "atlantica", "flight": "AT123"})).json()
            assert warm["bookings"] == 180
            before = (await h.get(f"{s['pss']}/stats")).json()["atlantica"]["accepted"]
            welcome, say = await start(s, ATL, "+447700900001")
            assert "Atlantica" in welcome["reply"]["text"] and welcome["reply"]["interruptible"] is False
            assert (await say("yes"))["turn_path"] == "fast_path"
            r = await say("Hi, my flight was cancelled")
            assert r["identity_level"] == "likely" and "ending 23" in r["reply"]["text"]
            await say("ABC123")
            r = await say("Smith")
            assert r["identity_level"] == "verified" and "14:05" in r["reply"]["text"]
            await say("the first one")
            r = await say("yes")
            assert "booked on AT127" in r["reply"]["text"]
            assert (await say("no thanks"))["conversation_status"] == "COMPLETED"
            after = (await h.get(f"{s['pss']}/stats")).json()["atlantica"]
            # hint, status, options from the saved copy: only verification and the commit reach the PSS
            assert after["accepted"] - before == 2 and after.get("rejected_429", 0) == 0

    asyncio.run(run())


def test_handover_payload_and_data_action(stack):
    async def run():
        async with stack() as s:
            _, say = await start(s, ATL, "+15550000000")
            for line in ["yes", "I need to rebook my cancelled flight", "ABC123", "Smith"]:
                await say(line)
            r = await say("can I speak to a human")
            assert r["conversation_status"] == "AGENT_HANDOVER"
            h = r["handover"]
            assert h["routing"]["queue"] == "Disruption_Rebooking" and h["caller"]["identity_level"] == "verified"
            assert h["booking"]["ref_masked"] == "A***23" and "ABC123" not in str(h)
            assert [a["action"] for a in h["attempted_actions"]] == ["verify_identity", "get_alternatives"]
            http = s["http"]
            ctx = (await http.get(f"{s['va']}/v1/handover-context/{h['context_ref']}", params={"tenant_id": "atlantica"})).json()
            assert ctx["booking"]["ref"] == "ABC123"
            wrong = await http.get(f"{s['va']}/v1/handover-context/{h['context_ref']}", params={"tenant_id": "nordica"})
            assert wrong.status_code == 404

    asyncio.run(run())


def test_one_deployment_two_tenants(stack):
    async def run():
        async with stack() as s:
            welcome, say = await start(s, NOR, "+4791000001", call_id="n-1")
            assert welcome["tenant_id"] == "nordica" and "Is that OK" not in welcome["reply"]["text"]
            r = await say("what is the status of NR456")
            assert "NR456 to Copenhagen is cancelled" in r["reply"]["text"]
            _, say2 = await start(s, NOR, "+15550000001", call_id="n-2")
            r = await say2("my booking ABC123 was cancelled")   # an Atlantica reference
            if r["conversation_status"] == "AGENT_HANDOVER":   # rebooking is canaried at 50% for nordica
                assert r["handover"]["routing"]["subcategory"] == "not_in_rollout"
            else:
                r = await say2("Smith")
                assert r["identity_level"] == "unknown" and "couldn't verify" in r["reply"]["text"]

    asyncio.run(run())


def test_create_is_idempotent_and_capacity_reads_the_mcp_breaker(stack):
    async def run():
        async with stack() as s:
            a, _ = await start(s, ATL, "+1", call_id="same")
            b, _ = await start(s, ATL, "+1", call_id="same")
            assert a["conversation_id"] == b["conversation_id"] and b["replayed"]
            cap = (await s["http"].get(f"{s['va']}/v1/capacity", params={"dialed_number": ATL})).json()
            assert cap["accept"] and cap["active_sessions"] == 1 and cap["pss_breaker"] == "closed"
            s["mcp_app"].state.runtimes["atlantica"].breaker.record_failure()
            for _ in range(5):
                s["mcp_app"].state.runtimes["atlantica"].breaker.record_failure()
            cap = (await s["http"].get(f"{s['va']}/v1/capacity", params={"dialed_number": ATL})).json()
            assert not cap["accept"] and cap["reasons"] == ["reservation_system_unhealthy"]

    asyncio.run(run())


def test_deferred_commit_is_drained_later_under_same_key(stack):
    async def run():
        async with stack() as s:
            h, rt = s["http"], s["mcp_app"].state.runtimes
            await h.post(f"{s['va']}/v1/events/disruption", json={"tenant_id": "atlantica", "flight": "AT123"})
            _, say = await start(s, ATL, "+15550000002")
            for text in ["yes", "my flight was cancelled", "ABC123", "Smith", "second"]:
                await say(text)
            await h.post(f"{s['mcp']}/admin/atlantica/lanes/pause", json={"lanes": ["P0"], "seconds": 3.5})  # longer than the 3 s P0 wait budget
            r = await say("yes")
            assert "within 30 minutes" in r["reply"]["text"]
            assert rt["atlantica"].deferred.summary() == {"pending": 1}
            await asyncio.sleep(1.0)
            await rt.drain_deferred()
            assert rt["atlantica"].deferred.summary() == {"confirmed": 1}
            assert (await h.get(f"{s['pss']}/admin/booking/atlantica/ABC123")).json()["flight"] == "AT131"

    asyncio.run(run())


def test_one_tenants_storm_does_not_starve_another(stack):
    async def run():
        async with stack() as s:
            rt = s["mcp_app"].state.runtimes
            atl, nor = rt["atlantica"], rt["nordica"]
            assert atl.admission is not nor.admission and atl.saved_copy is not nor.saved_copy
            atl.admission.pause(["P0", "P1", "P2", "P3"], 30)       # atlantica saturated
            _, say = await start(s, NOR, "+4791000009", call_id="iso-1")
            r = await say("status of NR456")
            assert "cancelled" in r["reply"]["text"]

    asyncio.run(run())
