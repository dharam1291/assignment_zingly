"""Disruption spike: many simultaneous callers against a 5 req/s reservation system.

Needs the mock PSS (:9001) and the voice agent (:8080) running (``make run``).

    python scripts/spike.py --mode compare            # unprotected vs protected, side by side
    python scripts/spike.py --mode protected --calls 200 --rate 8

Each simulated caller is a real passenger from the cancelled flight. A share of them
rebook (verify, choose, confirm); the rest ask for flight status and hang up.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import statistics
import time
from collections import Counter

import httpx

STATUS_LINES = ["what's the status of {flight}", "is {flight} delayed", "status of flight {flight} please"]


async def caller(api: httpx.AsyncClient, i: int, booking: dict, dialed: str, flight: str,
                 rebook: bool, think_s: float, latencies: list[float]) -> str:
    r = await api.post("/v1/conversations", json={"call_id": f"spike-{time.time_ns()}-{i}",
                                                  "dialed_number": dialed, "caller_number": booking["phone"]})
    if r.status_code != 200:
        return f"rejected_at_gateway:{r.status_code}"
    conv = r.json()
    lines = ["yes"] if "Is that OK" in conv["reply"]["text"] else []
    if rebook:
        lines += ["my flight was cancelled, I need a new flight", booking["ref"], booking["surname"],
                  random.choice(["the first one", "second"]), "yes", "no thanks"]
    else:
        lines += [random.choice(STATUS_LINES).format(flight=flight), "no thanks"]

    outcome = "status_answered" if not rebook else "incomplete"
    for line in lines:
        await asyncio.sleep(think_s)
        t0 = time.perf_counter()
        resp = await api.post(f"/v1/conversations/{conv['conversation_id']}/utterances", json={"text": line})
        latencies.append((time.perf_counter() - t0) * 1000)
        last = resp.json()
        text = last["reply"]["text"]
        if "booked on" in text:
            outcome = "rebooked_live"
        elif "within 30 minutes" in text:
            outcome = "rebooked_deferred"
        if last["conversation_status"] == "AGENT_HANDOVER":
            return f"handover:{last['handover']['routing']['subcategory']}"
        if last["conversation_status"] == "COMPLETED":
            break
    return outcome


def delta(after: dict, before: dict) -> dict:
    out = {}
    for k, v in after.items():
        if isinstance(v, (int, float)) and not isinstance(v, bool) and v - before.get(k, 0):
            out[k] = v - before.get(k, 0)
    return out


async def run_mode(args, protected: bool) -> dict:
    async with httpx.AsyncClient(base_url=args.zingly, timeout=60,
                                 limits=httpx.Limits(max_connections=1000)) as api, \
            httpx.AsyncClient(base_url=args.pss, timeout=10) as pss:
        await pss.post("/admin/reset")
        await api.post(f"/v1/admin/tenants/{args.tenant}/protection", json={"enabled": protected})
        bookings = (await pss.get(f"/admin/seed/{args.tenant}")).json()["bookings"]
        random.Random(7).shuffle(bookings)
        if protected and not args.no_prewarm:
            warm = (await api.post("/v1/events/disruption", json={"tenant_id": args.tenant, "flight": args.flight})).json()
            print(f"  pre-warm: {warm}")
        za = (await api.get("/v1/admin/stats")).json()[args.tenant]
        pa = (await pss.get("/stats")).json()[args.tenant]

        rng = random.Random(args.seed)
        latencies: list[float] = []
        started = time.perf_counter()

        async def scheduled(i: int):
            await asyncio.sleep(i / args.rate)
            return await caller(api, i, bookings[i % len(bookings)], args.dialed, args.flight,
                                rng.random() < args.rebook_share, args.think, latencies)

        outcomes = Counter(await asyncio.gather(*(scheduled(i) for i in range(args.calls))))
        elapsed = time.perf_counter() - started
        if protected:
            await asyncio.sleep(args.drain_wait)  # let deferred commits drain

        zb = (await api.get("/v1/admin/stats")).json()[args.tenant]
        pb = (await pss.get("/stats")).json()[args.tenant]
        await api.post(f"/v1/admin/tenants/{args.tenant}/protection", json={"enabled": True})

    pss_d = delta(pb, pa)
    lat = sorted(latencies)
    return {
        "mode": "protected" if protected else "unprotected",
        "calls": args.calls,
        "duration_s": round(elapsed, 1),
        "outcomes": dict(sorted(outcomes.items())),
        "pss_requests": pss_d.get("requests", 0),
        "pss_accepted": pss_d.get("accepted", 0),
        "pss_429": pss_d.get("rejected_429", 0),
        "pss_requests_per_call": round(pss_d.get("requests", 0) / args.calls, 2),
        "pss_peak_accepted_rps": pb.get("peak_accepted_rps"),
        "pss_limit_rps": pb.get("limit_rps"),
        "saved_copy": delta(zb["saved_copy"], za["saved_copy"]),
        "lanes": delta(zb["lanes"], za["lanes"]),
        "deferred_commits": zb["deferred_commits"],
        "turn_latency_ms": {"p50": round(statistics.median(lat), 1) if lat else None,
                            "p95": round(lat[int(len(lat) * 0.95) - 1], 1) if lat else None},
    }


def print_report(results: list[dict]) -> None:
    rows = [("calls", "calls"), ("duration_s", "duration (s)"), ("pss_requests", "PSS requests sent"),
            ("pss_429", "PSS 429 rejections"), ("pss_requests_per_call", "PSS requests per call"),
            ("pss_peak_accepted_rps", "PSS peak accepted req/s")]
    names = [r["mode"] for r in results]
    print("\n" + "metric".ljust(28) + "".join(n.rjust(16) for n in names))
    print("-" * (28 + 16 * len(names)))
    for key, label in rows:
        print(label.ljust(28) + "".join(str(r[key]).rjust(16) for r in results))
    print("turn latency p50 / p95 ms".ljust(28)
          + "".join(f"{r['turn_latency_ms']['p50']}/{r['turn_latency_ms']['p95']}".rjust(16) for r in results))
    for r in results:
        print(f"\n[{r['mode']}] caller outcomes: {r['outcomes']}")
        if r["mode"] == "protected":
            print(f"[{r['mode']}] saved copy: {r['saved_copy']}")
            print(f"[{r['mode']}] lanes: {r['lanes']}")
            print(f"[{r['mode']}] deferred commits: {r['deferred_commits']}")


async def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--zingly", default="http://127.0.0.1:8080")
    p.add_argument("--pss", default="http://127.0.0.1:9001")
    p.add_argument("--tenant", default="atlantica")
    p.add_argument("--dialed", default="+448000001234")
    p.add_argument("--flight", default="AT123")
    p.add_argument("--mode", choices=["protected", "unprotected", "compare"], default="compare")
    p.add_argument("--calls", type=int, default=120)
    p.add_argument("--rate", type=float, default=6.0, help="new calls per second")
    p.add_argument("--rebook-share", type=float, default=0.4)
    p.add_argument("--think", type=float, default=0.5, help="seconds between caller turns")
    p.add_argument("--drain-wait", type=float, default=8.0)
    p.add_argument("--no-prewarm", action="store_true")
    p.add_argument("--seed", type=int, default=1291)
    p.add_argument("--out", help="write JSON results here")
    args = p.parse_args()

    modes = {"protected": [True], "unprotected": [False], "compare": [False, True]}[args.mode]
    results = []
    for protected in modes:
        print(f"\n== {'protected' if protected else 'unprotected'}: {args.calls} calls at {args.rate}/s "
              f"against the {args.tenant} PSS (hard limit 5 req/s) ==")
        results.append(await run_mode(args, protected))
    print_report(results)
    if args.out:
        with open(args.out, "w") as fh:
            json.dump(results, fh, indent=2)
        print(f"\nwrote {args.out}")


if __name__ == "__main__":
    asyncio.run(main())
