import asyncio
from types import SimpleNamespace as NS

from zingly_auth import AuthConfig, DefaultAuthService
from zingly_core import IdentityLevel, TenantContext

BOOKING = {"ref": "ABC123", "surname": "Smith", "flight": "AT123", "phone": "+44"}


class Lookup:
    def __init__(self, status="ok"):
        self.status = status

    async def find_by_phone(self, ctx, phone):
        return NS(status="ok", data=[BOOKING] if phone == "+44" else [], as_of=None)

    async def get_booking(self, ctx, ref):
        if self.status != "ok":
            return NS(status=self.status, data=None, as_of=None)
        return NS(status="ok", data=BOOKING, as_of=None) if ref == "ABC123" else NS(status="not_found", data=None, as_of=None)


A = TenantContext("atlantica")
run = asyncio.run


def test_caller_id_gives_likely_with_masked_summary_only():
    auth = DefaultAuthService(AuthConfig(), Lookup())
    res = run(auth.identify_by_caller_id(A, "+44"))
    assert res.level is IdentityLevel.LIKELY and res.booking is None
    assert res.masked == {"flight": "AT123", "ref_masked": "A***23", "bookings_on_number": 1}


def test_verify_with_reference_and_surname():
    auth = DefaultAuthService(AuthConfig(), Lookup())
    res = run(auth.verify(A, "+1", "abc 123", " smith "))
    assert res.level is IdentityLevel.VERIFIED and res.booking["ref"] == "ABC123"


def test_wrong_ref_and_wrong_surname_look_identical_then_lock():
    auth = DefaultAuthService(AuthConfig(max_attempts=3), Lookup())
    r1 = run(auth.verify(A, "+1", "ZZZ999", "Smith"))   # does not exist
    r2 = run(auth.verify(A, "+1", "ABC123", "Jones"))   # exists, wrong surname
    assert (r1.outcome, r2.outcome) == ("failed", "failed")
    assert run(auth.verify(A, "+1", "ABC123", "Jones")).outcome == "locked"
    assert run(auth.verify(A, "+1", "ABC123", "Smith")).outcome == "locked"  # even with right details
    assert not auth.is_locked(TenantContext("nordica"), "+1")                # lockout is per tenant


def test_backend_outage_does_not_use_up_an_attempt():
    auth = DefaultAuthService(AuthConfig(max_attempts=1), Lookup(status="unavailable"))
    assert run(auth.verify(A, "+1", "ABC123", "Smith")).outcome == "unavailable"
    assert not auth.is_locked(A, "+1")
