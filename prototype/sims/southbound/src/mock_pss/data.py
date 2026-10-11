"""Deterministic seed data so every run (and every test) sees the same bookings."""

from __future__ import annotations

import random
from dataclasses import dataclass, field

SURNAMES = ["Smith", "Jones", "Taylor", "Brown", "Williams", "Wilson", "Johnson", "Davies",
            "Patel", "Wright", "Walker", "Evans", "Thomas", "Roberts", "Khan", "Lewis"]
REF_CHARS = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


@dataclass
class Airline:
    code: str
    flights: dict[str, dict] = field(default_factory=dict)
    bookings: dict[str, dict] = field(default_factory=dict)
    alternatives: dict[tuple[str, str], list[dict]] = field(default_factory=dict)
    rebookings: dict[str, dict] = field(default_factory=dict)  # idempotency key -> result


def _gen_bookings(rng: random.Random, flight: dict, count: int, phone_prefix: str,
                  start: int, fixed: list[dict]) -> dict[str, dict]:
    route = {"flight": flight["flight"], "origin": flight["origin"], "destination": flight["destination"]}
    out = {b["ref"]: {**b, **route} for b in fixed}
    i = start
    while len(out) < count:
        ref = "".join(rng.choice(REF_CHARS) for _ in range(6))
        if ref in out or not any(ch.isdigit() for ch in ref):
            continue
        out[ref] = {
            "ref": ref,
            "surname": rng.choice(SURNAMES),
            "phone": f"{phone_prefix}{i:06d}",
            **route,
            "cabin": "economy",
            "passengers": 1,
        }
        i += 1
    return out


def seed() -> dict[str, Airline]:
    rng = random.Random(1291)
    atl = Airline("atlantica")
    atl.flights = {
        "AT123": {"flight": "AT123", "origin": "LHR", "destination": "BOS", "date": "2026-10-10",
                  "departure": "09:40", "status": "CANCELLED", "reason": "weather"},
        "AT127": {"flight": "AT127", "origin": "LHR", "destination": "BOS", "date": "2026-10-10",
                  "departure": "14:05", "status": "ON_TIME"},
        "AT131": {"flight": "AT131", "origin": "LHR", "destination": "BOS", "date": "2026-10-10",
                  "departure": "19:40", "status": "ON_TIME"},
        "AT200": {"flight": "AT200", "origin": "LHR", "destination": "JFK", "date": "2026-10-10",
                  "departure": "11:15", "status": "DELAYED", "delay_minutes": 45},
    }
    atl.bookings = _gen_bookings(rng, atl.flights["AT123"], 180, "+4477009", 2, [
        {"ref": "ABC123", "surname": "Smith", "phone": "+447700900001", "cabin": "economy",
         "passengers": 1},
    ])
    atl.alternatives[("LHR", "BOS")] = [
        {"flight": "AT127", "departure": "14:05", "arrival": "16:55", "seats_left": 120},
        {"flight": "AT131", "departure": "19:40", "arrival": "22:30", "seats_left": 150},
    ]

    nor = Airline("nordica")
    nor.flights = {
        "NR456": {"flight": "NR456", "origin": "OSL", "destination": "CPH", "date": "2026-10-10",
                  "departure": "08:10", "status": "CANCELLED", "reason": "storm"},
        "NR460": {"flight": "NR460", "origin": "OSL", "destination": "CPH", "date": "2026-10-10",
                  "departure": "12:30", "status": "ON_TIME"},
    }
    nor.bookings = _gen_bookings(rng, nor.flights["NR456"], 60, "+479100", 2, [
        {"ref": "NRD789", "surname": "Hansen", "phone": "+4791000001", "cabin": "economy",
         "passengers": 1},
    ])
    nor.alternatives[("OSL", "CPH")] = [
        {"flight": "NR460", "departure": "12:30", "arrival": "13:40", "seats_left": 80},
    ]
    return {a.code: a for a in (atl, nor)}
