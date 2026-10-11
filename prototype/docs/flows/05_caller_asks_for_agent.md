# Flow 05: Caller asks for a person mid-task

Asking for an agent is honoured at any point (fast path, no model). The handover carries who the caller is, how they were verified and what was already done.

**Demonstrates:** fast path agent request, AGENT_HANDOVER payload, screen-pop, masked attributes

**Result:** PASS · recorded 2026-10-11 17:47 · re-run with `python scripts/run_flow.py 05_caller_asks_for_agent --trace`

## Setup

- reset PSS data, MCP lanes/saved copy/breaker, voice-agent sessions and lockouts
- disruption event for AT123: saved copy pre-warmed ({'flight': 'AT123', 'status': 'CANCELLED', 'bookings': 180, 'alternatives': 2, 'pss_requests': 3})

## Conversation

Genesys routed the call to **zingly**.

| # | Caller | Bot | Path → agent | Identity | ms |
|---|---|---|---|---|---|
| 0 | *(dials)* | Welcome to Atlantica Airways. I'm an AI assistant and this call may be recorded. Is that OK? | welcome (pre-rendered) | unknown | |
| 1 | yes | Thanks. How can I help with your flight today? | fast_path | unknown | 2.1 |
| 2 | my booking ABC123 was cancelled | Thanks. And the lead passenger's surname? | topic_change → rebooking | unknown | 1.2 |
| 3 | Smith | Thank you, you're verified. The next flights I can see to Boston are 14:05 on AT127 and 19:40 on AT131. Which would you like: the first or the second? | same_topic → rebooking | verified | 249.7 |
| 4 | can I speak to a real person | I'll connect you to a colleague now. They'll see everything we've covered. | fast_path | verified | 0.5 |

### Handover: Genesys screen-pop

Queue **Disruption_Rebooking**, callback_offered (estimated wait 300 s).

```json
{
  "conversation_status": "AGENT_HANDOVER",
  "tenant_id": "atlantica",
  "conversation_id": "conv-cc137dfff362",
  "call_id": "gen-45019a9065",
  "routing": {
    "queue": "Disruption_Rebooking",
    "category": "rebooking",
    "subcategory": "caller_requested_agent",
    "priority": 10,
    "callback_eligible": true
  },
  "summary": "Caller verified by booking_ref and surname. Booking A***23 on AT123. AT123 cancelled (weather). Reason for handover: caller asked for a person. Tried: verify_identity -> verified; get_alternatives -> ok.",
  "caller": {
    "number_masked": "+15******004",
    "identity_level": "verified",
    "verified_by": "booking_ref+surname"
  },
  "booking": {
    "ref_masked": "A***23",
    "flight": "AT123",
    "cabin": "economy"
  },
  "disruption": {
    "flight": "AT123",
    "status": "CANCELLED",
    "reason": "weather",
    "origin": "LHR",
    "destination": "BOS"
  },
  "attempted_actions": [
    {
      "action": "verify_identity",
      "result": "verified",
      "detail": "",
      "args": {},
      "at": 1791740881.7890928
    },
    {
      "action": "get_alternatives",
      "result": "ok",
      "detail": "",
      "args": {
        "origin": "LHR",
        "destination": "BOS"
      },
      "at": 1791740881.7890947
    }
  ],
  "context_ref": "7c199a58-d80b-4fad-8baa-b08d22e969c6",
  "genesys_participant_data": {
    "zingly.conversationStatus": "AGENT_HANDOVER",
    "zingly.category": "rebooking",
    "zingly.subcategory": "caller_requested_agent",
    "zingly.summary": "Caller verified by booking_ref and surname. Booking A***23 on AT123. AT123 cancelled (weather). Reason for handover: caller asked for a person. Tried: verify_identity -> verified; get_alternatives -> ok.",
    "zingly.identityLevel": "verified",
    "zingly.bookingRefMasked": "A***23",
    "zingly.attemptedActions": "2",
    "zingly.contextRef": "7c199a58-d80b-4fad-8baa-b08d22e969c6"
  },
  "data_notes": []
}
```

### Sequence (built from the recorded spans)

```mermaid
sequenceDiagram
    autonumber
    actor C as Caller
    participant G as Genesys (northbound)
    participant GW as Voice agent gateway
    participant R as AI router
    participant AG as Agents
    participant AU as Auth
    participant HO as Handover
    participant MC as MCP client
    participant MS as MCP server
    participant PO as Policy engine
    participant SC as Saved copy
    participant PA as PSS adapter
    participant PSS as Airline PSS (southbound)
    Note over C,G: call set-up
    G->>GW: gateway.capacity_check
    GW-->>G: accept=True
    G->>GW: gateway.create_conversation
    GW->>R: ai_router.welcome
    R-->>GW: done
    GW-->>G: done
    G-->>C: Welcome to Atlantica Airways. I'm an AI assistant and this …
    Note over C,G: yes
    C->>G: yes
    G->>GW: gateway.turn path=fast_path
    GW->>R: ai_router.route path=fast_path kind=say
    R-->>GW: done
    GW-->>G: status=IN_PROGRESS
    G-->>C: Thanks. How can I help with your flight today?
    Note over C,G: my booking ABC123 was cancelled
    C->>G: my booking ABC123 was cancelled
    G->>GW: gateway.turn agent=rebooking path=topic_change
    GW->>R: ai_router.route agent=rebooking path=topic_change kind=dispatch
    R-->>GW: done
    GW->>AG: agents.handle agent=rebooking
    AG-->>GW: done
    GW-->>G: status=IN_PROGRESS
    G-->>C: Thanks. And the lead passenger's surname?
    Note over C,G: Smith
    C->>G: Smith
    G->>GW: gateway.turn agent=rebooking path=same_topic
    GW->>R: ai_router.route agent=rebooking path=same_topic kind=dispatch
    R-->>GW: done
    GW->>AG: agents.handle agent=rebooking
    AG->>AU: auth.verify
    AU->>MC: mcp.call_tool tool=verify_booking
    MC->>MS: mcp.tool tool=verify_booking
    MS->>PO: policy.guard tool=verify_booking
    PO-->>MS: allowed=True, level=unknown
    MS->>PO: policy.admission lane=P1
    PO-->>MS: admitted=True
    MS->>PA: pss.request operation=get_booking
    PA->>PSS: pss.handle resource=bookings
    PSS-->>PA: http_status=200
    PA-->>MS: http_status=200
    MS-->>MC: status=ok, source=pss, level=unknown
    MC-->>AU: status=ok, source=pss
    AU-->>AG: outcome=verified, level=verified
    AG->>MC: mcp.call_tool tool=get_flight_status
    MC->>MS: mcp.tool tool=get_flight_status
    MS->>PO: policy.guard tool=get_flight_status
    PO-->>MS: allowed=True, level=unknown
    MS->>SC: saved_copy.get_or_load
    SC-->>MS: source=fresh
    MS-->>MC: status=ok, source=saved_copy, level=unknown
    MC-->>AG: status=ok, source=saved_copy
    AG->>MC: mcp.call_tool tool=get_alternatives
    MC->>MS: mcp.tool tool=get_alternatives
    MS->>PO: policy.guard tool=get_alternatives
    PO-->>MS: allowed=True, level=unknown
    MS->>SC: saved_copy.get_or_load
    SC-->>MS: source=fresh
    MS-->>MC: status=ok, source=saved_copy, level=unknown
    MC-->>AG: status=ok, source=saved_copy
    AG-->>GW: done
    GW-->>G: status=IN_PROGRESS
    G-->>C: Thank you, you're verified. The next flights I can see to B…
    Note over C,G: can I speak to a real person
    C->>G: can I speak to a real person
    G->>GW: gateway.turn path=fast_path
    GW->>R: ai_router.route path=fast_path kind=handover
    R-->>GW: done
    GW->>HO: handover.build
    HO-->>GW: done
    GW-->>G: status=AGENT_HANDOVER
    G-->>C: I'll connect you to a colleague now. They'll see everything…
```

### Traces

<details><summary>Call set-up</summary>

```text
[genesys] genesys: genesys.inbound_flow (13.7 ms) flow=Atlantica disruption line call_id=gen-45019a9065 caller=*********004 routed_to=zingly
  [voice-agent] gateway: gateway.capacity_check (3.3 ms) accept=True active=0 limit=500 breaker=closed
  [voice-agent] gateway: gateway.create_conversation (0.5 ms) call_id=gen-45019a9065 audio_id=atlantica:welcome:v1
    [voice-agent] ai-router: ai_router.welcome (0.2 ms)
```

</details>

<details><summary>Turn 1: “yes”</summary>

```text
[genesys] genesys: genesys.caller_turn (5.8 ms) call_id=gen-45019a9065 status=IN_PROGRESS
  [voice-agent] gateway: gateway.turn (2.1 ms) turn=1 status=IN_PROGRESS path=fast_path identity=unknown
    [voice-agent] channel: channel.inbound (0.1 ms) channel=text kind=speech chars=3
    [voice-agent] ai-router: ai_router.route (1.7 ms) kind=say path=fast_path
```

</details>

<details><summary>Turn 2: “my booking ABC123 was cancelled”</summary>

```text
[genesys] genesys: genesys.caller_turn (6.1 ms) call_id=gen-45019a9065 status=IN_PROGRESS
  [voice-agent] gateway: gateway.turn (1.2 ms) turn=2 status=IN_PROGRESS path=topic_change agent=rebooking identity=unknown
    [voice-agent] channel: channel.inbound (0.0 ms) channel=text kind=speech chars=31
    [voice-agent] ai-router: ai_router.route (0.3 ms) kind=dispatch path=topic_change agent=rebooking
    [voice-agent] agents: agents.handle (0.1 ms) agent=rebooking next_question=surname
```

</details>

<details><summary>Turn 3: “Smith”</summary>

```text
[genesys] genesys: genesys.caller_turn (253.3 ms) call_id=gen-45019a9065 status=IN_PROGRESS
  [voice-agent] gateway: gateway.turn (249.8 ms) turn=3 status=IN_PROGRESS path=same_topic agent=rebooking identity=verified
    [voice-agent] channel: channel.inbound (0.0 ms) channel=text kind=speech chars=5
    [voice-agent] ai-router: ai_router.route (0.1 ms) active=rebooking pending=surname kind=dispatch path=same_topic agent=rebooking
    [voice-agent] agents: agents.handle (249.2 ms) agent=rebooking pending=surname next_question=choose_option identity=verified
      [voice-agent] auth: auth.verify (189.2 ms) booking=****23 outcome=verified level=verified
        [voice-agent] mcp-client: mcp.call_tool (188.9 ms) tool=verify_booking identity=none status=ok source=pss
          [mcp-server] mcp-server: mcp.tool (155.2 ms) tool=verify_booking level=unknown status=ok source=pss
            [mcp-server] policy: policy.guard (0.0 ms) tool=verify_booking level=unknown allowed=True
            [mcp-server] policy: policy.admission (86.2 ms) lane=P1 wait_budget_s=1.5 admitted=True waited_ms=86.1
            [mcp-server] pss-adapter: pss.request (68.1 ms) method=GET operation=get_booking http_status=200
              [airline-pss] airline-pss: pss.handle (62.9 ms) airline=atlantica method=GET resource=bookings http_status=200 limit_rps=5
      [voice-agent] mcp-client: mcp.call_tool (30.6 ms) tool=get_flight_status identity=none status=ok source=saved_copy
        [mcp-server] mcp-server: mcp.tool (0.3 ms) tool=get_flight_status level=unknown status=ok source=saved_copy
          [mcp-server] policy: policy.guard (0.0 ms) tool=get_flight_status level=unknown allowed=True
          [mcp-server] saved-copy: saved_copy.get_or_load (0.0 ms) key=flight source=fresh
      [voice-agent] mcp-client: mcp.call_tool (28.8 ms) tool=get_alternatives identity=none status=ok source=saved_copy
        [mcp-server] mcp-server: mcp.tool (0.3 ms) tool=get_alternatives level=unknown status=ok source=saved_copy
          [mcp-server] policy: policy.guard (0.0 ms) tool=get_alternatives level=unknown allowed=True
          [mcp-server] saved-copy: saved_copy.get_or_load (0.0 ms) key=alts source=fresh
```

</details>

<details><summary>Turn 4: “can I speak to a real person”</summary>

```text
[genesys] genesys: genesys.caller_turn (4.1 ms) call_id=gen-45019a9065 status=AGENT_HANDOVER
  [voice-agent] gateway: gateway.turn (0.5 ms) turn=4 status=AGENT_HANDOVER path=fast_path identity=verified
    [voice-agent] channel: channel.inbound (0.0 ms) channel=text kind=speech chars=28
    [voice-agent] ai-router: ai_router.route (0.1 ms) active=rebooking pending=choose_option kind=handover path=fast_path handover=caller_requested_agent
    [voice-agent] handover: handover.build (0.1 ms) category=rebooking subcategory=caller_requested_agent queue=Disruption_Rebooking attempted_actions=2
  [genesys] genesys: genesys.route_to_agent (0.0 ms) queue=Disruption_Rebooking wait_s=300 disposition=callback_offered
```

</details>

## Background work during this flow

<details><summary>gateway.disruption_event (5095 ms)</summary>

```text
[voice-agent] gateway: gateway.disruption_event (5094.7 ms) flight=AT123
  [mcp-server] mcp-server: mcp.prewarm (5088.4 ms) flight=AT123
    [mcp-server] policy: policy.admission (0.0 ms) lane=P3 wait_budget_s=10 admitted=True waited_ms=0.0
    [mcp-server] pss-adapter: pss.request (80.7 ms) method=GET operation=get_flight http_status=200
      [airline-pss] airline-pss: pss.handle (76.5 ms) airline=atlantica method=GET resource=flights http_status=200 limit_rps=5
    [mcp-server] policy: policy.admission (2419.9 ms) lane=P3 wait_budget_s=10 admitted=True waited_ms=2419.9
    [mcp-server] pss-adapter: pss.request (90.4 ms) method=GET operation=get_passenger_list http_status=200
      [airline-pss] airline-pss: pss.handle (85.9 ms) airline=atlantica method=GET resource=flights http_status=200 limit_rps=5
    [mcp-server] policy: policy.admission (2410.4 ms) lane=P3 wait_budget_s=10 admitted=True waited_ms=2410.4
    [mcp-server] pss-adapter: pss.request (84.8 ms) method=GET operation=get_alternatives http_status=200
      [airline-pss] airline-pss: pss.handle (80.7 ms) airline=atlantica method=GET resource=alternatives http_status=200 limit_rps=5
```

</details>

## Components involved

| Process | Component | Operations seen in this run |
|---|---|---|
| `airline-pss` | airline-pss | `pss.handle` |
| `genesys` | genesys | `genesys.caller_turn`, `genesys.inbound_flow`, `genesys.route_to_agent` |
| `mcp-server` | mcp-server | `mcp.prewarm`, `mcp.tool` |
| `mcp-server` | policy | `policy.admission`, `policy.guard` |
| `mcp-server` | pss-adapter | `pss.request` |
| `mcp-server` | saved-copy | `saved_copy.get_or_load` |
| `voice-agent` | agents | `agents.handle` |
| `voice-agent` | ai-router | `ai_router.route`, `ai_router.welcome` |
| `voice-agent` | auth | `auth.verify` |
| `voice-agent` | channel | `channel.inbound` |
| `voice-agent` | gateway | `gateway.capacity_check`, `gateway.create_conversation`, `gateway.disruption_event`, `gateway.turn` |
| `voice-agent` | handover | `handover.build` |
| `voice-agent` | mcp-client | `mcp.call_tool` |

## Checks

- ✅ call 1: routed to zingly (got zingly)
- ✅ call 1 turn 3: identity = verified (got verified)
- ✅ call 1 turn 4: call status AGENT_HANDOVER (got AGENT_HANDOVER)
- ✅ call 1 turn 4: handover subcategory = caller_requested_agent (got caller_requested_agent)
- ✅ call 1 turn 4: handover identity = verified (got verified)
- ✅ call 1 turn 4: handover queue = Disruption_Rebooking (got Disruption_Rebooking)
