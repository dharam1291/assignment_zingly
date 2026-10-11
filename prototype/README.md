# Zingly voice agent prototype

A simulated flight-disruption call, end to end, in text. This is the slice the assignment
recommends, built on the module boundaries of the [solution design](../docs/SOLUTION_DESIGN.md):

- **Caller utterances** (text standing in for audio) arrive through a **Genesys simulator** (northbound).
- The **voice agent** identifies the caller and answers through a **real MCP server**.
- The MCP server protects a **mocked airline reservation system with a hard 5 req/s limit** (southbound).
  When the limit is near, it answers from a **saved copy** and **priority lanes**.
- Every handover produces an **`AGENT_HANDOVER` JSON payload** for the Genesys screen-pop.
- A **load script** simulates a spike. **14 runnable flows** demonstrate every degraded mode, and
  their **distributed traces** are recorded as documentation.

There is no LLM and no API key. The agents run in the design's *deterministic mode*: templates
and slot filling behind the same interfaces an LLM version would use.

## Quick start

```bash
cd prototype
./start_up.sh                        # Python venv + install + start all four servers
.venv/bin/python scripts/run_flow.py --list
.venv/bin/python scripts/run_flow.py happy_rebooking --trace
.venv/bin/python -m genesys_sim --trace         # interactive call in the terminal
open http://127.0.0.1:8090                      # or the softphone + agent desktop in a browser
.venv/bin/python scripts/spike.py              # load spike: unprotected vs protected
./start_up.sh stop
```

`start_up.sh` needs only Python 3.11+ on the PATH. It creates `.venv`, installs the 13 packages
in editable mode (only when a `pyproject.toml` changed), and stops whatever already listens on a port
(SIGTERM, then SIGKILL after a grace period). It then starts the servers in dependency order and
waits for each one's health check. Other commands are `stop`, `restart`, `status`, `test` and
`logs <name>`, with the options `--skip-install`, `--clean-traces` and `--reinstall`.

| Process | Port | Side | What it is |
|---|---|---|---|
| `genesys` | 8090 | northbound | Genesys inbound flow: A/B split, capacity check, queues, callback, screen-pop, browser UI |
| `voice_agent` | 8080 | Zingly | Gateway + channel + AI router + agents + auth + handover; an **MCP client** |
| `mcp` | 8100 | Zingly | **MCP server** (official SDK): `/{tenant}/mcp` + policy engine + saved copy |
| `pss` | 9001 | southbound | Airline reservation system: hard 5 req/s per airline, 429, fault injection |

## Architecture

```mermaid
flowchart LR
    caller(["☎ Caller"]):::actor
    cfg[["config/tenants.yml<br/>one file · all tenants"]]:::config
    traces[(".run/traces.jsonl<br/>trace collector")]:::obs

    subgraph NB["Northbound · Genesys simulator :8090"]
        direction TB
        ivr["Inbound flow<br/>A/B split · capacity check"]:::north
        queues["Queues · callback<br/>agent desktop screen-pop"]:::north
    end

    subgraph VA["Zingly voice agent :8080"]
        direction TB
        gw["Gateway"]:::voice
        ch["Channel<br/>text now · LiveKit later"]:::voice
        rt["AI router<br/>welcome · consent · fast path<br/>disambiguation · business routing"]:::voice
        ag["Agents<br/>supervisor · rebooking<br/>flight status · FAQ"]:::voice
        au["Auth<br/>identity levels · lockout<br/>signs identity token"]:::voice
        ho["Handover<br/>AGENT_HANDOVER"]:::voice
        mc["MCP client"]:::voice
    end

    subgraph MS["Zingly MCP server :8100"]
        direction TB
        ep["MCP endpoint per tenant<br/>/atlantica/mcp · /nordica/mcp"]:::mcp
        po["Policy engine<br/>guard · booking scope<br/>priority lanes · breaker"]:::mcp
        sc["Saved copy<br/>single-flight · as-of"]:::mcp
        tl["Reservation tools<br/>+ deferred commits"]:::mcp
    end

    subgraph SB["Southbound · airline PSS :9001"]
        pss["Reservation system<br/>hard 5 req/s · 429"]:::south
    end

    caller -->|"speaks (text)"| ivr
    ivr -->|"create conversation · utterances"| gw
    gw --> ch --> rt --> ag
    ag --> au
    ag --> ho
    ag --> mc
    au --> mc
    mc ==>|"MCP Streamable HTTP<br/>identity token in _meta"| ep
    ep --> po --> sc --> tl
    tl ==>|"HTTP · traceparent"| pss
    ho -->|"screen-pop payload"| queues
    cfg -.-> VA
    cfg -.-> MS
    VA -.->|spans| traces
    MS -.->|spans| traces
    NB -.->|spans| traces
    SB -.->|spans| traces

    classDef actor fill:#FFFFFF,stroke:#37474F,color:#000
    classDef north fill:#E3F2FD,stroke:#1E88E5,color:#0D47A1
    classDef voice fill:#E8F5E9,stroke:#43A047,color:#1B5E20
    classDef mcp fill:#FFF3E0,stroke:#FB8C00,color:#E65100
    classDef south fill:#FCE4EC,stroke:#D81B60,color:#880E4F
    classDef config fill:#F3E5F5,stroke:#8E24AA,color:#4A148C
    classDef obs fill:#ECEFF1,stroke:#546E7A,color:#263238
    style NB fill:#F5FAFF,stroke:#1E88E5
    style VA fill:#F6FBF6,stroke:#43A047
    style MS fill:#FFFAF2,stroke:#FB8C00
    style SB fill:#FFF5F8,stroke:#D81B60
    linkStyle 0,1 stroke:#1E88E5,stroke-width:2px
    linkStyle 9 stroke:#FB8C00,stroke-width:3px
    linkStyle 13 stroke:#D81B60,stroke-width:3px
```

**Why the policy engine lives inside the MCP server.** Every client of the reservation system
passes through the same door: the voice agent, Codex, or the MCP Inspector. So the guard, the
booking-scope check, the lanes and the saved copy apply to every caller, not just to well-behaved
ones. The voice agent holds no reservation code at all, and an architecture test enforces that.

## Modules

Each box above is its own library under `libs/`, with its own `pyproject.toml` and tests.
Two services compose them. The interfaces and default implementations of a module live
**inside that module**.

| Library | Design box | Interface → default implementation | Config section | Runs in |
|---|---|---|---|---|
| `core` | shared base | `TenantContext`, `IdentityLevel`, signed `identity_token`, `TenantConfigStore`, `tracing` | `platform` | both |
| `channel` | voice worker | `Channel` → `TextChannel` | `channel` | voice agent |
| `ai_router` | AI routing | `IntentClassifier` → `KeywordClassifier`, plus `AIRouter`, `FastPath`, `Welcome`, `BusinessRouter` | `ai_router` | voice agent |
| `agents` | supervisor + domain agents | `DomainAgent` → Rebooking / Flight status / FAQ, `Supervisor` | `agents` | voice agent |
| `auth` | Auth service | `AuthService` → `DefaultAuthService` (lockout, issues the token) | `auth` | voice agent |
| `handover` | handover, screen-pop | `HandoverBuilder` → `GenesysHandoverBuilder` | `handover` | voice agent |
| `policy` | policy engine | `ToolGuard` → `LevelGuard`, `AdmissionController` → `LaneAdmission`, `CircuitBreaker` → `CountingBreaker` | `policy` | MCP server |
| `saved_copy` | saved copy | `SavedCopy` → `InMemorySavedCopy` | `saved_copy` | MCP server |
| `mcp` | reservation tools | `ToolRegistry`, `PssBackend` → `HttpPssBackend`, `DeferredCommits` (transport-free) | `mcp` | MCP server |

```mermaid
flowchart BT
    core["core"]:::core
    subgraph L["libraries: each imports only core"]
        channel:::lib
        ai_router:::lib
        agents:::lib
        auth:::lib
        handover:::lib
        policy:::lib
        saved_copy:::lib
        mcp:::lib
    end
    va["services/voice_agent<br/>composes channel · ai_router · agents · auth · handover<br/>+ MCP SDK client"]:::svc
    ms["services/mcp_server<br/>composes policy · saved_copy · mcp<br/>+ MCP SDK server"]:::svc
    L --> core
    va --> channel & ai_router & agents & auth & handover
    ms --> policy & saved_copy & mcp
    va -. "MCP protocol only" .-> ms
    classDef core fill:#F3E5F5,stroke:#8E24AA,color:#4A148C
    classDef lib fill:#E8F5E9,stroke:#43A047,color:#1B5E20
    classDef svc fill:#FFF3E0,stroke:#FB8C00,color:#E65100
```

When a module needs another one, it declares the interface it needs **in its own package**
(`ports.py`), and the service plugs the other module in. For example, `mcp` declares `AdmissionPort`
and `CachePort`, and `policy` and `saved_copy` satisfy them without importing each other.
`tests/test_architecture.py` fails the build on any other import: a library importing another
library, the MCP SDK inside a library, or the voice agent importing reservation code.

## How one caller turn is handled

```mermaid
flowchart TD
    U["Caller text"]:::in --> G["Genesys: caller turn<br/>starts the trace"]:::north
    G --> GW["Gateway: session, tenant"]:::voice --> CH["Channel: normalise, DTMF"]:::voice --> R{"AI router"}:::router
    R -->|"hi · yes/no · agent<br/>fast path, no model"| FP["Cached reply, or yes/no<br/>bound to the pending question"]:::voice
    R -->|"same topic<br/>(slot answers stay put)"| A["Active domain agent"]:::voice
    R -->|"topic change<br/>classifier + rollout %"| N["New domain agent<br/>open task suspended"]:::voice
    R -->|"unclear"| CL["One clarifying question<br/>handover after 2"]:::voice
    A & N --> T["Tools through the MCP client<br/>identity token in _meta"]:::mcp
    T --> RES{"Agent reply"}:::router
    RES -->|"next question"| OUT["Reply to the caller"]:::north
    RES -->|"done: resume a suspended task<br/>or ask 'anything else?'"| OUT
    RES -->|"cannot finish safely"| HO["AGENT_HANDOVER<br/>who · why · what was tried"]:::hand
    FP & CL --> OUT
    HO --> Q["Genesys queue or callback<br/>screen-pop"]:::north
    classDef in fill:#FFFFFF,stroke:#37474F,color:#000
    classDef north fill:#E3F2FD,stroke:#1E88E5,color:#0D47A1
    classDef voice fill:#E8F5E9,stroke:#43A047,color:#1B5E20
    classDef router fill:#FFFDE7,stroke:#F9A825,color:#5D4037
    classDef mcp fill:#FFF3E0,stroke:#FB8C00,color:#E65100
    classDef hand fill:#FCE4EC,stroke:#D81B60,color:#880E4F
```

## How a reservation call is protected

```mermaid
flowchart TD
    C["tools/call<br/>from any MCP client"]:::mcp --> ID{"Identity token valid?<br/>(signature · tenant · expiry)"}:::check
    ID -->|"no token / invalid"| UNK["level = unknown"]:::mcp
    ID -->|"valid"| LV["level + booking from the token"]:::mcp
    UNK & LV --> GU{"Guard: tool allowed<br/>at this level?"}:::check
    GU -->|no| DEN["denied"]:::bad
    GU -->|yes| SC{"Booking-scoped tool?<br/>booking = token's booking"}:::check
    SC -->|mismatch| DEN
    SC -->|ok| KIND{"Shared data<br/>or caller data?"}:::check
    KIND -->|"flight status, options, caller-ID hint"| FRESH{"Saved copy fresh?"}:::check
    FRESH -->|yes| HIT["answer · 0 PSS requests"]:::good
    FRESH -->|"no: single-flight<br/>one loader per key"| LANE
    KIND -->|"verify, booking, rebook"| LANE{"Breaker closed and<br/>lane token within wait budget?<br/>P0 3s · P1 1.5s · P2 0.5s · P3 0s"}:::check
    LANE -->|yes| PSS["PSS · hard 5 req/s"]:::south
    LANE -->|"no: read"| STALE["saved copy labelled 'as of'"]:::warn
    LANE -->|"no: rebook"| DEF["deferred commit<br/>same idempotency key"]:::warn
    PSS -->|"timeout on a write"| RB{"Read the booking back"}:::check
    RB -->|"moved"| HIT
    RB -->|"unchanged"| FAIL["unavailable · booking unchanged"]:::bad
    RB -->|"unreadable"| REC["outcome unknown<br/>reconcile under the same key"]:::warn
    classDef mcp fill:#FFF3E0,stroke:#FB8C00,color:#E65100
    classDef check fill:#FFFDE7,stroke:#F9A825,color:#5D4037
    classDef good fill:#E8F5E9,stroke:#43A047,color:#1B5E20
    classDef warn fill:#FFF8E1,stroke:#FFB300,color:#6D4C41
    classDef bad fill:#FFEBEE,stroke:#E53935,color:#B71C1C
    classDef south fill:#FCE4EC,stroke:#D81B60,color:#880E4F
```

## Multi-tenancy: one deployment, one config file

```mermaid
flowchart LR
    F[["config/tenants.yml<br/>platform · defaults · tenants"]]:::config
    F --> M{{"deep-merge defaults<br/>with each tenant block"}}:::config
    M --> A["atlantica<br/>+448000001234<br/>consent on · rebooking 100%<br/>lanes 40/30/20/10 · deferred on"]:::t1
    M --> N["nordica<br/>+4780001234<br/>no consent · rebooking 50%<br/>lanes 50/30/10/10 · deferred off"]:::t2
    A --> VA1["voice agent runtime<br/>atlantica"]:::voice
    A --> MS1["MCP runtime /atlantica/mcp<br/>own lanes · saved copy · breaker · key"]:::mcp
    N --> VA2["voice agent runtime<br/>nordica"]:::voice
    N --> MS2["MCP runtime /nordica/mcp<br/>own lanes · saved copy · breaker · key"]:::mcp
    classDef config fill:#F3E5F5,stroke:#8E24AA,color:#4A148C
    classDef t1 fill:#E3F2FD,stroke:#1E88E5,color:#0D47A1
    classDef t2 fill:#E0F7FA,stroke:#00ACC1,color:#006064
    classDef voice fill:#E8F5E9,stroke:#43A047,color:#1B5E20
    classDef mcp fill:#FFF3E0,stroke:#FB8C00,color:#E65100
```

[`config/tenants.yml`](config/tenants.yml) has three blocks:

- **`platform`**: service URLs and the trace sink, shared by every process.
- **`defaults`**: one section per module.
- **`tenants`**: each tenant's dialed numbers and overrides.

Each process builds one runtime per tenant and hands each module only its own merged section.
A call is matched to a tenant by its dialed number. Lane buckets, saved copy, breaker, lockout
counters, deferred queue, idempotency keys and identity-token keys are all per tenant. One
tenant's storm cannot starve another tenant, and that is tested.

## The MCP server

A real Model Context Protocol server built on the official `mcp` Python SDK (1.30.0):

- **Streamable HTTP**, one endpoint per tenant (`/atlantica/mcp`, `/nordica/mcp`), and **stdio**
  (`python -m mcp_server --stdio --tenant atlantica`).
- **Six tools** with input and output schemas and annotations:
  - `get_flight_status`, `get_alternatives`: public.
  - `lookup_caller_id`: masked summary only.
  - `verify_booking`: returns booking data only on a match.
  - `get_booking`, `rebook`: VERIFIED and scoped to the token's booking.
- **One resource**, `zingly://{tenant}/admission`, with live lane, saved-copy and breaker counters.
- **Identity travels out of band**, never through a tool argument: request `_meta.identity_token`,
  the `X-Identity-Token` header, or `ZINGLY_IDENTITY_TOKEN` for stdio clients.

[docs/MCP_SERVER.md](docs/MCP_SERVER.md) shows how to connect **Codex**, the **MCP Inspector**
or any MCP client.

## Demonstration flows

`scripts/run_flow.py` plays a YAML scenario from [`flows/`](flows) against the running servers.
It applies setup actions (fault injection, lane saturation, capacity, A/B split), places calls
through Genesys, checks every reply, and verifies the end state in the reservation system.
`--trace` prints the distributed trace of every turn. `--record` writes the pages in
[docs/flows/](docs/flows/README.md), built from the real spans.

| Flow | Shows |
|---|---|
| [01 happy rebooking](docs/flows/01_happy_rebooking.md) | likely → verified, side question then resume, commit in P0, signed token |
| [02 flight status, public](docs/flows/02_flight_status_public.md) | no identity needed; saved copy, 0 PSS requests, "as of" |
| [03 clarify then route](docs/flows/03_clarify_then_route.md) | ambiguous intent, one clarifying question |
| [04 verification lockout](docs/flows/04_verification_lockout.md) | three failures lock; no hint whether the reference exists |
| [05 caller asks for an agent](docs/flows/05_caller_asks_for_agent.md) | fast-path handover with full context |
| [06 consent declined](docs/flows/06_consent_declined.md) | consent first; "no" goes to a person |
| [07 PSS down](docs/flows/07_pss_down_handover.md) | safe failure, no attempt used up, callback offered |
| [08 PSS brownout](docs/flows/08_pss_brownout_saved_copy.md) | saved copy "as of", read-before-retry, idempotent reconciliation |
| [09 deferred commit](docs/flows/09_deferred_commit.md) | P0 saturated → deferred commit, confirmed later |
| [10 breaker opens](docs/flows/10_breaker_open_capacity.md) | breaker open → Genesys capacity check → person |
| [11 capacity full](docs/flows/11_capacity_full.md) | session ceiling → overflow to the human queue |
| [12 second tenant](docs/flows/12_second_tenant_nordica.md) | same deployment, Nordica config, rollout canary |
| [13 A/B split](docs/flows/13_ab_split_legacy_ivr.md) | Genesys sends the call to the legacy IVR |
| [14 MCP client direct](docs/flows/14_mcp_direct_client.md) | MCP protocol, guard, booking scope, idempotent write |

## Testing the gaps: spike, handover, degraded modes

[docs/TESTING_GAPS.md](docs/TESTING_GAPS.md) maps each risk in the design to the command
that demonstrates it, what to look for, and where it shows up in the trace.

The spike (`scripts/spike.py`) places 120 callers from the cancelled flight AT123 at 6 new calls
per second, 40% of whom rebook, against the 5 req/s reservation system. All traffic goes through
the real MCP protocol. Numbers vary a little from run to run.

| | Protection off | Protection on |
|---|---:|---:|
| PSS requests sent | 221 | 80 (3 of them the pre-warm) |
| **PSS 429 rejections** | **126** | **0** |
| PSS requests per call | 1.84 (low only because most calls failed early) | 0.67 |
| PSS peak accepted req/s | 5 (at the limit) | 4 (parent limit) |
| Callers rebooked | 5 | 50 (38 live + 12 deferred, all 12 confirmed) |
| Handed over because a backend call failed | 85 | 0 |
| Flight-status callers answered | 30 of 70 | 70 of 70 |
| Saved-copy hits | 0 | 220 |

## Tracing

Every process writes spans to `.run/traces.jsonl`. Context crosses process boundaries with
the W3C `traceparent` header, or in MCP `_meta`. So one caller turn is one trace through Genesys →
voice agent → MCP server → PSS. Use `scripts/trace.py` to read traces, the browser agent desktop
to see the trace of the last turn, or [docs/TRACING.md](docs/TRACING.md) for the span catalogue
and how each flow is executed component by component.

## Automated tests

`./start_up.sh test` runs **56 tests**:

- unit tests per library;
- MCP-server tests over the real protocol;
- end-to-end voice-agent tests, in which the voice agent talks MCP to the MCP server, which talks HTTP to the PSS, all in one process;
- architecture rules.

The flows above are the live, demonstrable counterpart.

## Production readiness

[docs/PRODUCTION_READINESS.md](docs/PRODUCTION_READINESS.md) lists, area by area, what is
simulated here and what must be built or enabled before going live.

## Layout

```
prototype/
  start_up.sh                    set up + start/stop everything
  config/tenants.yml             one file, all tenants
  libs/<module>/                 9 libraries: src/zingly_<module>/, tests/, pyproject.toml
  services/voice_agent/          gateway + composition root, MCP client
  services/mcp_server/           MCP server (SDK) + composition root, ops API
  sims/northbound/               Genesys simulator: server, CLI, browser UI, genesys.yml
  sims/southbound/               airline reservation system (rate limited, fault injection)
  flows/                         14 runnable demonstration flows (YAML)
  scripts/                       run_flow.py, record_flow.py, spike.py, trace.py, mint_identity_token.py
  docs/                          MCP server, testing the gaps, tracing, production readiness, recorded flows
  tests/                         architecture rules
  conftest.py                    in-process harness for the end-to-end tests
```
