from __future__ import annotations

from dataclasses import dataclass, field, fields
from typing import Any, Mapping


@dataclass
class Wording:
    """Approved wording. Tenants override any line under ``[tenants.<id>.agents.wording]``."""

    likely_summary: str = "I can see a booking ending {ref_tail} on flight {flight}."
    ask_booking_ref: str = "To make changes I need to verify you. What's your six-character booking reference?"
    ask_ref_again: str = "Sorry, I didn't catch a six-character reference. Could you say it again?"
    ask_surname: str = "Thanks. And the lead passenger's surname?"
    verified: str = "Thank you, you're verified."
    verify_failed: str = "Sorry, I couldn't verify those details. Let's try once more: what's the booking reference?"
    verify_locked: str = "I'm not able to verify you right now, so I'll pass you to a colleague who can help."
    verify_unavailable: str = "I'm having trouble checking that right now, so I'll pass you to a colleague."
    not_disrupted: str = "Your flight {flight} is {status}, so there's nothing to change."
    offer_options: str = "The next flights I can see to {destination} are {options}."
    choose_option: str = "Which would you like: {choices}?"
    choose_single: str = "Would you like that one?"
    confirm_rebook: str = ("Just to confirm: move booking ending {ref_tail} from {from_flight} to {to_flight}, "
                           "departing {departure}. Shall I go ahead?")
    rebooked: str = ("Done. You're booked on {to_flight} departing {departure}. "
                     "Your confirmation, {confirmation}, is on its way by text.")
    seat_gone: str = "That flight has just filled up."
    no_options: str = "I can't see any alternatives I can book for you, so I'll pass you to a colleague."
    other_options: str = "OK. I'll pass you to a colleague who can look at other options for you."
    anything_else: str = "Is there anything else I can help with?"
    rebook_failed: str = ("I wasn't able to complete that change and your booking is unchanged. "
                          "I'll pass you to a colleague with everything we've done so far.")
    ask_flight_number: str = "Which flight number is it?"
    status_line: str = "{flight} to {destination} is {status}."
    status_cancelled_hint: str = "I can help you rebook if you like."
    faq_no_answer: str = "I don't have that answer, so I'll pass you to a colleague."
    resume: str = "Now, back to your {task}:"
    # Lane fallbacks (design §5 table): what the caller hears when a lane is full.
    p0_deferred: str = ("I've noted your choice of {to_flight} at {departure}. We're confirming it now, "
                        "and you'll get a text within 30 minutes.")
    p1_as_of: str = "This is as of {as_of}, and I'll check again before I change anything."
    p2_as_of: str = "Availability changes quickly, so I'll check before I book."
    p3_as_of: str = "That's as of {as_of}."


@dataclass
class AgentsConfig:
    wording: Wording = field(default_factory=Wording)
    airports: dict[str, str] = field(default_factory=dict)
    max_options: int = 2
    faq: list[dict] = field(default_factory=list)  # [{keywords=[...], answer="..."}]

    @classmethod
    def from_config(cls, section: Mapping[str, Any]) -> "AgentsConfig":
        names = {f.name for f in fields(Wording)}
        overrides = {k: v for k, v in section.get("wording", {}).items() if k in names}
        return cls(Wording(**overrides), dict(section.get("airports", {})), int(section.get("max_options", 2)),
                   list(section.get("faq", [])))

    def place(self, code: str) -> str:
        return self.airports.get(code, code)
