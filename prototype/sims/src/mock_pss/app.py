"""Mock PSS over HTTP. Hard limit per airline (default 5 req/s, sliding 1 s window).

Run: ``uvicorn mock_pss.app:app --port 9001``  (env MOCK_PSS_RPS, MOCK_PSS_LATENCY_MS)
"""

from __future__ import annotations

import asyncio
import os
import random
import time
from collections import Counter, deque

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from mock_pss.data import seed


class SlidingWindowLimiter:
    def __init__(self, rps: int):
        self.rps = rps
        self._hits: deque[float] = deque()

    def allow(self, now: float) -> bool:
        while self._hits and now - self._hits[0] >= 1.0:
            self._hits.popleft()
        if len(self._hits) >= self.rps:
            return False
        self._hits.append(now)
        return True


class State:
    def __init__(self, rps: int, latency_ms: tuple[int, int]):
        self.rps = rps
        self.latency_ms = latency_ms
        self.reset()

    def reset(self) -> None:
        self.airlines = seed()
        self.limiters = {code: SlidingWindowLimiter(self.rps) for code in self.airlines}
        self.counts: dict[str, Counter] = {code: Counter() for code in self.airlines}
        self.per_second: dict[str, Counter] = {code: Counter() for code in self.airlines}
        self.error_rate: dict[str, float] = {code: 0.0 for code in self.airlines}
        self.extra_latency_ms: dict[str, int] = {code: 0 for code in self.airlines}


def _latency_from_env() -> tuple[int, int]:
    lo, _, hi = os.environ.get("MOCK_PSS_LATENCY_MS", "40-120").partition("-")
    return int(lo), int(hi or lo)


def create_app(rps: int | None = None, latency_ms: tuple[int, int] | None = None) -> FastAPI:
    state = State(rps or int(os.environ.get("MOCK_PSS_RPS", "5")), latency_ms or _latency_from_env())
    app = FastAPI(title="Mock Atlantica PSS")
    app.state.pss = state

    @app.middleware("http")
    async def rate_limit(request: Request, call_next):
        parts = request.url.path.strip("/").split("/")
        airline = parts[0] if parts else ""
        if airline not in state.airlines:  # /stats, /admin/* are not rate limited
            return await call_next(request)
        now = time.monotonic()
        counts = state.counts[airline]
        counts["requests"] += 1
        if not state.limiters[airline].allow(now):
            counts["rejected_429"] += 1
            return JSONResponse({"error": "rate limit exceeded"}, status_code=429,
                                headers={"Retry-After": "1"})
        counts["accepted"] += 1
        counts[f"endpoint:{parts[1] if len(parts) > 1 else ''}"] += 1
        state.per_second[airline][int(time.time())] += 1
        lo, hi = state.latency_ms
        await asyncio.sleep((random.uniform(lo, hi) + state.extra_latency_ms[airline]) / 1000)
        if random.random() < state.error_rate[airline]:
            counts["errors_503"] += 1
            return JSONResponse({"error": "backend unavailable"}, status_code=503)
        return await call_next(request)

    def airline_or_404(code: str):
        if code not in state.airlines:
            raise HTTPException(404, "unknown airline")
        return state.airlines[code]

    @app.get("/{airline}/flights/{flight}")
    async def flight(airline: str, flight: str):
        data = airline_or_404(airline).flights.get(flight.upper())
        if not data:
            raise HTTPException(404, "flight not found")
        return data

    @app.get("/{airline}/flights/{flight}/passengers")
    async def passengers(airline: str, flight: str):
        a = airline_or_404(airline)
        return {"flight": flight.upper(),
                "bookings": [b for b in a.bookings.values() if b["flight"] == flight.upper()]}

    @app.get("/{airline}/bookings/{ref}")
    async def booking(airline: str, ref: str):
        data = airline_or_404(airline).bookings.get(ref.upper())
        if not data:
            raise HTTPException(404, "booking not found")
        return data

    @app.get("/{airline}/bookings")
    async def bookings_by_phone(airline: str, phone: str):
        return {"bookings": [b for b in airline_or_404(airline).bookings.values() if b["phone"] == phone]}

    @app.get("/{airline}/alternatives")
    async def alternatives(airline: str, origin: str, destination: str):
        options = airline_or_404(airline).alternatives.get((origin.upper(), destination.upper()), [])
        return {"origin": origin.upper(), "destination": destination.upper(),
                "options": [o for o in options if o["seats_left"] > 0]}

    @app.post("/{airline}/rebookings")
    async def rebook(airline: str, body: dict, idempotency_key: str = Header(...)):
        a = airline_or_404(airline)
        if idempotency_key in a.rebookings:
            return {**a.rebookings[idempotency_key], "replayed": True}
        booking = a.bookings.get(str(body.get("booking_ref", "")).upper())
        if not booking or booking["flight"] != body.get("from_flight"):
            raise HTTPException(409, "booking not on from_flight")
        target = a.flights.get(body.get("to_flight", ""))
        options = a.alternatives.get((target["origin"], target["destination"]), []) if target else []
        option = next((o for o in options if o["flight"] == body.get("to_flight")), None)
        if not option or option["seats_left"] <= 0:
            raise HTTPException(409, "no seats on to_flight")
        option["seats_left"] -= booking["passengers"]
        booking["flight"] = option["flight"]
        result = {"status": "CONFIRMED", "booking_ref": booking["ref"], "new_flight": option["flight"],
                  "departure": option["departure"], "confirmation": f"RB{len(a.rebookings) + 1:05d}"}
        a.rebookings[idempotency_key] = result
        return result

    # ---- test-harness endpoints: not rate limited, not counted -----------------------
    @app.get("/stats")
    async def stats():
        out = {}
        for code, counts in state.counts.items():
            per_sec = state.per_second[code]
            out[code] = {**dict(counts), "limit_rps": state.rps,
                         "peak_accepted_rps": max(per_sec.values(), default=0)}
        return out

    @app.post("/admin/reset")
    async def reset():
        state.reset()
        return {"ok": True}

    @app.post("/admin/mode")
    async def mode(body: dict):
        code = body["airline"]
        state.error_rate[code] = float(body.get("error_rate", 0.0))
        state.extra_latency_ms[code] = int(body.get("extra_latency_ms", 0))
        return {"ok": True}

    @app.get("/admin/seed/{airline}")
    async def seed_dump(airline: str):
        return {"bookings": list(airline_or_404(airline).bookings.values())}

    return app


app = create_app()
