import asyncio

import httpx

from mock_pss.app import create_app


def client(rps=5):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(rps=rps, latency_ms=(0, 0))),
                             base_url="http://pss")


def test_hard_rate_limit_returns_429():
    async def run():
        async with client() as c:
            codes = [(await c.get("/atlantica/flights/AT123")).status_code for _ in range(8)]
            stats = (await c.get("/stats")).json()["atlantica"]
        return codes, stats

    codes, stats = asyncio.run(run())
    assert codes.count(200) == 5 and codes.count(429) == 3
    assert stats["rejected_429"] == 3


def test_rebooking_is_idempotent_and_airlines_are_separate():
    async def run():
        async with client(rps=100) as c:
            body = {"booking_ref": "ABC123", "from_flight": "AT123", "to_flight": "AT127"}
            r1 = await c.post("/atlantica/rebookings", json=body, headers={"Idempotency-Key": "k1"})
            r2 = await c.post("/atlantica/rebookings", json=body, headers={"Idempotency-Key": "k1"})
            nor = await c.get("/nordica/bookings/ABC123")
        return r1.json(), r2.json(), nor.status_code

    first, replay, nordica = asyncio.run(run())
    assert first["status"] == "CONFIRMED" and replay["replayed"] is True
    assert first["confirmation"] == replay["confirmation"]
    assert nordica == 404
