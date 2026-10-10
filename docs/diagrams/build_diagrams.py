"""Regenerate the three detailed diagrams:  python docs/diagrams/build_diagrams.py

The high-level architecture (Figure 1) is hand-drawn and lives next to these as
high-level-architecture.webp. Everything here uses only the standard library.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from svgkit import SVG, ZONES, ACCENT  # noqa: E402

OUT = os.path.dirname(os.path.abspath(__file__))
RED, AMBER, GREEN = ZONES["danger"][0], ZONES["genesys"][0], ZONES["airline"][0]


# ------------------------------------------------------------------ Figure 2: identification
def identification():
    s = SVG(1240, 660, "Figure 2 · Caller identification, on demand",
            "Verified only when a request needs it. Genesys passes the caller-ID match as a free hint. The Identity service issues the level, never the model.")
    s.box(28, 120, 150, 56, "Call connects", "welcome + consent played")
    s.box(218, 120, 200, 56, "Caller-ID check", "free hint from Genesys", accent=True)
    s.arrow([(178, 148), (218, 148)])
    s.box(470, 90, 220, 56, "Likely", "caller ID matches a booking", kind="genesys")
    s.box(470, 160, 220, 56, "Unknown", "public status and FAQ only")
    s.arrow([(418, 140), (444, 140), (444, 118), (470, 118)], label="match", lx=432, ly=100)
    s.arrow([(418, 156), (444, 156), (444, 188), (470, 188)], label="no match", lx=420, ly=206, anchor="start")
    s.box(740, 120, 230, 56, "Ask booking ref + surname", "only when the request needs it", accent=True)
    s.arrow([(690, 118), (715, 118), (715, 148), (740, 148)])
    s.path("M690,188 H715 V148", end=False)
    s.box(1010, 120, 200, 56, "Identity service", "checks against the booking", accent=True)
    s.arrow([(970, 148), (1010, 148)], color=ACCENT)

    s.box(1010, 280, 200, 60, "Verified", "rebook within policy", kind="airline")
    s.arrow([(1110, 176), (1110, 280)], color=GREEN, label="match", lx=1120, ly=232, anchor="start")
    s.box(740, 280, 230, 60, "Failed attempt", "retry, up to 3 times", kind="danger")
    s.arrow([(1040, 176), (1040, 230), (855, 230), (855, 280)], color=RED, label="no match", lx=950, ly=224)
    s.box(740, 400, 230, 76, "Locked for 1 hour", "public info, or a person.\nAgent told: not verified", kind="danger")
    s.arrow([(855, 340), (855, 400)], color=RED, label="3rd failure", lx=863, ly=374, anchor="start")

    s.box(1010, 400, 200, 60, "Higher-risk request?", "split booking · minors · refund")
    s.arrow([(1110, 340), (1110, 400)])
    s.box(1010, 500, 200, 64, "Extra check", "app approval (OIDC login)\nor SMS one-time code", accent=True)
    s.arrow([(1110, 460), (1110, 500)], label="yes", lx=1120, ly=486, anchor="start")
    s.box(740, 500, 230, 64, "Handoff as Verified", "denied or timed out →\nagent checks in person", kind="genesys")
    s.arrow([(1010, 532), (970, 532)], color=AMBER, label="denied", lx=990, ly=524)
    s.box(470, 500, 230, 64, "Strongly verified", "higher-risk actions allowed", kind="airline")
    s.arrow([(1110, 564), (1110, 596), (585, 596), (585, 564)], color=GREEN, label="approved", lx=850, ly=590)

    s.zone(28, 240, 420, 150, "Who can rebook by voice?", "neutral")
    for i, t in enumerate(["Only a Verified caller, within policy, for the",
                           "passengers on that booking. Harm is limited:",
                           "an involuntary move with no cash value,",
                           "announced to the booking's own phone and",
                           "email, and reversible by an agent."]):
        s.text(44, 282 + i * 17, t, size=10.5, color="#0F172A")
    s.zone(28, 410, 420, 150, "Fraud controls", "danger")
    for i, t in enumerate(["Velocity limits per caller ID and booking",
                           "Detect many references tried from many numbers",
                           "Never confirm that a booking reference exists",
                           "The model never decides identity: the service",
                           "issues a level and a short-lived session token"]):
        s.text(44, 452 + i * 17, t, size=10.5, color="#0F172A")
    s.text(28, 640, "Caller ID = number shown by the phone network · OTP = one-time SMS code · OIDC = the login standard the airline app uses",
           size=10.5, color="#475569")
    s.save(f"{OUT}/identification.svg")


# ------------------------------------------------------------------ Figure 3: reservation system
def reservation():
    s = SVG(1240, 630, "Figure 3 · Protecting the rate-limited reservation system",
            "Callers are correlated: keep a copy per flight, ask the PSS once for many callers, queue the rest by priority.")
    s.box(28, 290, 120, 60, "Domain agent", "tool call")
    s.box(168, 290, 132, 60, "Policy engine", "authorise ·\nguardrails")
    s.box(320, 290, 150, 60, "MCP server", "status · options\nrebook · notify", accent=True)
    s.arrow([(148, 320), (168, 320)])
    s.arrow([(300, 320), (320, 320)])
    s.arrow([(470, 320), (524, 320)], color=GREEN, width=2)

    s.zone(508, 240, 560, 200, "Connector layer · rate limiting lives here", "airline")
    s.box(524, 290, 150, 70, "Saved copy", "status · manifest · options\nfresh for a set time (TTL)", kind="zingly")
    s.box(700, 290, 150, 70, "Ask once", "1,000 callers on AT123\n→ 1 PSS query", kind="zingly")
    s.box(876, 290, 176, 70, "Priority lanes", "P0 book 40% · P1 find booking 30%\nP2 options 20% · P3 status 10%", kind="zingly")
    s.arrow([(674, 325), (700, 325)], label="miss", lx=687, ly=316, color=ACCENT)
    s.arrow([(850, 325), (876, 325)], color=ACCENT)
    s.text(524, 392, "Circuit breaker per endpoint: opens at 50% errors over 10 s, or p95 above 2 s.", size=10.5, color="#475569")
    s.text(524, 410, "Reads retry once, only if it fits the turn budget. Writes are never retried blindly.", size=10.5, color="#475569")
    s.box(1110, 290, 100, 70, "PSS", "≈ 50 TPS\n(assumed)", kind="airline")
    s.arrow([(1052, 325), (1110, 325)], color=GREEN, width=2)

    s.zone(508, 84, 560, 112, "Before the wave · prepare on the event", "airline")
    s.box(524, 120, 130, 56, "IROPS feed", "flight.cancelled")
    s.box(690, 120, 170, 56, "Pre-warm worker", "manifest once · options\nper route and cabin")
    s.arrow([(654, 148), (690, 148)], label="event", lx=672, ly=140)
    s.arrow([(775, 176), (775, 214), (599, 214), (599, 290)], color=ACCENT)
    s.text(690, 208, "writes", size=10.5, color=ACCENT, halo=True)
    s.arrow([(860, 148), (964, 148), (964, 290)], color=GREEN, dashed=True)
    s.text(972, 230, "pre-warm reads\nuse the P3 lane", size=10.5, color=GREEN, anchor="start", halo=True)

    s.zone(28, 392, 460, 100, "What is safe to keep", "neutral")
    for i, t in enumerate(["Flight status: refreshed by events, 30 s safety limit",
                           "Manifest: until the flight closes · options: 20–30 s, offer only",
                           "Booking: for the call only · holds and commits: never kept"]):
        s.text(44, 430 + i * 17, t, size=10.5, color="#0F172A")

    s.zone(28, 510, 1184, 76, "When a lane is full, the caller still gets an answer", "danger")
    for i, (t, sub) in enumerate([("P0 → deferred commit", "recorded, booked later, SMS"),
                                  ("P1 → booking snapshot", "labelled \"as of 14:02\""),
                                  ("P2 → indicative copy", "re-checked live before booking"),
                                  ("P3 → saved copy only", "event-fed status")]):
        s.box(44 + i * 293, 538, 275, 40, t, sub, kind="danger", title_size=11.5)
    s.text(28, 614, "PSS = airline reservation system · TTL = how long a saved answer stays fresh · P0–P3 = priority 0 (highest) to 3 · IROPS = airline disruption events",
           size=10.5, color="#475569")
    s.save(f"{OUT}/reservation-protection.svg")


# ------------------------------------------------------------------ Figure 4: handover + callback
def handover():
    s = SVG(1240, 500, "Figure 4 · Handover with context, and callback when all agents are busy",
            "The bot returns an outcome and context. Genesys owns the queue, the wait time and the callback, so nothing is custom-built.")
    s.box(28, 110, 150, 56, "Zingly bot", "returns AGENT_HANDOVER", accent=True)
    s.box(230, 110, 190, 56, "Architect flow resumes", "reads the call attributes", kind="genesys")
    s.box(470, 110, 170, 56, "Wait time check", "EWT · agents available", kind="genesys", accent=True)
    s.arrow([(178, 138), (230, 138)], color=ACCENT, width=2)
    s.arrow([(420, 138), (470, 138)], color=AMBER, width=2)
    s.box(700, 60, 190, 56, "Skill queue", "language · tier · intent", kind="genesys")
    s.box(940, 60, 250, 56, "Agent desktop", "screen-pop: who · why · what was tried", kind="genesys", accent=True)
    s.arrow([(640, 132), (670, 132), (670, 88), (700, 88)], color=AMBER, label="short wait", lx=612, ly=76, anchor="start")
    s.arrow([(890, 88), (940, 88)], color=AMBER, width=2)
    s.box(700, 190, 190, 56, "Offer a callback", "keep place · confirm number", kind="genesys")
    s.box(940, 190, 250, 56, "Callback created", "same attributes attached", kind="genesys")
    s.arrow([(640, 144), (670, 144), (670, 218), (700, 218)], color=AMBER, label="long wait or all busy", lx=548, ly=236, anchor="start")
    s.arrow([(890, 218), (940, 218)], color=AMBER)
    s.box(700, 290, 190, 56, "SMS confirmation", "via Twilio")
    s.box(940, 290, 250, 56, "Agent takes the callback", "the same screen-pop appears", kind="genesys", accent=True)
    s.arrow([(795, 246), (795, 290)])
    s.arrow([(1065, 246), (1065, 290)], color=AMBER, width=2)

    s.zone(28, 210, 450, 270, "Handover payload (call attributes)", "zingly")
    for i, t in enumerate(["conversation_status = AGENT_HANDOVER",
                           "category · subcategory · summary",
                           "who the caller is and how they were verified",
                           "booking · flight · disruption reason",
                           "attempted actions, result and booking state",
                           "  e.g. rebook to AT127: FAILED, booking unchanged",
                           "handoffId: sensitive detail is fetched by a Data",
                           "  Action under OAuth, not stored in attributes"]):
        s.text(46, 252 + i * 24, t, size=11, color="#0F172A")
    s.zone(700, 380, 490, 100, "Why this works", "neutral")
    for i, t in enumerate(["Genesys already owns the queue, the wait time and callbacks.",
                           "The agent never asks for the booking reference again.",
                           "A callback carries the same context as a live transfer."]):
        s.text(716, 418 + i * 18, t, size=10.5, color="#0F172A")
    s.save(f"{OUT}/handover-callback.svg")


if __name__ == "__main__":
    identification()
    reservation()
    handover()
    print("ok")
