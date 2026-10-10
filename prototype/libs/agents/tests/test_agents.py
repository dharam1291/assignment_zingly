import asyncio
from types import SimpleNamespace as NS

from zingly_agents import AgentState, AgentTurn, AgentsConfig, build_supervisor
from zingly_core import IdentityLevel, TenantContext

CTX = TenantContext("atlantica", "conv-1")
BOOKING = {"ref": "ABC123", "surname": "Smith", "flight": "AT123", "cabin": "economy", "origin": "LHR", "destination": "BOS"}
ALTS = [{"flight": "AT127", "departure": "14:05"}, {"flight": "AT131", "departure": "19:40"}]


class Tools:
    def __init__(self, rebook_status="ok", alts_status="ok"):
        self.rebook_status, self.alts_status = rebook_status, alts_status
        self.calls = []

    async def call(self, ctx, name, args, level):
        self.calls.append((name, level))
        if name == "get_flight_status":
            return NS(status="ok", source="saved_copy", as_of=0, detail="",
                      data={"flight": args["flight"], "status": "CANCELLED", "reason": "weather",
                            "origin": "LHR", "destination": "BOS"})
        if name == "get_alternatives":
            return NS(status=self.alts_status, data=ALTS, source="saved_copy", as_of=0, detail="")
        if name == "rebook":
            assert level >= IdentityLevel.VERIFIED
            data = {"confirmation": "RB00001"} if self.rebook_status == "ok" else {}
            return NS(status=self.rebook_status, data=data, source="pss", as_of=None, detail="")
        raise AssertionError(name)


class Auth:
    async def identify_by_caller_id(self, ctx, number):
        if number == "+44":
            return NS(level=IdentityLevel.LIKELY, masked={"flight": "AT123", "ref_masked": "A***23"})
        return NS(level=IdentityLevel.UNKNOWN, masked=None)

    async def verify(self, ctx, number, ref, surname):
        ok = ref == "ABC123" and surname.lower() == "smith"
        return NS(outcome="verified" if ok else "failed", booking=BOOKING if ok else None,
                  verified_by="booking_ref+surname", data_as_of=None, level=IdentityLevel.VERIFIED)


CFG = AgentsConfig.from_config({"airports": {"BOS": "Boston"},
                                "faq": [{"keywords": ["bag", "baggage"], "answer": "Bags are re-checked automatically."}]})


class Call:
    """Drives the supervisor the way the service does, keeping identity from replies."""

    def __init__(self, tools=None, number="+1"):
        self.tools = tools or Tools()
        self.sup = build_supervisor(CFG, self.tools, Auth(), ["rebooking", "flight_status", "faq"])
        self.state, self.level, self.number = AgentState(), IdentityLevel.UNKNOWN, number

    def say(self, agent, text, yes_no=None):
        reply = asyncio.run(self.sup.handle(CTX, agent, AgentTurn(text, self.level, self.number, yes_no), self.state))
        self.level = reply.identity or self.level
        return reply


def test_full_rebooking_with_likely_hint_then_verification():
    c = Call(number="+44")
    r = c.say("rebooking", "my flight was cancelled")
    assert "ending 23 on flight AT123" in r.text and r.pending_question == "booking_ref"
    assert c.level is IdentityLevel.LIKELY
    assert c.say("rebooking", "A B C 1 2 3").pending_question == "surname"
    r = c.say("rebooking", "it's Smith")
    assert c.level is IdentityLevel.VERIFIED
    assert "14:05 on AT127 and 19:40 on AT131" in r.text and "Boston" in r.text
    r = c.say("rebooking", "the first one")
    assert r.pending_question == "confirm_rebook" and not r.interruptible
    r = c.say("rebooking", "yes", yes_no="yes")
    assert r.done and "RB00001" in r.text
    assert [a["action"] for a in c.state.attempted] == ["verify_identity", "get_alternatives", "rebook"]


def test_deferred_commit_wording_when_p0_lane_is_full():
    c = Call(tools=Tools(rebook_status="deferred"))
    c.say("rebooking", "booking ABC123 was cancelled")
    c.say("rebooking", "Smith")
    c.say("rebooking", "19:40")
    r = c.say("rebooking", "yes", yes_no="yes")
    assert "within 30 minutes" in r.text and r.done


def test_failed_rebook_hands_over_with_attempts_recorded():
    c = Call(tools=Tools(rebook_status="unavailable"))
    c.say("rebooking", "ABC123"); c.say("rebooking", "Smith"); c.say("rebooking", "second")
    r = c.say("rebooking", "yes", yes_no="yes")
    assert r.handover["subcategory"] == "rebook_failed"
    assert c.state.attempted[-1]["result"] == "unavailable"


def test_side_question_resumes_the_open_task():
    c = Call()
    c.say("rebooking", "ABC123"); c.say("rebooking", "Smith")
    r = c.say("faq", "what happens to my bag?")
    assert "re-checked" in r.text and "back to your rebooking" in r.text
    assert r.pending_question == "choose_option" and c.state.active == "rebooking"
    assert c.say("rebooking", "first").pending_question == "confirm_rebook"


def test_flight_status_needs_no_identity_and_labels_saved_copy():
    c = Call()
    r = c.say("flight_status", "status of AT123?")
    assert "AT123 to Boston is cancelled" in r.text and "as of" in r.text and r.done
    assert c.tools.calls == [("get_flight_status", IdentityLevel.UNKNOWN)]
