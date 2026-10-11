"""Regenerate the prototype diagrams:  python prototype/docs/diagrams/build_diagrams.py

Hand-laid-out SVGs drawn with the same toolkit (docs/diagrams/svgkit.py) and visual language
as the solution-design figures. Standard library only.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..", "..", "..", "docs", "diagrams")))
from svgkit import ACCENT, SVG, ZONES  # noqa: E402

# Prototype zones, added to the shared palette: one colour per process / role.
ZONES["voice"] = ("#4F46E5", "#EEF2FF")     # Zingly voice agent
ZONES["mcp"] = ("#0891B2", "#ECFEFF")       # Zingly MCP server
ZONES["config"] = ("#7C3AED", "#F5F3FF")    # tenant configuration
ZONES["tenant_a"] = ("#2563EB", "#EFF6FF")  # Atlantica
ZONES["tenant_n"] = ("#0D9488", "#F0FDFA")  # Nordica
NORTH, SOUTH, WARN, BAD = "genesys", "airline", "genesys", "danger"
VOICE, MCP = ZONES["voice"][0], ZONES["mcp"][0]
GREEN, RED, AMBER, PURPLE = ZONES["airline"][0], ZONES["danger"][0], ZONES["genesys"][0], ZONES["config"][0]


# ------------------------------------------------------------------ 1 · architecture
def architecture():
    s = SVG(1240, 610, "Prototype architecture · four processes",
            "Text stands in for audio. The voice agent reaches the airline only through the MCP server, "
            "where the policy engine and the saved copy protect the 5 req/s reservation system.")
    # zones
    s.zone(140, 86, 192, 410, "Northbound :8090", NORTH)
    s.zone(356, 86, 390, 410, "Zingly voice agent :8080", "voice")
    s.zone(836, 86, 200, 410, "Zingly MCP server :8100", "mcp")
    s.zone(1066, 86, 148, 410, "Southbound :9001", SOUTH)

    # caller + Genesys
    s.box(28, 122, 98, 56, "Caller", "text = audio")
    s.box(152, 114, 168, 72, "Genesys inbound", "A/B split legacy IVR\ncapacity check", kind=NORTH)
    s.box(152, 296, 168, 84, "Queues · callback", "agent desktop\nscreen-pop from\nAGENT_HANDOVER", kind=NORTH)
    s.arrow([(126, 150), (152, 150)], color=AMBER)

    # voice agent internals: left column x=372, right column x=567
    s.box(372, 118, 160, 56, "Gateway", "sessions · tenant")
    s.box(567, 118, 160, 56, "Channel", "text now · LiveKit later")
    s.box(567, 200, 160, 70, "AI router", "welcome · consent\nfast path · disambiguation\nbusiness routing (rollout %)",
          accent=True)
    s.box(372, 200, 160, 56, "Handover", "AGENT_HANDOVER")
    s.box(567, 296, 160, 70, "Agents", "supervisor\nrebooking · status · FAQ", accent=True)
    s.box(372, 296, 160, 70, "Auth", "identity levels · lockout\nsigns identity token")
    s.box(567, 400, 160, 56, "MCP client", "official SDK")
    s.arrow([(320, 150), (372, 150)], color=AMBER)
    s.arrow([(532, 146), (567, 146)], color=VOICE)
    s.arrow([(647, 174), (647, 200)], color=VOICE)
    s.arrow([(647, 270), (647, 296)], color=VOICE)
    s.arrow([(567, 342), (532, 342)], color=VOICE)
    s.arrow([(567, 310), (550, 310), (550, 228), (532, 228)], color=VOICE)
    s.arrow([(647, 366), (647, 400)], color=VOICE)
    s.arrow([(452, 366), (452, 428), (567, 428)], color=VOICE)
    s.arrow([(372, 228), (346, 228), (346, 338), (320, 338)], color=AMBER)

    # MCP server internals, bottom-up: endpoint -> policy -> saved copy -> tools
    s.box(850, 394, 172, 70, "MCP endpoint", "per tenant\n/atlantica/mcp · /nordica/mcp\n+ stdio for Codex", kind="mcp")
    s.box(850, 286, 172, 84, "Policy engine", "identity token · guard\nbooking scope\nlanes P0–P3 · breaker",
          kind="mcp")
    s.box(850, 204, 172, 60, "Saved copy", "fresh · single-flight\n'as of' fallback")
    s.box(850, 118, 172, 64, "Reservation tools", "6 tools\ndeferred commits")
    s.arrow([(727, 428), (850, 428)], color=MCP, width=2.4)
    s.text(788, 416, "MCP protocol", size=10.5, weight=650, color=MCP, anchor="middle", halo=True)
    s.text(788, 446, "token in _meta", size=10.5, color=MCP, anchor="middle", halo=True)
    s.arrow([(936, 394), (936, 370)], color=MCP)
    s.arrow([(936, 286), (936, 264)], color=MCP)
    s.arrow([(936, 204), (936, 182)], color=MCP)

    # southbound
    s.box(1078, 118, 124, 64, "Airline PSS", "hard 5 req/s\n429 above it", kind=SOUTH)
    s.box(1078, 204, 124, 60, "Fault injection", "errors · latency")
    s.arrow([(1022, 150), (1078, 150)], color=GREEN, width=2.4)
    s.text(1050, 141, "HTTP", size=10.5, weight=650, color=GREEN, anchor="middle", halo=True)

    # config + traces
    s.box(560, 522, 300, 54, "config/tenants.yml", "one file · every tenant · each module gets its section",
          kind="config")
    s.arrow([(640, 522), (640, 496)], color=PURPLE, dashed=True)
    s.arrow([(846, 522), (846, 496)], color=PURPLE, dashed=True)
    s.box(28, 522, 304, 54, ".run/traces.jsonl", "spans from all four processes · W3C traceparent")
    s.text(1214, 540, "solid: request path", size=10.5, anchor="end")
    s.text(1214, 558, "dashed: configuration", size=10.5, anchor="end")
    s.text(1214, 576, "every hop carries the trace context", size=10.5, anchor="end")
    s.save(f"{HERE}/architecture.svg")


# ------------------------------------------------------------------ 2 · modules
def modules():
    s = SVG(1240, 450, "Modules · libraries depend only on core",
            "Each library owns its interfaces and default implementations. Only the two services wire them; "
            "an architecture test fails the build on any other import.")
    libs = [("channel", "Channel →\nTextChannel", "voice"), ("ai_router", "welcome · fast path\nrouting", "voice"),
            ("agents", "supervisor +\n3 domain agents", "voice"), ("auth", "levels · lockout\nsigns token", "voice"),
            ("handover", "AGENT_HANDOVER\nscreen-pop", "voice"), ("policy", "guard · lanes\nbreaker", "mcp"),
            ("saved_copy", "single-flight\n'as of'", "mcp"), ("mcp", "tools · PSS adapter\ndeferred commits", "mcp")]
    x0, w, gap = 63, 120, 22
    s.box(x0, 96, 4 * (w + gap) + w, 64, "services/voice_agent",
          "gateway + composition root · official MCP SDK client", kind="voice")
    mx = x0 + 5 * (w + gap)
    s.box(mx, 96, 2 * (w + gap) + w, 64, "services/mcp_server", "official MCP SDK server · ops API", kind="mcp")
    s.arrow([(x0 + 4 * (w + gap) + w, 128), (mx, 128)], color=MCP, dashed=True, width=2)
    s.text((x0 + 4 * (w + gap) + w + mx) / 2, 120, "MCP only", size=10.5, weight=650, color=MCP, anchor="middle",
           halo=True)

    s.zone(46, 184, 1148, 112, " ", "neutral")
    for i, (name, sub, kind) in enumerate(libs):
        x = x0 + i * (w + gap)
        s.box(x, 224, w, 60, name, sub, kind=kind, title_size=12)
        s.arrow([(x + w / 2, 160), (x + w / 2, 224)], color=ZONES[kind][0])
        s.arrow([(x + w / 2, 284), (x + w / 2, 340)], color=PURPLE)
    s.text(56, 206, "LIBRARIES", size=10.5, weight=700, color="#64748B")
    s.box(x0, 340, 8 * w + 7 * gap, 56, "core",
          "tenant context · identity level + signed identity token · tenant config loader · tracing", kind="config")
    s.text(x0, 424, "When a module needs another one it declares the interface it needs in its own ports.py; "
                    "the service plugs the other module in.", size=10.5)
    s.save(f"{HERE}/modules.svg")


# ------------------------------------------------------------------ 3 · one caller turn
def turn():
    s = SVG(1240, 620, "One caller turn",
            "Cheap paths first: rules before any model, the active agent before the classifier, a person whenever "
            "the bot cannot finish safely.")
    # top pipeline
    s.box(28, 122, 110, 56, "Caller", "says something")
    s.box(166, 122, 160, 56, "Genesys", "caller turn · starts trace", kind=NORTH)
    s.box(354, 122, 140, 56, "Gateway", "session · tenant")
    s.box(522, 122, 130, 56, "Channel", "text · DTMF")
    s.box(686, 100, 180, 100, "AI router", "rules first,\nthen classifier\n+ rollout %", accent=True)
    s.arrow([(138, 150), (166, 150)], color=AMBER)
    s.arrow([(326, 150), (354, 150)], color=VOICE)
    s.arrow([(494, 150), (522, 150)], color=VOICE)
    s.arrow([(652, 150), (686, 150)], color=VOICE)

    # branches
    branches = [("Fast path", "hi · yes/no · agent · no model\ncached reply, or yes/no bound to the pending question", "airline"),
                ("Clarify", "intent unclear: one short question\nhandover after two", None),
                ("Same topic", "slot answers ('ABC123') stay with\nthe active domain agent", "voice"),
                ("Topic change", "classifier picks a new agent (rollout %)\nthe open task is suspended, resumed later", "voice")]
    ys = [92, 168, 244, 320]
    s.path("M866,150 H896", color=VOICE, end=False)
    s.path(f"M896,{ys[0] + 28} V{ys[-1] + 28}", color=VOICE, end=False)
    for (title, sub, kind), y in zip(branches, ys):
        s.box(924, y, 290, 58, title, sub, kind=kind)
        s.arrow([(896, y + 28), (924, y + 28)], color=VOICE)

    # agent + tools
    s.path("M1069,378 V420 H808", color=VOICE, end=False)
    s.path("M1214,273 H1226 V420 H1069", color=VOICE, end=False)
    s.arrow([(808, 420), (808, 470)], color=VOICE)
    s.box(708, 470, 200, 70, "Domain agent", "rebooking · flight status · FAQ\nidentity token stays out of\ntool arguments", accent=True)
    s.box(940, 470, 274, 70, "MCP server", "guard · booking scope · lanes\nsaved copy · reservation system", kind="mcp")
    s.arrow([(908, 505), (940, 505)], color=MCP, both=True, width=2)
    s.text(924, 496, "tools/call", size=10.5, weight=650, color=MCP, anchor="middle", halo=True)

    # agent reply -> reply or handover
    s.box(484, 470, 190, 70, "Agent reply", "next question · done ·\ncannot finish safely")
    s.arrow([(708, 505), (674, 505)], color=VOICE)
    s.box(260, 470, 196, 70, "AGENT_HANDOVER", "who · why · how verified\nwhat was already tried", kind=BAD)
    s.arrow([(484, 505), (456, 505)], color=RED)
    s.box(28, 470, 200, 70, "Genesys queue", "or callback when the wait\nis long · screen-pop", kind=NORTH)
    s.arrow([(260, 505), (228, 505)], color=RED)
    s.box(28, 300, 200, 64, "Reply to the caller", "next question, resume the\nsuspended task, or 'anything else?'",
          kind="airline")
    s.arrow([(579, 470), (579, 332), (228, 332)], color=GREEN)
    s.arrow([(83, 300), (83, 178)], color=GREEN)
    s.text(590, 450, "next question / done", size=10.5, color=GREEN, anchor="start", halo=True)
    s.text(370, 462, "cannot finish", size=10.5, color=RED, anchor="middle", halo=True)
    s.text(28, 596, "Fast path and clarify answer straight back to the caller. AI disclosure and itinerary read-back "
                    "cannot be interrupted.", size=10.5)
    s.save(f"{HERE}/turn.svg")


# ------------------------------------------------------------------ 4 · protection
def protection():
    s = SVG(1240, 790, "How a reservation call is protected (inside the MCP server)",
            "Every client goes through the same checks: the voice agent, Codex, the MCP Inspector. "
            "Writes are never served from the copy and never retried blindly.")
    # checks row
    s.box(28, 112, 150, 56, "tools/call", "from any MCP client", kind="mcp")
    s.box(206, 100, 196, 80, "Identity token", "signature · tenant · expiry\n→ level + booking\nnone or invalid → unknown",
          accent=True)
    s.box(430, 112, 170, 56, "Guard", "tool allowed at this level?", accent=True)
    s.box(628, 112, 196, 56, "Booking scope", "booking = token's booking?", accent=True)
    s.box(852, 112, 190, 56, "Which data?", "shared, or the caller's own")
    for a, b in [(178, 206), (402, 430), (600, 628), (824, 852)]:
        s.arrow([(a, 140), (b, 140)], color=MCP)
    s.box(470, 222, 210, 50, "denied", "nothing reaches the PSS", kind=BAD)
    s.arrow([(515, 168), (515, 222)], color=RED, label="not allowed", lx=523, ly=200, anchor="start")
    s.arrow([(726, 168), (726, 247), (680, 247)], color=RED, label="other booking", lx=734, ly=200, anchor="start")

    # split
    s.path("M947,168 V230", color=MCP, end=False)
    s.arrow([(947, 230), (760, 230), (760, 300)], color=MCP)
    s.arrow([(947, 230), (1076, 230), (1076, 300)], color=MCP)
    s.text(860, 222, "status · options · caller-ID hint", size=10.5, color=MCP, anchor="middle", halo=True)
    s.text(1080, 222, "verify · booking · rebook", size=10.5, color=MCP, anchor="start", halo=True)

    s.box(660, 300, 200, 64, "Saved copy fresh?", "25 s for options\nfilled by the disruption pre-warm",
          kind="mcp")
    s.box(940, 296, 272, 84, "Breaker closed + lane token?", "within the lane's wait budget\n"
          "P0 3 s · P1 1.5 s · P2 0.5 s · P3 0 s\nhigher lanes borrow idle capacity", kind="mcp")
    s.arrow([(860, 332), (940, 332)], color=MCP, label="no: one loader", lx=900, ly=322)
    s.text(900, 352, "per key", size=10.5, color=MCP, anchor="middle", halo=True)

    s.box(660, 436, 200, 56, "Answer the caller", "from the copy: 0 PSS requests", kind="airline")
    s.arrow([(760, 364), (760, 436)], color=GREEN, label="yes", lx=768, ly=386, anchor="start")
    s.box(1000, 436, 212, 56, "Airline PSS", "hard 5 req/s", kind=SOUTH)
    s.arrow([(1106, 380), (1106, 436)], color=GREEN, label="yes", lx=1114, ly=412, anchor="start")
    s.arrow([(1000, 464), (860, 464)], color=GREEN, label="ok", lx=930, ly=456)

    s.box(380, 436, 236, 70, "Lane full: degrade, don't fail", "read → saved copy labelled 'as of'\n"
          "rebook → deferred commit\n(same idempotency key, SMS later)", kind=WARN)
    s.arrow([(980, 380), (980, 408), (498, 408), (498, 436)], color=AMBER, label="no: lane full", lx=600, ly=400)

    # write timeout
    s.box(1000, 588, 212, 56, "Read the booking back", "never a blind retry", accent=True)
    s.arrow([(1106, 492), (1106, 588)], color=RED, label="write timed out", lx=1114, ly=544, anchor="start")
    outs = [("Moved → confirmed", "the write had landed", "airline", 532),
            ("Unchanged → unavailable", "booking untouched; handover", BAD, 600),
            ("Unreadable → reconcile", "outcome unknown: replay later\nunder the same idempotency key", WARN, 668)]
    s.path("M1000,616 H976", color=ACCENT, end=False)
    s.path(f"M976,{outs[0][3] + 26} V{outs[-1][3] + 28}", color=ACCENT, end=False)
    for title, sub, kind, y in outs:
        h = 56 if "\n" in sub else 52
        s.box(716, y, 232, h, title, sub, kind=kind)
        s.arrow([(976, y + h / 2), (948, y + h / 2)], color=ACCENT)
    s.text(28, 766, "Lanes split the PSS limit 40/30/20/10 under a parent limit set a little below it (4 of 5 req/s). "
                    "Counters live in memory here and in Redis in production.", size=10.5)
    s.save(f"{HERE}/protection.svg")


# ------------------------------------------------------------------ 5 · multi-tenancy
def tenancy():
    s = SVG(1240, 470, "Multi-tenancy · one deployment, one config file",
            "Each process builds one runtime per tenant from the merged sections. A call is matched to a tenant "
            "by its dialed number.")
    s.box(28, 196, 190, 84, "config/tenants.yml", "platform\ndefaults per module\ntenants + overrides",
          kind="config")
    s.box(252, 208, 172, 60, "Deep-merge", "defaults + each\ntenant block", kind="config")
    s.arrow([(218, 238), (252, 238)], color=PURPLE)
    s.box(470, 100, 300, 126, "Atlantica · +448000001234",
          "consent prompt on\nrebooking for 100% of calls\nlanes 40 / 30 / 20 / 10\ndeferred commits on",
          kind="tenant_a")
    s.box(470, 256, 300, 126, "Nordica · +4780001234",
          "no consent prompt\nrebooking canaried to 50%\nlanes 50 / 30 / 10 / 10\ndeferred commits off · own queues",
          kind="tenant_n")
    s.arrow([(424, 228), (446, 228), (446, 163), (470, 163)], color=PURPLE)
    s.arrow([(424, 248), (446, 248), (446, 319), (470, 319)], color=PURPLE)

    for (y, kind, name) in [(100, "tenant_a", "atlantica"), (256, "tenant_n", "nordica")]:
        color = ZONES[kind][0]
        s.box(830, y, 384, 52, f"Voice agent runtime · {name}", "router · agents · auth lockouts · handover queues",
              kind="voice")
        s.box(830, y + 66, 384, 60, f"MCP runtime · /{name}/mcp",
              "own lanes · saved copy · breaker · signing key\ndeferred queue · verification throttle", kind="mcp")
        s.arrow([(770, y + 30), (800, y + 30), (800, y + 26), (830, y + 26)], color=color)
        s.arrow([(800, y + 30), (800, y + 96), (830, y + 96)], color=color)
    s.text(28, 418, "Isolation: lane buckets, saved copy, breaker, lockout counters, deferred queue, idempotency keys and "
                    "identity-token keys are all per tenant.", size=10.5)
    s.text(28, 438, "One tenant's storm cannot starve another (tested). A token issued for Atlantica is rejected on "
                    "/nordica/mcp.", size=10.5)
    s.save(f"{HERE}/tenancy.svg")


if __name__ == "__main__":
    for build in (architecture, modules, turn, protection, tenancy):
        build()
    print("wrote architecture.svg, modules.svg, turn.svg, protection.svg, tenancy.svg")
