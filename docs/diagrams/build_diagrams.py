"""Regenerate every architecture diagram:  python docs/diagrams/build_diagrams.py"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from svgkit import SVG, Seq, ACCENT, LINE, ZONES, SUB, INK  # noqa: E402

OUT = os.path.dirname(os.path.abspath(__file__))
RED = ZONES["danger"][0]
AMBER = ZONES["genesys"][0]
GREEN = ZONES["airline"][0]


# ---------------------------------------------------------------- 01 overview (business view)
def solution_overview():
    s = SVG(1240, 604, "Figure 1 · The solution on a page",
            "Twilio keeps the phone lines, Atlantica keeps its systems of record. Zingly adds the voice agent in between.")
    # caller
    s.box(28, 196, 150, 84, "Passenger", "\"My flight was\ncancelled, rebook me\"")
    # Twilio
    s.zone(208, 136, 196, 204, "Twilio · unchanged", "twilio")
    s.box(224, 186, 164, 112, "Phone network", "same numbers,\nsame carrier contract,\ncall routing as today")
    s.arrow([(178, 238), (224, 238)], color=ACCENT, width=2)
    # Zingly
    s.zone(440, 96, 440, 284, "Zingly voice agent · EU region", "zingly")
    steps = [("Understand", "streaming speech ↔ text, barge-in, < 1.6 s replies"),
             ("Identify", "booking ref + surname; app push for risky changes"),
             ("Decide", "options within Atlantica's policy, refund always offered"),
             ("Act", "rebook and confirm by SMS, or hand off to a human")]
    for i, (t, sub) in enumerate(steps):
        y = 132 + i * 60
        s.raw(f'<rect x="456" y="{y}" width="408" height="48" rx="8" fill="#fff" stroke="{ACCENT}" stroke-width="1.3"/>')
        s.badge(480, y + 24, i + 1)
        s.text(500, y + 20, t, size=12.5, weight=650, color=INK)
        s.text(500, y + 37, sub, size=10.5, color=SUB)
        if i < 3:
            s.path(f"M480,{y + 34} V{y + 60 + 14}", color=ACCENT, end=False)
    s.arrow([(388, 238), (440, 238)], color=ACCENT, width=2, both=True)
    s.text(414, 228, "audio", size=10, color=ACCENT, anchor="middle", halo=True)
    # outcomes
    s.zone(920, 96, 292, 284, "Outcome for the caller", "neutral")
    s.box(936, 132, 260, 96, "Rebooked by phone", "new itinerary read back,\nSMS to the contact on the booking,\nno queue, no agent needed", kind="airline")
    s.box(936, 252, 260, 112, "Human agent, full context", "agent screen opens with who,\nwhich flight and what was tried.\nAll agents busy: a callback\nthat keeps the caller's place", kind="genesys")
    s.arrow([(880, 180), (936, 180)], color=GREEN, width=2)
    s.arrow([(880, 308), (936, 308)], color=AMBER, width=2)
    # Atlantica systems
    s.zone(440, 412, 772, 96, "Atlantica systems of record · unchanged", "airline")
    s.box(456, 444, 260, 48, "Reservation system (PSS)", "rate-limited: protected, never overrun", kind="airline")
    s.box(736, 444, 200, 48, "Disruption feed", "cancellations pre-warm answers")
    s.box(956, 444, 240, 48, "Genesys contact centre", "agents, queues, callbacks", kind="genesys")
    s.arrow([(680, 380), (680, 444)], color=GREEN, both=True)
    s.text(670, 400, "cache + priority queue in front", size=10.5, color=GREEN, halo=True, anchor="end")
    s.arrow([(836, 444), (836, 380)])
    s.text(844, 404, "events", size=10.5, color=SUB, halo=True)
    s.arrow([(1076, 364), (1076, 444)], color=AMBER, both=True)
    # guardrails
    s.zone(28, 530, 1184, 56, "Guardrails", "danger", label_x=48)
    s.text(150, 563, "No single factor authorises a change  ·  The AI talks, the tools state facts  ·  "
                     "Every failure ends with a human, never a dropped call  ·  Passenger data stays in the EU",
           size=11.5, weight=600, color=INK)
    s.save(f"{OUT}/01-solution-overview.svg")


# ---------------------------------------------------------------- 02 context
def system_context():
    s = SVG(1240, 724, "Figure 2 · System context",
            "Zingly sits behind Twilio as the media + brain; Atlantica's PSS and Genesys stay systems of record. Tenant = airline.")
    # caller
    s.box(24, 196, 124, 56, "Passenger", "PSTN / mobile")
    # Twilio
    s.zone(180, 90, 220, 396, "Twilio · CPaaS", "twilio")
    s.box(196, 120, 188, 48, "DIDs · PSTN ingress", "subaccount per tenant")
    s.box(196, 196, 188, 56, "Programmable Voice", "<Connect><Stream> WSS")
    s.box(196, 282, 188, 48, "Fallback TwiML", "static · outside Zingly", kind="danger")
    s.box(196, 372, 188, 56, "SIP egress", "<Dial><Sip> to Genesys")
    s.arrow([(148, 214), (164, 214), (164, 144), (196, 144)])
    s.arrow([(290, 168), (290, 196)])
    s.arrow([(290, 252), (290, 282)], color=RED, dashed=True, label="WSS drop", lx=298, ly=271, anchor="start")
    s.arrow([(290, 330), (290, 372)], color=RED, dashed=True)
    s.arrow([(196, 238), (188, 238), (188, 400), (196, 400)], label="", lx=0, ly=0)
    s.text(182, 322, "transfer", size=10, color=SUB, anchor="end")
    # Zingly
    s.zone(500, 90, 340, 396, "Zingly Voice Platform", "zingly")
    s.box(516, 112, 308, 46, "Control plane · global, no PII", "tenant registry · policy packs · prompts · flags")
    s.zone(516, 172, 308, 300, "EU cell · Atlantica home cell", "zingly", dashed=True)
    s.box(532, 206, 276, 48, "Media Gateway", "WSS · VAD · barge-in · call control", accent=True)
    s.box(532, 270, 276, 48, "Dialog Orchestrator", "state machine + LLM · Policy Engine", accent=True)
    s.box(532, 342, 118, 68, "Context API", "handoff store\nTTL 15 min / 24 h", title_size=12)
    s.box(680, 342, 128, 68, "Read model", "cache · coalescing\nadmission lanes", title_size=12)
    s.arrow([(670, 254), (670, 270)], color=ACCENT, both=True)
    s.arrow([(591, 318), (591, 342)])
    s.arrow([(744, 318), (744, 342)])
    s.text(599, 334, "writes", size=10, color=SUB)
    s.text(752, 334, "tools", size=10, color=SUB)
    s.arrow([(670, 158), (670, 172)], dashed=True)
    s.text(678, 168, "config", size=10, color=SUB)
    # Twilio <-> Zingly
    s.arrow([(384, 222), (532, 222)], color=ACCENT, both=True, width=2,
            label="webhook (HMAC)\n+ WSS audio μ-law 8k", lx=442, ly=200)
    s.arrow([(532, 246), (384, 246)], label="call control (REST)", lx=442, ly=264)
    # AI vendors
    s.zone(940, 90, 276, 128, "In-region AI vendors", "neutral")
    s.box(956, 120, 244, 82, "STT · LLM · TTS", "primary + secondary per cell\nno retention · no training")
    s.arrow([(808, 230), (888, 230), (888, 161), (956, 161)], label="speech · tokens", lx=848, ly=248)
    # Atlantica
    s.zone(940, 236, 276, 250, "Atlantica Airways", "airline")
    s.box(956, 270, 244, 48, "Notification API + App", "OIDC-signed-in passenger")
    s.box(956, 332, 244, 44, "Reservation system (PSS)", "Amadeus-like · ~50 TPS (assumed)", kind="airline")
    s.box(956, 386, 244, 38, "Ops / IROPS feed")
    s.box(956, 434, 244, 40, "Atlantica IdP", "agent SSO")
    s.arrow([(808, 294), (956, 294)], both=True, label="push · SMS", lx=890, ly=286)
    s.arrow([(808, 354), (956, 354)], color=GREEN, label="mTLS · budgeted", lx=890, ly=346)
    s.arrow([(956, 404), (808, 404)], label="IROPS events", lx=890, ly=396)
    # Genesys
    s.zone(180, 540, 1036, 140, "Genesys Cloud CX · tenant org", "genesys", label_x=700)
    s.box(196, 584, 220, 56, "BYOC Cloud trunk", "SIP/TLS + SRTP")
    s.box(556, 584, 252, 56, "Architect flow + Data Action", "reads UUI → fetches context")
    s.box(956, 584, 244, 56, "Agent desktop", "Script screen-pop · callbacks")
    s.arrow([(370, 428), (370, 584)], color=AMBER, width=2)
    s.text(362, 512, "SIP + UUI = handoffId\nonly (no PII)", size=10.5, color=AMBER, anchor="end", halo=True)
    s.arrow([(416, 612), (556, 612)], label="inbound call", lx=486, ly=604)
    s.arrow([(808, 612), (956, 612)], label="route + screen-pop", lx=882, ly=604)
    s.arrow([(596, 584), (596, 410)], color=ACCENT, width=2)
    s.text(588, 506, "Data Action GET /handoffs/{id}\nOAuth2 client credentials", size=10.5, color=ACCENT, anchor="end", halo=True)
    s.arrow([(665, 318), (665, 584)])
    s.text(673, 506, "EWT · create callback\n(Genesys API, OAuth)", size=10.5, color=SUB, halo=True)
    s.arrow([(1078, 474), (1078, 584)])
    s.text(1086, 520, "agent SSO", size=10.5, color=SUB, halo=True)
    # legend
    s.text(28, 706, "Indigo = real-time voice + context path · Red dashed = failure-only path · Amber = handoff to human",
           size=10.5, color=SUB)
    s.save(f"{OUT}/02-system-context.svg")




# ---------------------------------------------------------------- 02 voice pipeline
STAGES = [  # name, p50, p95, colour
    ("Endpointing", 250, 400, "#A5B4FC"),
    ("STT final", 80, 150, "#818CF8"),
    ("Tool (cache)", 30, 80, "#38BDF8"),
    ("LLM 1st token", 250, 500, "#4F46E5"),
    ("TTS 1st byte", 120, 200, "#7C3AED"),
    ("Media + network", 150, 250, "#94A3B8"),
]


def voice_pipeline():
    s = SVG(1240, 640, "Figure 4 · Voice pipeline and latency budget",
            "Streaming end to end: no stage waits for the previous one to finish. Budget = end of caller speech → first audio byte heard.")
    row_y, bw, bh = 96, 150, 70
    xs = [28 + i * 210 for i in range(6)]
    boxes = [
        ("Caller", "PSTN / mobile", None),
        ("Twilio edge", "Media Streams\n150 / 250 ms", "twilio"),
        ("Media Gateway", "VAD · endpointing\n250 / 400 ms", "zingly"),
        ("Streaming STT", "8 kHz telephony model\n80 / 150 ms", "neutral"),
        ("Orchestrator", "tools 30/80 · LLM 250/500\nPolicy Engine", "zingly"),
        ("Streaming TTS", "μ-law 8 kHz out\n120 / 200 ms", "neutral"),
    ]
    for x, (t, sub, k) in zip(xs, boxes):
        s.box(x, row_y, bw, bh, t, sub, kind=k)
    labels = ["μ-law\n20 ms", "frames", "partials\n+ finals", "tokens", "text"]
    for i in range(5):
        x1, x2 = xs[i] + bw, xs[i + 1]
        s.arrow([(x1, row_y + 22), (x2, row_y + 22)], color=ACCENT, width=2)
        if labels[i]:
            s.text((x1 + x2) / 2, row_y + 6, labels[i], size=10, color=ACCENT, anchor="middle", halo=True)
    # return path
    ry = row_y + bh + 34
    s.arrow([(xs[5] + bw / 2, row_y + bh), (xs[5] + bw / 2, ry), (xs[2] + bw / 2, ry), (xs[2] + bw / 2, row_y + bh)],
            color=ACCENT, width=2)
    s.text((xs[2] + xs[5]) / 2 + bw / 2, ry - 7, "synthesised audio → Twilio media messages + a mark per phrase",
           size=10.5, color=ACCENT, anchor="middle", halo=True)
    s.arrow([(xs[2], row_y + 52), (xs[1] + bw, row_y + 52)], color=ACCENT, width=2)
    s.arrow([(xs[1], row_y + 52), (xs[0] + bw, row_y + 52)], color=ACCENT, width=2)
    s.text((xs[1] + bw + xs[2]) / 2, row_y + 66, "media out", size=10, color=ACCENT, anchor="middle", halo=True)
    s.text((xs[0] + bw + xs[1]) / 2, row_y + 66, "audio", size=10, color=ACCENT, anchor="middle", halo=True)

    # latency bars
    top = 262
    s.text(28, top, "TURN LATENCY BUDGET (ms)", size=10.5, weight=700, color=SUB)
    x0, scale = 120, 0.62
    for lab, idx, y in [("p50", 1, top + 22), ("p95", 2, top + 66)]:
        s.text(x0 - 12, y + 19, lab, size=12, weight=700, color=INK, anchor="end")
        x = x0
        for st in STAGES:
            w = st[idx] * scale
            s.raw(f'<rect x="{x:.1f}" y="{y}" width="{w:.1f}" height="28" fill="{st[3]}" stroke="#fff" stroke-width="1"/>')
            if w > 30:
                dark = st[3] in ("#4F46E5", "#7C3AED", "#818CF8")
                s.text(x + w / 2, y + 18, str(st[idx]), size=10.5, weight=600,
                       color="#fff" if dark else INK, anchor="middle")
            x += w
        total = sum(st[idx] for st in STAGES)
        s.text(x0 + 1600 * scale + 24, y + 19, f"≈ {total} ms", size=12, weight=700, color=INK)
    for ms, lab in [(1000, "p50 target 1.0 s"), (1600, "p95 target 1.6 s")]:
        tx = x0 + ms * scale
        s.raw(f'<line x1="{tx}" y1="{top + 12}" x2="{tx}" y2="{top + 104}" stroke="{RED}" stroke-width="1.2" stroke-dasharray="4 3"/>')
        s.text(tx + 4, top + 118, lab, size=10, color=RED)
    lx = 120
    for st in STAGES:
        s.raw(f'<rect x="{lx}" y="{top + 132}" width="12" height="12" rx="2" fill="{st[3]}"/>')
        s.text(lx + 17, top + 142, st[0], size=10.5, color=SUB)
        lx += len(st[0]) * 6.4 + 42

    # mechanism panels
    py = 440
    panels = [
        (28, "Barge-in", "zingly", [
            ("Caller talks", "over TTS", None),
            ("VAD ≥ 200 ms", "+ STT partial", None),
            ("send clear", "to Twilio", "zingly"),
            ("mark → keep", "only heard words", None)],
         "Coughs and line echo are filtered by the dual check.",
         "Disclosure and itinerary read-back are non-interruptible."),
        (628, "Masking a slow tool", "airline", [
            ("tool ETA", "> 700 ms", None),
            ("play cached", "filler phrase", "airline"),
            ("PSS call via", "admission lane", None),
            ("stream answer", "when it lands", None)],
         "No dead air while the PSS answers.",
         "Speculative LLM start on stable partials saves ~100–200 ms."),
    ]
    for px, title, kind, steps, f1, f2 in panels:
        s.zone(px, py, 584, 176, title, kind)
        bx = px + 16
        for i, (t, sub, k) in enumerate(steps):
            s.box(bx, py + 40, 124, 60, t, sub, kind=k, title_size=11.5)
            if i < 3:
                s.arrow([(bx + 124, py + 70), (bx + 144, py + 70)])
            bx += 144
        s.text(px + 16, py + 130, f1, size=10.5, color=SUB)
        s.text(px + 16, py + 148, f2, size=10.5, color=SUB)
    s.save(f"{OUT}/04-voice-pipeline.svg")


# ---------------------------------------------------------------- 03 call sequence
def call_sequence():
    s = SVG(1240, 1000, "Figure 3 · Disruption call, end to end",
            "Identify → tell options → self-serve rebook, or hand off to a Genesys agent with full context.")
    actors = {
        "caller": (90, "Caller", "phone", "neutral"),
        "twilio": (280, "Twilio", "voice + SMS", "twilio"),
        "zingly": (490, "Zingly Orchestrator", "gateway + dialog", "zingly"),
        "rm":     (710, "Policy + Read model", "cache · lanes", "zingly"),
        "pss":    (920, "Atlantica PSS", "system of record", "airline"),
        "gen":    (1120, "Genesys Cloud", "Architect · agents", "genesys"),
    }
    q = Seq(s, actors, top=84, box_w=160)
    q.draw_heads()
    q.msg("caller", "twilio", "dials disruption line")
    q.msg("twilio", "zingly", "voice webhook (X-Twilio-Signature)")
    q.msg("zingly", "zingly", "verify HMAC · tenant = AccountSid + DID")
    q.msg("zingly", "twilio", "TwiML <Connect><Stream> + signed stream token", dashed=True)
    q.msg("twilio", "zingly", "WSS media stream open", color=ACCENT)
    q.msg("zingly", "caller", "AI disclosure + greeting (pre-rendered, non-interruptible)", color=ACCENT)
    q.msg("zingly", "rm", "lookup hmac(ANI) in disruption manifest → L1 hint")
    q.msg("caller", "zingly", "\"My flight got cancelled\" · booking ref X7K2PQ · \"Singh\"", color=ACCENT)
    q.msg("zingly", "rm", "verify(rloc, surname)")
    q.msg("rm", "pss", "PNR retrieve · lane P1 (≤ 1.5 s wait)", color=GREEN)
    q.msg("pss", "rm", "PNR snapshot (cached for the call)", dashed=True)
    q.msg("rm", "zingly", "L2 verified + options (indicative cache)", dashed=True)
    q.msg("zingly", "caller", "\"AT127 at 14:05 or AT129 at 19:40 — or a full refund\"", color=ACCENT)
    y_alt = q.y - 14
    q.y += 18
    q.msg("caller", "zingly", "\"The 14:05 please\"", color=ACCENT)
    q.msg("zingly", "rm", "policy: assurance ≥ L2 · same cabin · ±N h · no fare diff")
    q.msg("rm", "pss", "live re-check → hold → commit · lane P0 · idempotency key", color=GREEN)
    q.msg("pss", "rm", "COMMITTED (timeout ⇒ query PNR state, never blind retry)", dashed=True)
    q.msg("zingly", "caller", "read-back of new itinerary (non-interruptible)", color=ACCENT)
    q.msg("zingly", "twilio", "SMS confirmation → contact on PNR (not ANI)")
    q.y += 10
    q.divider(36, 1210, "else · caller asks for agent · policy denies · ID fails · 2 failed turns · PSS down", "genesys")
    q.y += 6
    q.msg("zingly", "zingly", "store HandoffContext → opaque handoffId")
    q.msg("zingly", "gen", "estimated wait time? (high ⇒ callback offer, see Fig. 6)")
    q.msg("zingly", "twilio", "update call → <Dial><Sip> · UUI = handoffId", color=AMBER)
    q.msg("twilio", "gen", "SIP INVITE (TLS/SRTP) + UUI", color=AMBER)
    q.msg("gen", "zingly", "Data Action GET /handoffs/{id} (OAuth2 CC) → screen-pop", color=AMBER)
    q.frame(36, 1210, y_alt, q.y - 12, "alt  self-serve rebook", "zingly")
    q.finish()
    s.save(f"{OUT}/03-disruption-call-sequence.svg")


# ---------------------------------------------------------------- 04 PSS protection
def pss_protection():
    s = SVG(1240, 660, "Figure 5 · Protecting the rate-limited reservation system during a 20× spike",
            "Callers are correlated: thousands ask about the same cancelled flights. Cache per flight / O&D, coalesce, then admit by priority.")
    s.zone(28, 84, 820, 112, "Before the wave · pre-warm on the event", "airline")
    s.box(48, 118, 190, 58, "Ops / IROPS feed", "flight.cancelled AT123")
    s.box(318, 118, 220, 58, "Disruption Worker", "pull manifest once · options\nper O&D + cabin")
    s.box(618, 118, 214, 58, "Disruption read model", "status · manifest · ANI index\nindicative options", kind="zingly")
    s.arrow([(238, 147), (318, 147)], label="event", lx=278, ly=139)
    s.arrow([(538, 147), (618, 147)], label="writes", lx=578, ly=139)
    s.arrow([(428, 176), (428, 214), (970, 214), (970, 252)], color=GREEN, dashed=True)
    s.text(860, 208, "low-priority reads via lanes P2 / P3", size=10.5, color=GREEN, halo=True, anchor="middle")

    my = 300
    for i in (2, 1):
        s.raw(f'<rect x="{28 + i * 6}" y="{my + 4 - i * 6}" width="150" height="70" rx="8" fill="#fff" stroke="#CBD5E1"/>')
    s.box(28, my + 4, 150, 70, "1,000 callers", "all on AT123 → BOS")
    s.box(238, my + 4, 160, 70, "Tool calls", "status · options · PNR", kind="zingly")
    s.box(458, my + 4, 160, 70, "Cache lookup", "tenant-prefixed keys\nTTL per data class", kind="zingly")
    s.box(678, my + 4, 160, 70, "Single-flight", "concurrent misses on a key\n→ 1 upstream call", kind="zingly")
    s.arrow([(178, my + 39), (238, my + 39)], color=ACCENT, width=2)
    s.arrow([(398, my + 39), (458, my + 39)], color=ACCENT, width=2)
    s.arrow([(618, my + 39), (678, my + 39)], label="miss", lx=648, ly=my + 31)
    s.arrow([(538, my + 4), (538, 244), (725, 244), (725, 176)], color=ACCENT, dashed=True)
    s.text(548, 266, "hit → answer in < 50 ms", size=10.5, color=ACCENT, halo=True)
    s.text(758, my + 96, "1,000 requests → 1 PSS call", size=11.5, weight=700, color=ACCENT, anchor="middle")

    lx, ly = 900, 236
    s.zone(lx - 16, ly, 196, 330, "Admission control", "zingly")
    lanes = [("P0 commit / hold", "40%", "3 s"), ("P1 PNR retrieve", "30%", "1.5 s"),
             ("P2 availability", "20%", "0.5 s"), ("P3 status / bg", "10%", "0 s")]
    for i, (n, share, wait) in enumerate(lanes):
        y = ly + 34 + i * 62
        s.raw(f'<rect x="{lx}" y="{y}" width="164" height="48" rx="7" fill="#fff" stroke="{ACCENT}" stroke-width="1.3"/>')
        s.raw(f'<rect x="{lx + 1}" y="{y + 1}" width="{162 * int(share[:-1]) / 40:.0f}" height="5" rx="2" fill="{ACCENT}" opacity=".55"/>')
        s.text(lx + 10, y + 25, n, size=11.5, weight=650, color=INK)
        s.text(lx + 10, y + 40, f"{share} of budget · wait ≤ {wait}", size=10, color=SUB)
    s.text(lx + 82, ly + 300, "token buckets per tenant;", size=10, color=SUB, anchor="middle")
    s.text(lx + 82, ly + 314, "borrow down, never up", size=10, color=SUB, anchor="middle")
    s.arrow([(838, my + 39), (900, my + 39)], color=ACCENT, width=2)
    s.box(1112, 330, 100, 96, "PSS", "≈ 50 TPS\nper tenant\ncredential", kind="airline")
    for i in range(4):
        y = ly + 58 + i * 62
        s.path(f"M1064,{y} H1088", color=GREEN, end=False)
    s.path(f"M1088,{ly + 58} V{ly + 58 + 3 * 62}", color=GREEN, end=False)
    s.arrow([(1088, 378), (1112, 378)], color=GREEN, width=2)

    fy = 470
    s.zone(28, fy, 836, 170, "When a lane is full or the breaker is open, the caller still gets an answer", "danger")
    fb = [("P0 → deferred commit", "choice queued under its\nidempotency key · SMS confirm"),
          ("P1 → manifest snapshot", "labelled \"as of 14:02\" ·\nno change without live read"),
          ("P2 → indicative cache", "options offered, re-checked\nlive before any commit"),
          ("P3 → cache only", "flight status from the\nevent-fed read model")]
    for i, (t, sub) in enumerate(fb):
        s.box(44 + i * 205, fy + 40, 190, 72, t, sub, kind="danger", title_size=11.5)
    s.text(44, fy + 136, "Breaker per endpoint class: opens at 50% errors over 10 s or p95 > 2 s; half-open after 15 s.",
           size=10.5, color=SUB)
    s.text(44, fy + 154, "Reads retry once with jitter only if it still fits the turn's latency budget. Writes never retry blindly.",
           size=10.5, color=SUB)
    s.save(f"{OUT}/05-pss-protection.svg")


# ---------------------------------------------------------------- 05 multi-tenant
def multi_tenant():
    s = SVG(1240, 650, "Figure 8 · Multi-tenant platform: global control plane, regional cells",
            "Tenant = airline. Identity is resolved server-side and pinned to a home cell for residency; large tenants get a dedicated (silo) cell.")
    s.zone(28, 84, 1184, 96, "Global control plane · no passenger PII", "zingly")
    cp = [("Tenant registry", "DID / AccountSid → tenant + cell"), ("Config + policy packs", "versioned · flagged rollout"),
          ("Connector catalog", "PSS · CCaaS · CPaaS adapters"), ("Prompt + voice versions", "eval-gated releases")]
    for i, (t, sub) in enumerate(cp):
        s.box(48 + i * 292, 114, 268, 50, t, sub)
    s.box(28, 236, 200, 66, "Inbound call", "Twilio webhook\nAccountSid + DID", kind="twilio")
    s.box(28, 340, 200, 66, "Genesys Data Action", "OAuth client → tenant", kind="genesys")
    s.box(288, 286, 170, 70, "Tenant router", "resolve tenant +\nhome cell (GSLB)", accent=True)
    s.arrow([(228, 269), (258, 269), (258, 306), (288, 306)], color=ACCENT)
    s.arrow([(228, 373), (258, 373), (258, 336), (288, 336)], color=ACCENT)
    s.arrow([(373, 286), (373, 164)], dashed=True)
    s.text(381, 232, "lookup (cached)", size=10.5, color=SUB, halo=True)

    cells = [
        (520, "EU cell A · silo", ["Atlantica Airways"], "warm standby: 2nd EU region"),
        (750, "EU cell B · pool", ["Airline B", "Airline C"], "warm standby: 2nd EU region"),
        (980, "US cell · pool", ["Airline D", "Airline E"], "warm standby: 2nd US region"),
    ]
    for x, title, tenants, sb in cells:
        s.zone(x, 220, 212, 266, title, "zingly", dashed=True)
        y = 252
        for t in ["Media Gateway", "Orchestrator", "Read model · Redis", "Postgres (RLS) · event log", "Vault · KMS"]:
            s.raw(f'<rect x="{x + 14}" y="{y}" width="184" height="24" rx="5" fill="#fff" stroke="#CBD5E1"/>')
            s.text(x + 106, y + 16, t, size=10.5, color=INK, anchor="middle")
            y += 30
        n = len(tenants)
        tw = (184 - (n - 1) * 8) / n
        for i, t in enumerate(tenants):
            tx = x + 14 + i * (tw + 8)
            s.raw(f'<rect x="{tx:.1f}" y="{y + 4}" width="{tw:.1f}" height="30" rx="6" fill="{ZONES["airline"][1]}" stroke="{GREEN}"/>')
            s.text(tx + tw / 2, y + 23, t, size=10.5, weight=650, color=GREEN, anchor="middle")
        s.text(x + 106, 476, sb, size=10, color=SUB, anchor="middle", italic=True)
    s.arrow([(458, 321), (520, 321)], color=ACCENT, width=2, label="Atlantica", lx=489, ly=313)
    s.path("M440,356 V506 H1086", color=LINE, end=False)
    s.arrow([(856, 506), (856, 486)])
    s.arrow([(1086, 506), (1086, 486)])
    s.text(648, 500, "other tenants → their home cells", size=10.5, color=SUB, halo=True, anchor="middle")

    s.zone(28, 530, 1184, 100, "Isolated per tenant, even inside a pooled cell", "airline")
    iso = ["tenant_id from server-side resolution only", "Postgres row-level security · Redis key prefix + ACL",
           "own KMS key (envelope) · crypto-shred on exit", "own vault path · Twilio subaccount · Genesys client",
           "own quotas: PSS TPS · AI concurrency · LLM tokens", "own policy pack · prompts · voices · retention"]
    for i, t in enumerate(iso):
        cx = 48 + (i % 3) * 392
        cy = 572 + (i // 3) * 28
        s.raw(f'<circle cx="{cx + 4}" cy="{cy - 4}" r="3.5" fill="{GREEN}"/>')
        s.text(cx + 14, cy, t, size=11, color=INK)
    s.save(f"{OUT}/08-multi-tenant-cells.svg")


# ---------------------------------------------------------------- 06 handoff + OAuth
def handoff_auth():
    s = SVG(1240, 900, "Figure 6 · Genesys handoff, screen-pop and callback, with the OAuth 2.0 flow",
            "Only an opaque handoffId crosses SIP. Genesys pulls context with a tenant-scoped, audience-restricted token.")
    actors = {
        "orch":  (110, "Zingly Orchestrator", "EU cell", "zingly"),
        "authz": (320, "Zingly AuthZ", "token endpoint", "zingly"),
        "ctx":   (530, "Context API", "handoff store", "zingly"),
        "tw":    (730, "Twilio", "call control", "twilio"),
        "arch":  (930, "Genesys Cloud", "Architect · Data Action · API", "genesys"),
        "agent": (1130, "Agent desktop", "Script screen-pop", "genesys"),
    }
    q = Seq(s, actors, top=84, box_w=170)
    q.draw_heads()
    q.msg("orch", "ctx", "PUT HandoffContext → handoffId (128-bit random · TTL 15 min, 24 h if callback)")
    q.msg("orch", "arch", "GET queue estimated wait time (Genesys API · OAuth CC)")
    y_alt = q.y - 14
    q.y += 18
    q.msg("orch", "tw", "update call → <Dial><Sip> · UUI = handoffId", color=AMBER)
    q.msg("tw", "arch", "SIP INVITE over TLS + UUI", color=AMBER)
    q.msg("arch", "authz", "POST /token · grant=client_credentials · private_key_jwt", color=ACCENT)
    q.msg("authz", "arch", "access_token · aud=context-api · scope=handoff:read · tenant=atlantica · 5 min",
          dashed=True, color=ACCENT)
    q.msg("arch", "ctx", "GET /v1/handoffs/{id} · Authorization: Bearer …", color=ACCENT)
    q.msg("ctx", "ctx", "check aud · scope · token.tenant = handoff.tenant · TTL")
    q.msg("ctx", "arch", "context JSON (every read audited)", dashed=True)
    q.msg("arch", "agent", "route by lang / tier / assurance → screen-pop", color=AMBER)
    q.y += 10
    q.divider(36, 1210, "else · EWT above threshold or all agents busy → callback offer", "genesys")
    q.y += 6
    q.msg("orch", "orch", "caller accepts callback · number confirmed")
    q.msg("orch", "arch", "POST callback { number, queue, data: { handoffId } }", color=AMBER)
    q.msg("orch", "tw", "SMS: callback booked · polite end of call")
    q.msg("arch", "agent", "callback to agent → same Data Action → screen-pop", color=AMBER)
    q.frame(36, 1210, y_alt, q.y - 12, "alt  EWT ≤ threshold (e.g. 5 min)", "genesys")
    q.y += 10
    life_end = q.y - 16
    q.note(36, 1174, "Agents sign in to Genesys with Atlantica SSO (OIDC/SAML). The agent's browser never holds Zingly "
                     "credentials: context is fetched server-side by the Data Action.")
    q.finish(life_end=life_end)
    s.save(f"{OUT}/06-handoff-auth-flows.svg")


# ---------------------------------------------------------------- 07 step-up
def step_up():
    s = SVG(1240, 700, "Figure 7 · Step-up to L3: app push approval (CIBA-style decoupled auth)",
            "The passenger is already signed in to the Atlantica app via OIDC; the airline vouches for them with a short-lived signed assertion.")
    actors = {
        "caller": (100, "Caller", "on the phone", "neutral"),
        "orch":   (330, "Zingly Orchestrator", "EU cell", "zingly"),
        "notify": (570, "Notification API", "Atlantica backend", "airline"),
        "app":    (810, "Atlantica App", "OIDC session", "airline"),
        "idp":    (1060, "Atlantica IdP", "issues assertion", "airline"),
    }
    q = Seq(s, actors, top=84, box_w=190)
    q.draw_heads()
    q.msg("orch", "notify", "POST /push { pnrHolderRef, nonce, bindingCode=47 } (OAuth CC)", color=GREEN)
    q.msg("orch", "caller", "\"Please approve in the app — you'll see code 47\"", color=ACCENT)
    q.msg("notify", "app", "push notification")
    q.msg("app", "app", "code 47 matches · biometric unlock · Approve")
    q.msg("app", "idp", "approve(nonce) with the user's access token", color=GREEN)
    q.msg("idp", "orch", "signed JWT { iss=atlantica, aud=zingly:atlantica, sub, rloc, nonce, exp ≤ 120 s }", color=GREEN)
    q.msg("orch", "orch", "verify via Atlantica JWKS · aud · nonce · exp · rloc → L3")
    q.msg("orch", "caller", "\"Thanks, you're verified\" → higher-risk action allowed", color=ACCENT)
    q.y += 10
    life_end = q.y - 16
    q.note(36, 1174, "Timeout (60 s) or denied → SMS OTP to the phone on the PNR → else agent handoff flagged assurance=L2.\n"
                     "The binding code defeats push-fatigue approvals; nonce + 120 s expiry prevent replay.", kind="danger")
    q.finish(life_end=life_end)
    s.save(f"{OUT}/07-step-up-auth.svg")


if __name__ == "__main__":
    solution_overview()
    system_context()
    voice_pipeline()
    call_sequence()
    pss_protection()
    multi_tenant()
    handoff_auth()
    step_up()
    print("ok")
