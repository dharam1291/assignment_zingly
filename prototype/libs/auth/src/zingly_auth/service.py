from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Protocol

from zingly_core import IdentityLevel, TenantContext, identity_token, tracing


class BookingLookupPort(Protocol):
    """What auth needs from the airline's systems. Results expose ``.status`` (ok|stale|...),
    ``.data`` and ``.as_of``; the service plugs the MCP client in here.

    * ``caller_id_hint`` -> masked list ``[{flight, ref_masked}]`` (MCP ``lookup_caller_id``)
    * ``check_booking``  -> ``{match, booking?}`` (MCP ``verify_booking``)
    """

    async def caller_id_hint(self, ctx: TenantContext, phone: str) -> Any: ...

    async def check_booking(self, ctx: TenantContext, booking_ref: str, surname: str) -> Any: ...


@dataclass
class AuthConfig:
    max_attempts: int = 3
    lockout_minutes: float = 60
    use_caller_id_hint: bool = True
    token_ttl_s: float = 900
    signing_key_env: str = ""

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
    identity_token: str | None = None  # signed assertion the MCP server trusts (VERIFIED only)


def mask_ref(ref: str) -> str:
    return ref[0] + "*" * (len(ref) - 3) + ref[-2:] if len(ref) > 3 else "***"


class AuthService(Protocol):
    """Issues identity levels. A VERIFIED result carries a signed token for the MCP server."""

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
    signing_key: bytes = b""
    clock: Callable[[], float] = time.time
    _attempts: dict[str, _Attempts] = field(default_factory=dict)  # Redis in production

    def _state(self, ctx: TenantContext, caller_number: str) -> _Attempts:
        return self._attempts.setdefault(ctx.key("auth", caller_number), _Attempts())

    def is_locked(self, ctx: TenantContext, caller_number: str) -> bool:
        return self._state(ctx, caller_number).locked_until > self.clock()

    async def identify_by_caller_id(self, ctx: TenantContext, caller_number: str) -> AuthResult:
        with tracing.span("auth.caller_id_hint", "auth", caller=tracing.mask(caller_number, 3)) as sp:
            result = await self._hint(ctx, caller_number)
            sp.set(level=result.level.label)
            return result

    async def _hint(self, ctx: TenantContext, caller_number: str) -> AuthResult:
        if not self.config.use_caller_id_hint or not caller_number:
            return AuthResult(IdentityLevel.UNKNOWN, "unknown")
        found = await self.lookup.caller_id_hint(ctx, caller_number)
        if found.status not in ("ok", "stale") or not found.data:
            return AuthResult(IdentityLevel.UNKNOWN, "unknown")
        first = found.data[0]
        masked = {"flight": first["flight"], "ref_masked": first["ref_masked"], "bookings_on_number": len(found.data)}
        return AuthResult(IdentityLevel.LIKELY, "likely", masked=masked, data_as_of=found.as_of)

    async def verify(self, ctx: TenantContext, caller_number: str, booking_ref: str, surname: str) -> AuthResult:
        with tracing.span("auth.verify", "auth", booking=tracing.mask(booking_ref)) as sp:
            result = await self._verify(ctx, caller_number, booking_ref, surname)
            sp.set(outcome=result.outcome, level=result.level.label, attempts_left=result.attempts_left)
            return result

    async def _verify(self, ctx: TenantContext, caller_number: str, booking_ref: str, surname: str) -> AuthResult:
        state = self._state(ctx, caller_number)
        if self.is_locked(ctx, caller_number):
            return AuthResult(IdentityLevel.UNKNOWN, "locked", attempts_left=0)
        ref = "".join(booking_ref.split()).upper()
        found = await self.lookup.check_booking(ctx, ref, surname.strip())
        if found.status not in ("ok", "stale"):
            # Our side could not check: not the caller's fault, so no attempt is used up.
            return AuthResult(IdentityLevel.UNKNOWN, "unavailable",
                              attempts_left=self.config.max_attempts - state.failures)
        if found.data.get("match"):
            state.failures = 0
            booking = found.data["booking"]
            token = identity_token.issue(self.signing_key, ctx.tenant_id, ctx.conversation_id,
                                         IdentityLevel.VERIFIED, booking["ref"], self.config.token_ttl_s)
            return AuthResult(IdentityLevel.VERIFIED, "verified", booking=booking, verified_by="booking_ref+surname",
                              data_as_of=found.as_of if found.status == "stale" else None, identity_token=token)
        state.failures += 1
        if state.failures >= self.config.max_attempts:
            state.locked_until = self.clock() + self.config.lockout_minutes * 60
            state.failures = 0
            return AuthResult(IdentityLevel.UNKNOWN, "locked", attempts_left=0)
        return AuthResult(IdentityLevel.UNKNOWN, "failed", attempts_left=self.config.max_attempts - state.failures)
