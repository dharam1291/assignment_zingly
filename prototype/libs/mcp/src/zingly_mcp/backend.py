"""Adapter to an airline's reservation system (PSS)."""

from __future__ import annotations

from typing import Any, Protocol

import httpx


class BackendError(Exception):
    pass


class RateLimited(BackendError):
    """The PSS answered 429. With protection on this should never happen."""


class BackendUnavailable(BackendError):
    pass


class NotFound(BackendError):
    pass


class Conflict(BackendError):
    pass


class PssBackend(Protocol):
    async def flight(self, flight: str) -> dict: ...

    async def passengers(self, flight: str) -> list[dict]: ...

    async def booking(self, ref: str) -> dict: ...

    async def bookings_by_phone(self, phone: str) -> list[dict]: ...

    async def alternatives(self, origin: str, destination: str) -> list[dict]: ...

    async def rebook(self, ref: str, from_flight: str, to_flight: str, idempotency_key: str) -> dict: ...


class HttpPssBackend:
    def __init__(self, base_url: str, airline: str, client: httpx.AsyncClient, timeout_s: float = 2.0):
        self._base = f"{base_url.rstrip('/')}/{airline}"
        self._client = client
        self._timeout = timeout_s

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            resp = await self._client.request(method, self._base + path, timeout=self._timeout, **kwargs)
        except httpx.HTTPError as exc:
            raise BackendUnavailable(type(exc).__name__) from exc
        if resp.status_code == 429:
            raise RateLimited(resp.headers.get("Retry-After", "1"))
        if resp.status_code == 404:
            raise NotFound(path)
        if resp.status_code == 409:
            raise Conflict(resp.json().get("detail", "conflict"))
        if resp.status_code >= 500:
            raise BackendUnavailable(str(resp.status_code))
        resp.raise_for_status()
        return resp.json()

    async def flight(self, flight: str) -> dict:
        return await self._request("GET", f"/flights/{flight}")

    async def passengers(self, flight: str) -> list[dict]:
        return (await self._request("GET", f"/flights/{flight}/passengers"))["bookings"]

    async def booking(self, ref: str) -> dict:
        return await self._request("GET", f"/bookings/{ref}")

    async def bookings_by_phone(self, phone: str) -> list[dict]:
        return (await self._request("GET", "/bookings", params={"phone": phone}))["bookings"]

    async def alternatives(self, origin: str, destination: str) -> list[dict]:
        data = await self._request("GET", "/alternatives", params={"origin": origin, "destination": destination})
        return data["options"]

    async def rebook(self, ref: str, from_flight: str, to_flight: str, idempotency_key: str) -> dict:
        return await self._request("POST", "/rebookings", headers={"Idempotency-Key": idempotency_key},
                                   json={"booking_ref": ref, "from_flight": from_flight, "to_flight": to_flight})
