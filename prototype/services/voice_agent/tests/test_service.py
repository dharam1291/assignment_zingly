import asyncio

import httpx

from mock_pss.app import create_app as create_pss
from voice_agent.app import create_app

ATL, NOR = "+448000001234", "+4780001234"


def harness(rps=5):
    pss_app = create_pss(rps=rps, latency_ms=(0, 0))
    pss = httpx.AsyncClient(transport=httpx.ASGITransport(app=pss_app), base_url="http://pss")
    app = create_app(http=pss)
    api = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://zingly")
    return app, api, pss


async def start(api, dialed, caller, call_id="call-1"):
    r = (await api.post("/v1/conversations", json={"call_id": call_id, "dialed_number": dialed,
                                                    "caller_number": caller})).json()
    cid = r["conversation_id"]

    async def say(text):
        return (await api.post(f"/v1/conversations/{cid}/utterances", json={"text": text})).json()

    return r, say


def test_end_to_end_rebooking_call_after_prewarm():
    async def run():
        app, api, pss = harness()
        warm = (await api.post("/v1/events/disruption", json={"tenant_id": "atlantica", "flight": "AT123"})).json()
        assert warm["bookings"] == 180
        before = (await pss.get("/stats")).json()["atlantica"]["accepted"]

        welcome, say = await start(api, ATL, "+447700900001")
        assert "Atlantica" in welcome["reply"]["text"] and welcome["reply"]["interruptible"] is False
        assert (await say("yes"))["turn_path"] == "fast_path"
        r = await say("Hi, my flight was cancelled")
        assert r["agent"] == "rebooking" and r["identity_level"] == "likely" and "ending 23" in r["reply"]["text"]
        await say("ABC123")
        r = await say("Smith")
        assert r["identity_level"] == "verified" and "14:05" in r["reply"]["text"]
        await say("the first one")
        r = await say("yes")
        assert "booked on AT127" in r["reply"]["text"]
        r = await say("no thanks")
        assert r["conversation_status"] == "COMPLETED"

        after = (await pss.get("/stats")).json()["atlantica"]
        # hint, status and options came from the saved copy: only verify + rebook hit the PSS
        assert after["accepted"] - before == 2
        assert after.get("rejected_429", 0) == 0
        return True

    assert asyncio.run(run())


def test_handover_payload_and_data_action():
    async def run():
        app, api, _ = harness()
        _, say = await start(api, ATL, "+15550000000")
        await say("yes")
        await say("I need to rebook my cancelled flight")
        await say("ABC123")
        await say("Smith")
        r = await say("can I speak to a human")
        assert r["conversation_status"] == "AGENT_HANDOVER"
        h = r["handover"]
        assert h["routing"]["queue"] == "Disruption_Rebooking" and h["caller"]["identity_level"] == "verified"
        assert h["booking"]["ref_masked"] == "A***23" and "ABC123" not in str(h)
        assert [a["action"] for a in h["attempted_actions"]] == ["verify_identity", "get_alternatives"]
        ctx = (await api.get(f"/v1/handover-context/{h['context_ref']}", params={"tenant_id": "atlantica"})).json()
        assert ctx["booking"]["ref"] == "ABC123"
        wrong = await api.get(f"/v1/handover-context/{h['context_ref']}", params={"tenant_id": "nordica"})
        assert wrong.status_code == 404
        return True

    assert asyncio.run(run())


def test_one_deployment_two_tenants():
    async def run():
        app, api, _ = harness()
        welcome, say = await start(api, NOR, "+4791000001", call_id="n-1")
        assert welcome["tenant_id"] == "nordica" and "Nordica" in welcome["reply"]["text"]
        assert "Is that OK" not in welcome["reply"]["text"]          # nordica: no consent prompt
        r = await say("what is the status of NR456")
        assert "NR456 to Copenhagen is cancelled" in r["reply"]["text"]
        # an Atlantica booking reference means nothing to Nordica
        _, say2 = await start(api, NOR, "+15550000001", call_id="n-2")
        r = await say2("my booking ABC123 was cancelled")
        if r["conversation_status"] == "AGENT_HANDOVER":   # rebooking is canaried at 50% for nordica
            assert r["handover"]["routing"]["subcategory"] == "not_in_rollout"
        else:
            r = await say2("Smith")
            assert r["identity_level"] == "unknown" and "couldn't verify" in r["reply"]["text"]
        return True

    assert asyncio.run(run())


def test_create_is_idempotent_on_call_id_and_capacity_check():
    async def run():
        app, api, _ = harness()
        a, _ = await start(api, ATL, "+1", call_id="same")
        b, _ = await start(api, ATL, "+1", call_id="same")
        assert a["conversation_id"] == b["conversation_id"] and b["replayed"]
        cap = (await api.get("/v1/capacity", params={"dialed_number": ATL})).json()
        assert cap["accept"] and cap["active_sessions"] == 1
        return True

    assert asyncio.run(run())


def test_deferred_commit_is_drained_later_under_same_key():
    async def run():
        app, api, pss = harness()
        rt = app.state.platform.runtime("atlantica")
        await api.post("/v1/events/disruption", json={"tenant_id": "atlantica", "flight": "AT123"})
        _, say = await start(api, ATL, "+15550000002")
        for text in ["yes", "my flight was cancelled", "ABC123", "Smith", "second"]:
            await say(text)
        rt.admission.config.wait_s["P0"] = 0.0
        while await rt.admission.acquire("P0"):      # drain P0 (and the lanes it can borrow)
            pass
        r = await say("yes")
        assert "within 30 minutes" in r["reply"]["text"]
        assert rt.deferred.summary() == {"pending": 1}
        await asyncio.sleep(1.2)
        await rt.deferred.drain(rt.tools.commit_deferred)
        assert rt.deferred.summary() == {"confirmed": 1}
        booking = (await pss.get("/atlantica/bookings/ABC123")).json()
        assert booking["flight"] == "AT131"
        return True

    assert asyncio.run(run())


def test_one_tenants_storm_does_not_starve_another():
    async def run():
        app, api, pss = harness()
        atl = app.state.platform.runtime("atlantica")
        nor = app.state.platform.runtime("nordica")
        assert atl.admission is not nor.admission and atl.saved_copy is not nor.saved_copy
        while await atl.admission.acquire("P0", 0.0):   # atlantica's lanes are exhausted
            pass
        assert not await atl.admission.acquire("P3", 0.0)
        _, say = await start(api, NOR, "+4791000009", call_id="iso-1")
        r = await say("status of NR456")                 # nordica's P3 lane still has its token
        assert "cancelled" in r["reply"]["text"]
        return True

    assert asyncio.run(run())
