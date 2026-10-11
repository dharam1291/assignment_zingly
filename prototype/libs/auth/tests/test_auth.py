import asyncio
from types import SimpleNamespace as NS

from zingly_auth import AuthConfig, DefaultAuthService
from zingly_core import IdentityLevel, TenantContext, identity_token

BOOKING = {"ref": "ABC123", "surname": "Smith", "flight": "AT123", "phone": "+44"}
KEY = identity_token.signing_key("atlantica")


class Lookup:
    """Behaves like the MCP tools: masked hint; match/no-match without saying which part failed."""

    def __init__(self, status="ok"):
        self.status = status

    async def caller_id_hint(self, ctx, phone):
        data = [{"flight": "AT123", "ref_masked": "A***23"}] if phone == "+44" else []
        return NS(status="ok", data=data, as_of=None)

    async def check_booking(self, ctx, ref, surname):
        if self.status != "ok":
            return NS(status=self.status, data=None, as_of=None)
        ok = ref == "ABC123" and surname.lower() == "smith"
        return NS(status="ok", data={"match": True, "booking": BOOKING} if ok else {"match": False}, as_of=None)


A = TenantContext("atlantica", "conv-1")
run = asyncio.run


def auth(**kw):
    return DefaultAuthService(AuthConfig(**kw), Lookup(), KEY)


def test_caller_id_gives_likely_with_masked_summary_only():
    res = run(auth().identify_by_caller_id(A, "+44"))
    assert res.level is IdentityLevel.LIKELY and res.booking is None and res.identity_token is None
    assert res.masked == {"flight": "AT123", "ref_masked": "A***23", "bookings_on_number": 1}


def test_verify_issues_a_token_scoped_to_the_booking():
    res = run(auth().verify(A, "+1", "abc 123", " smith "))
    assert res.level is IdentityLevel.VERIFIED and res.booking["ref"] == "ABC123"
    claims = identity_token.verify(KEY, res.identity_token, "atlantica")
    assert claims.booking_ref == "ABC123" and claims.conversation_id == "conv-1"


def test_wrong_ref_and_wrong_surname_look_identical_then_lock():
    svc = auth(max_attempts=3)
    r1 = run(svc.verify(A, "+1", "ZZZ999", "Smith"))
    r2 = run(svc.verify(A, "+1", "ABC123", "Jones"))
    assert (r1.outcome, r2.outcome) == ("failed", "failed")
    assert run(svc.verify(A, "+1", "ABC123", "Jones")).outcome == "locked"
    assert run(svc.verify(A, "+1", "ABC123", "Smith")).outcome == "locked"
    assert not svc.is_locked(TenantContext("nordica"), "+1")


def test_backend_outage_does_not_use_up_an_attempt():
    svc = DefaultAuthService(AuthConfig(max_attempts=1), Lookup(status="unavailable"), KEY)
    assert run(svc.verify(A, "+1", "ABC123", "Smith")).outcome == "unavailable"
    assert not svc.is_locked(A, "+1")
