# Flow 14: MCP server used directly, like Codex or the MCP Inspector would

A plain MCP client connects to the Atlantica endpoint over Streamable HTTP, lists the tools, reads public data, and tries to rebook: denied without an identity token, denied with a token for another booking, allowed with a VERIFIED token for this booking.

**Demonstrates:** real MCP server, guardrails, booking scope, signed identity token, idempotent write

**Result:** PASS · recorded 2026-10-11 17:48 · re-run with `python scripts/run_flow.py 14_mcp_direct_client --trace`

## Setup

- reset PSS data, MCP lanes/saved copy/breaker, voice-agent sessions and lockouts

## MCP client session

| Request | Identity | Result |
|---|---|---|
| `tools/list` "" |  | ['get_flight_status', 'get_alternatives', 'lookup_caller_id', 'verify_booking', 'get_booking', 'rebook'] |
| `tools/call get_flight_status` {"flight": "AT123"} | no identity token | ok |
| `tools/call verify_booking` {"booking_ref": "ABC123", "surname": "Jones"} | no identity token | ok |
| `tools/call rebook` {"booking_ref": "ABC123", "from_flight": "AT123", "to_flight": "AT127"} | no identity token | denied: 'rebook' needs verified, caller is unknown |
| `tools/call rebook` {"booking_ref": "ABC123", "from_flight": "AT123", "to_flight": "AT127"} | token verified for ZZZ999 | denied: booking is not the one this caller verified |
| `tools/call rebook` {"booking_ref": "ABC123", "from_flight": "AT123", "to_flight": "AT127"} | token verified for ABC123 | ok |
| `tools/call rebook` {"booking_ref": "ABC123", "from_flight": "AT123", "to_flight": "AT127"} | token verified for ABC123 | ok |

### Traces

<details><summary>tools/call get_flight_status</summary>

```text
[flow-runner] mcp-client: flow.mcp_call (129.9 ms) tool=get_flight_status identity=no identity token
  [mcp-server] mcp-server: mcp.tool (118.6 ms) tool=get_flight_status level=unknown status=ok source=pss
    [mcp-server] policy: policy.guard (0.0 ms) tool=get_flight_status level=unknown allowed=True
    [mcp-server] saved-copy: saved_copy.get_or_load (118.2 ms) key=flight source=origin
      [mcp-server] policy: policy.admission (0.0 ms) lane=P3 wait_budget_s=0.0 admitted=True waited_ms=0.0
      [mcp-server] pss-adapter: pss.request (117.9 ms) method=GET operation=get_flight http_status=200
        [airline-pss] airline-pss: pss.handle (114.6 ms) airline=atlantica method=GET resource=flights http_status=200 limit_rps=5
```

</details>

<details><summary>tools/call verify_booking</summary>

```text
[flow-runner] mcp-client: flow.mcp_call (226.5 ms) tool=verify_booking identity=no identity token
  [mcp-server] mcp-server: mcp.tool (213.2 ms) tool=verify_booking level=unknown status=ok source=pss
    [mcp-server] policy: policy.guard (0.0 ms) tool=verify_booking level=unknown allowed=True
    [mcp-server] policy: policy.admission (120.6 ms) lane=P1 wait_budget_s=1.5 admitted=True waited_ms=120.6
    [mcp-server] pss-adapter: pss.request (92.1 ms) method=GET operation=get_booking http_status=200
      [airline-pss] airline-pss: pss.handle (88.2 ms) airline=atlantica method=GET resource=bookings http_status=200 limit_rps=5
```

</details>

<details><summary>tools/call rebook</summary>

```text
[flow-runner] mcp-client: flow.mcp_call (13.8 ms) tool=rebook identity=no identity token
  [mcp-server] mcp-server: mcp.tool (0.2 ms) tool=rebook level=unknown status=denied source=none detail='rebook' needs verified, caller is unknown
    [mcp-server] policy: policy.guard (0.1 ms) tool=rebook level=unknown allowed=False reason='rebook' needs verified, caller is unknown
```

</details>

<details><summary>tools/call rebook</summary>

```text
[flow-runner] mcp-client: flow.mcp_call (13.6 ms) tool=rebook identity=token verified for ZZZ999
  [mcp-server] mcp-server: mcp.tool (0.2 ms) tool=rebook level=verified status=denied source=none detail=booking is not the one this caller verified
    [mcp-server] policy: policy.guard (0.0 ms) tool=rebook level=verified allowed=True
```

</details>

<details><summary>tools/call rebook</summary>

```text
[flow-runner] mcp-client: flow.mcp_call (209.0 ms) tool=rebook identity=token verified for ABC123
  [mcp-server] mcp-server: mcp.tool (196.7 ms) tool=rebook level=verified status=ok source=pss
    [mcp-server] policy: policy.guard (0.0 ms) tool=rebook level=verified allowed=True
    [mcp-server] policy: policy.admission (115.4 ms) lane=P0 wait_budget_s=3.0 admitted=True waited_ms=115.4
    [mcp-server] pss-adapter: pss.request (80.8 ms) method=POST operation=rebook http_status=200
      [airline-pss] airline-pss: pss.handle (76.9 ms) airline=atlantica method=POST resource=rebookings http_status=200 limit_rps=5
```

</details>

<details><summary>tools/call rebook</summary>

```text
[flow-runner] mcp-client: flow.mcp_call (319.9 ms) tool=rebook identity=token verified for ABC123
  [mcp-server] mcp-server: mcp.tool (306.5 ms) tool=rebook level=verified status=ok source=pss
    [mcp-server] policy: policy.guard (0.0 ms) tool=rebook level=verified allowed=True
    [mcp-server] policy: policy.admission (202.3 ms) lane=P0 wait_budget_s=3.0 admitted=True waited_ms=202.2
    [mcp-server] pss-adapter: pss.request (103.5 ms) method=POST operation=rebook http_status=200
      [airline-pss] airline-pss: pss.handle (99.9 ms) airline=atlantica method=POST resource=rebookings http_status=200 limit_rps=5
```

</details>

## Components involved

| Process | Component | Operations seen in this run |
|---|---|---|
| `airline-pss` | airline-pss | `pss.handle` |
| `flow-runner` | mcp-client | `flow.mcp_call` |
| `mcp-server` | mcp-server | `mcp.tool` |
| `mcp-server` | policy | `policy.admission`, `policy.guard` |
| `mcp-server` | pss-adapter | `pss.request` |
| `mcp-server` | saved-copy | `saved_copy.get_or_load` |

## Checks

- ✅ mcp step 1: tools/list includes get_flight_status
- ✅ mcp step 1: tools/list includes verify_booking
- ✅ mcp step 1: tools/list includes rebook
- ✅ mcp step 2: get_flight_status → {'status': 'ok'}
- ✅ mcp step 3: verify_booking → {'status': 'ok', 'data': {'match': False}}
- ✅ mcp step 4: rebook → {'status': 'denied'}
- ✅ mcp step 5: rebook → {'status': 'denied'}
- ✅ mcp step 6: rebook → {'status': 'ok'}
- ✅ mcp step 7: rebook → {'status': 'ok', 'data': {'replayed': True}}
