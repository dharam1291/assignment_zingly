from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Protocol

from zingly_core import IdentityLevel, TenantContext


class BookingLookupPort(Protocol):
    """What auth needs to look up bookings. Results expose ``.status`` (ok|stale|...),
    ``.data`` and ``.as_of``; the service plugs MCP tools in here."""

    async def find_by_phone(self, ctx: TenantContext, phone: str) -> Any: ...

    async def get_booking(self, ctx: TenantContext, booking_ref: str) -> Any: ...


@dataclass
class AuthConfig:
    max_attempts: int = 3
    lockout_minutes: float = 60
    use_caller_id_hint: bool = True

    @classmethod
    def from_config(cls, section: Mapping[str, Any]) -> "AuthConfig":
        known = {k: section[k] for k in cls.__dataclass_fields__ if k in section}
        return cls(**known)


@dataclass
class AuthResult:
    level: IdentityLevel
    outcome: str                       # likely | unknown | verified | failed | locked | unavailable
    booking: dict | None = None        # only when verified
    masked: dict | None = None         # safe to speak at LIKELY
    verified_by: str | None = None
    attempts_left: int | None = None
    data_as_of: float | None = None    # set when verified against the saved copy


def mask_ref(ref: str) -> str:
    return ref[0] + "*" * (len(ref) - 3) + ref[-2:] if len(ref) > 3 else "***"


class AuthService(Protocol):
    async def identify_by_caller_id(self, ctx: TenantContext, caller_number: str) -> AuthResult: ...

    async def verify(self, ctx: TenantContext, caller_number: str, booking_ref: str, surname: str) -> AuthResult: ...

    def is_locked(self, ctx: TenantContext, caller_number: str) -> bool: ...


@dataclass
class _Attempts:
    failures: int = 0
    locked_until: float = 0.0


@dataclass
class DefaultAuthService:
    config: AuthConfig
    lookup: BookingLookupPort
    clock: Callable[[], float] = time.time
    _attempts: dict[str, _Attempts] = field(default_factory=dict)  # Redis in production

    def _state(self, ctx: TenantContext, caller_number: str) -> _Attempts:
        return self._attempts.setdefault(ctx.key("auth", caller_number), _Attempts())

    def is_locked(self, ctx: TenantContext, caller_number: str) -> bool:
        return self._state(ctx, caller_number).locked_until > self.clock()

    async def identify_by_caller_id(self, ctx: TenantContext, caller_number: str) -> AuthResult:
        if not self.config.use_caller_id_hint or not caller_number:
            return AuthResult(IdentityLevel.UNKNOWN, "unknown")
        found = await self.lookup.find_by_phone(ctx, caller_number)
        if found.status not in ("ok", "stale") or not found.data:
            return AuthResult(IdentityLevel.UNKNOWN, "unknown")
        booking = found.data[0]
        masked = {"flight": booking["flight"], "ref_masked": mask_ref(booking["ref"]),
                  "bookings_on_number": len(found.data)}
        return AuthResult(IdentityLevel.LIKELY, "likely", masked=masked, data_as_of=found.as_of)

    async def verify(self, ctx: TenantContext, caller_number: str, booking_ref: str, surname: str) -> AuthResult:
        state = self._state(ctx, caller_number)
        if self.is_locked(ctx, caller_number):
            return AuthResult(IdentityLevel.UNKNOWN, "locked", attempts_left=0)
        ref = "".join(booking_ref.split()).upper()
        found = await self.lookup.get_booking(ctx, ref)
        if found.status not in ("ok", "stale", "not_found"):
            # Our side could not check: not the caller's fault, so no attempt is used up.
            return AuthResult(IdentityLevel.UNKNOWN, "unavailable",
                              attempts_left=self.config.max_attempts - state.failures)
        if found.status in ("ok", "stale") and found.data["surname"].casefold() == surname.strip().casefold():
            state.failures = 0
            return AuthResult(IdentityLevel.VERIFIED, "verified", booking=found.data,
                              verified_by="booking_ref+surname",
                              data_as_of=found.as_of if found.status == "stale" else None)
        state.failures += 1
        if state.failures >= self.config.max_attempts:
            state.locked_until = self.clock() + self.config.lockout_minutes * 60
            state.failures = 0
            return AuthResult(IdentityLevel.UNKNOWN, "locked", attempts_left=0)
        return AuthResult(IdentityLevel.UNKNOWN, "failed", attempts_left=self.config.max_attempts - state.failures)
