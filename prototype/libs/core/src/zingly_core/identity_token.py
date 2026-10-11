"""Signed identity assertion (design: identity is issued by the Auth service, never by a model).

The Auth service signs ``{tenant, conversation, level, booking_ref, exp}`` after it verifies a
caller. The MCP server only trusts a level carried by a valid token, and booking-scoped tools
(rebook, get_booking) only act on the booking named in it. Format: ``<base64url payload>.<hex
HMAC-SHA256>``. Production: asymmetric keys (KMS), short expiry, rotation, audience claim.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from dataclasses import dataclass

from zingly_core.identity import IdentityLevel


@dataclass(frozen=True)
class IdentityClaims:
    tenant_id: str
    conversation_id: str
    level: IdentityLevel
    booking_ref: str | None
    expires_at: float

    @classmethod
    def anonymous(cls, tenant_id: str) -> "IdentityClaims":
        return cls(tenant_id, "", IdentityLevel.UNKNOWN, None, 0)


class InvalidToken(ValueError):
    pass


def signing_key(tenant_id: str, env_name: str | None = None) -> bytes:
    """Per-tenant key from the environment; a fixed dev key only when none is set."""
    name = env_name or f"ZINGLY_IDENTITY_KEY_{tenant_id.upper()}"
    return (os.environ.get(name) or f"dev-only-identity-key-{tenant_id}").encode()


def issue(key: bytes, tenant_id: str, conversation_id: str, level: IdentityLevel,
          booking_ref: str | None, ttl_s: float = 900) -> str:
    payload = {"t": tenant_id, "c": conversation_id, "l": int(level), "b": booking_ref,
               "exp": round(time.time() + ttl_s)}
    body = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode().rstrip("=")
    sig = hmac.new(key, body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{sig}"


def verify(key: bytes, token: str, tenant_id: str) -> IdentityClaims:
    try:
        body, sig = token.rsplit(".", 1)
    except ValueError:
        raise InvalidToken("malformed")
    expected = hmac.new(key, body.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, sig):
        raise InvalidToken("bad signature")
    payload = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    if payload["t"] != tenant_id:
        raise InvalidToken("token issued for another tenant")
    if payload["exp"] < time.time():
        raise InvalidToken("expired")
    return IdentityClaims(payload["t"], payload["c"], IdentityLevel(payload["l"]), payload["b"], payload["exp"])
