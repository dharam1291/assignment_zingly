# Prototype: a simulated disruption call, end to end, in text

This builds the slice the assignment recommends, using the module boundaries of the
[solution design](../docs/SOLUTION_DESIGN.md):

- a small server takes **caller utterances** (text standing in for audio),
- it **identifies** the caller against a **mocked reservation system with a hard 5 req/s limit**,
- it answers **rebooking options from the saved copy** when the limit is reached,
- it produces an **`AGENT_HANDOVER` JSON payload** for the Genesys screen-pop,
- a **load script** simulates a spike and shows the admission control and saved-copy behaviour.

There is no LLM and no API key. The agents run in the design's **deterministic mode** (§7), where
templates and slot filling sit behind the same interfaces an LLM version would use.

## Quick start

```bash
cd prototype
make install          # venv + every library installed editable (Python 3.11+)
make test             # 45 tests: per library, service integration, architecture rules
make run              # mock PSS on :9001, voice agent on :8080
make demo             # happy path: likely -> verified -> side question -> rebooked
make demo-handover    # PSS failing: safe failure + Genesys screen-pop
make demo-nordica     # same deployment, second tenant
make chat             # type as the caller
make spike            # load test: unprotected vs protected
make stop
```

## How it maps to the architecture

Each box in Figure 1 that belongs to the voice agent is its **own library** (`libs/<name>`, its own
`pyproject.toml` and tests). The **`voice_agent` service** composes them. Systems outside Zingly are
simulated under `sims/`.

| Library | Design box (§) | Interface it owns → default implementation | Config section |
|---|---|---|---|
| `core` | shared base | `TenantContext`, `IdentityLevel`, `TenantConfigStore` | — |
| `channel` | voice worker (§3) | `Channel` → `TextChannel` (LiveKit later) | `channel` |
| `ai_router` | AI routing: welcome, consent, fast path, disambiguation, business routing (§2.5, §3) | `IntentClassifier` → `KeywordClassifier`; `AIRouter`, `FastPath`, `BusinessRouter`, `Welcome` | `ai_router.*` |
| `agents` | supervisor + Rebooking / Flight Status / FAQ (§2.6) | `DomainAgent` → deterministic agents; `Supervisor` | `agents` |
| `auth` | Auth service, identity levels, lockout (§4) | `AuthService` → `DefaultAuthService` | `auth` |
| `policy` | Policy engine: guardrails, rate limiting, resilience (§5, §8) | `ToolGuard` → `LevelGuard`; `AdmissionController` → `LaneAdmission`; `CircuitBreaker` → `CountingBreaker` | `policy.*` |
| `saved_copy` | saved copy + "ask once" (§5) | `SavedCopy` → `InMemorySavedCopy` (Redis `SET NX` in production) | `saved_copy` |
| `mcp` | MCP server → airline APIs (§2.8) | `ToolRegistry` (MCP `tools/list` shape), `PssBackend` → `HttpPssBackend`, deferred commits | `mcp` |
| `handover` | `AGENT_HANDOVER`, screen-pop, callback (§6) | `HandoverBuilder` → `GenesysHandoverBuilder` | `handover` |

| Outside Zingly (simulated) | What it owns |
|---|---|
| `sims/mock_pss` | The airline's reservation system: one backend per airline, a **hard 5 req/s sliding window returning 429**, idempotent rebooking, fault injection |
| `sims/genesys_sim` | The Genesys inbound flow: **IVR-vs-bot A/B %**, capacity check, queue/callback decision, screen-pop |

### Dependency rule: libraries depend only on `core`

```
                   services/voice_agent   (composition root: the only place that wires modules)
   ┌────────┬─────────┬────────┬───────┬────────┬────────────┬──────────┬─────────┐
 channel ai_router  agents    auth   policy     mcp     saved_copy  handover   (libs/)
   └────────┴─────────┴────────┴───┬───┴────────┴────────────┴──────────┴─────────┘
                                 core   (tenant context, identity level, config loader)
```

A module's interfaces and default implementations live **inside that module**. When a module needs
another one, it declares the interface it needs as a `Protocol` **in its own package** (`ports.py`), and the
service plugs the other module's object into it. For example:

- `mcp/ports.py` declares `AdmissionPort`, `CachePort`, `GuardPort` and `BreakerPort`. `policy` and
  `saved_copy` match them without either side importing the other.
- `agents/ports.py` declares `ToolPort` and `AuthPort`. The service passes in the MCP `ToolRegistry` and the auth service.
- `auth` declares `BookingLookupPort`, and the service adapts MCP tools to it (`AuthLookupAdapter`).

`tests/test_architecture.py` fails the build if a library imports anything except `zingly_core` and itself.

## Multi-tenancy: one deployment, one config file

[`config/tenants.toml`](config/tenants.toml) contains `[defaults.<module>]` and `[tenants.<id>.<module>]`.
One `voice_agent` process loads it and builds **one runtime per tenant**, giving each module only its own merged section.

- **Tenant resolution:** each call is matched to a tenant by its **dialed number** (or an explicit `tenant_id` from Genesys).
- **Isolation:** each tenant has its own lane buckets, saved copy, breaker, lockout counters and deferred queue. Every key is
  prefixed with the tenant id, and idempotency keys include it. One tenant's storm cannot starve another tenant
  (tested).
- **Two sample tenants:**
  - **Atlantica:** consent prompt on; rebooking for 100% of calls.
  - **Nordica:** different welcome; no consent prompt; P0-heavy lane split; rebooking canaried to **50%**
    (the other half are handed over with `not_in_rollout`); no deferred commits; its own Genesys queues.

## The call flow in code

```
Genesys ──POST /v1/conversations──▶ gateway (idempotent on call_id, capacity check)
caller text ─▶ channel.inbound ─▶ ai_router.route
                                   ├─ fast path (hi / yes / no / "agent")      0 LLM calls in LLM mode
                                   ├─ same topic → active domain agent          1
                                   ├─ topic change → classifier + business routing (rollout %)
                                   └─ clarify / handover
                     agents.Supervisor ─▶ DomainAgent ─▶ ToolPort ─▶ mcp.ToolRegistry
                                                                       └─ guard → breaker → lane → saved copy / PSS
                     handover.build ─▶ AGENT_HANDOVER ─▶ Genesys screen-pop (+ Data Action for full context)
```

## What the prototype demonstrates

| Design claim | Where | How to see it |
|---|---|---|
| Identity is a level, issued by auth; caller-ID gives only a masked summary | `auth`, `agents/rebooking.py` | `make demo`: `likely` → `verified` |
| Three failures lock; a failure never reveals whether the reference exists | `auth` | `libs/auth/tests` |
| Saved copy with a 25 s freshness window; 50 concurrent misses → **1** PSS request | `saved_copy` | `libs/saved_copy/tests` |
| Priority lanes P0–P3 (40/30/20/10% of the parent rate), waits 3 / 1.5 / 0.5 / 0 s, higher lanes borrow from lower | `policy/lanes.py` | `libs/policy/tests`, spike lane stats |
| A full lane → fallback wording: "as of" copy, or a **deferred commit** confirmed later under the same idempotency key | `mcp/tools.py`, `agents/config.py` | spike: `rebooked_deferred` → `confirmed` |
| The idempotency key excludes the call id; a timed-out write reads the booking before any retry | `mcp/tools.py` | `libs/mcp/tests` |
| Side question during a task, then resume | `agents/supervisor.py` | `make demo` (bag question) |
| Handover with who, why, verification and every attempted action; masked attributes; Data Action for full context | `handover`, gateway | `make demo-handover` |
| Bot is never the only path: capacity check, error path, rollout % | gateway, `ai_router/business_routing.py`, `genesys_sim` | `GET /v1/capacity` |

## Spike results

`make spike`: 120 callers from the cancelled flight AT123, 6 new calls per second, 40% of them rebooking.
The reservation system's hard limit is 5 req/s. Numbers vary a little from run to run.

| | Unprotected | Protected |
|---|---:|---:|
| PSS requests sent | 223 | 76 (3 of them the pre-warm) |
| **PSS 429 rejections** | **125** | **0** |
| PSS requests per call | 1.86 (low only because most calls failed early) | 0.63 |
| PSS peak accepted req/s | 5 (at the limit) | 4 (parent limit) |
| Rebooked | 1 | 50 (44 live + 6 deferred, all 6 confirmed) |
| Handed over because a backend call failed | 84 | 0 |
| Flight-status callers answered | 35 of 70 | 70 of 70 |
| Saved-copy hits | 0 | 220 |

With protection on, the caller-ID hint, flight status and options come from the pre-warmed saved
copy. Only verification (P1) and the commit (P0) reach the PSS. When P1 is full, verification
uses the pre-warmed passenger list, and the handover notes "as of". When P0 is full, the choice
becomes a deferred commit. The p95 turn latency (~1.5 s) is lane waiting; in voice, a filler
phrase would cover it.

## HTTP API (voice agent, :8080)

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/v1/capacity?dialed_number=` | Genesys capacity check before routing to the bot |
| `POST` | `/v1/conversations` | `{call_id, dialed_number, caller_number}` → welcome (pre-rendered audio id), room id. Idempotent on `call_id` |
| `POST` | `/v1/conversations/{id}/utterances` | `{text}` or `{dtmf}` → reply, `turn_path`, `identity_level`, `conversation_status`, `handover` |
| `GET` | `/v1/handover-context/{context_ref}?tenant_id=` | Genesys Data Action: full context for the agent desktop |
| `POST` | `/v1/events/disruption` | `{tenant_id, flight}`: pre-warm. HMAC-signed when `gateway.webhook_secret_env` is set |
| `GET` | `/v1/admin/stats` | Per-tenant lanes, saved copy, deferred commits, breaker, tool results |
| `POST` | `/v1/admin/tenants/{id}/protection` | Demo switch used by the spike |

## Simulated here, real in production

| Prototype | Production (design) |
|---|---|
| Text in and out (`TextChannel`) | LiveKit room participant: streaming STT/TTS, barge-in, non-interruptible prompts (the `Channel` interface) |
| Keyword classifier, template agents | Small LLM classifier and LLM domain agents through the AI gateway (same `IntentClassifier` / `DomainAgent`) |
| In-process `ToolRegistry` with MCP-shaped tools | MCP server transport (stdio / streamable HTTP) around the same registry, with mTLS to Atlantica |
| In-memory lanes, saved copy, lockouts | Redis: shared buckets, `SET NX` single-flight, so all instances agree |
| No auth on gateway endpoints | OAuth 2.0 client credentials, WAF (§8) |
| Strongly verified level defined, not reachable | App push (OIDC) or SMS one-time code (§4) |
| Session state in process memory | Session store with TTL; handover context kept 24 h |

## Layout

```
prototype/
  config/tenants.toml       one file, all tenants
  libs/<module>/            9 libraries: src/zingly_<module>/, tests/, pyproject.toml
  services/voice_agent/     gateway + composition root (runtime.py, conversation.py, app.py)
  sims/                     mock_pss (rate-limited PSS), genesys_sim (caller + Genesys CLI)
  scripts/spike.py          load test
  tests/                    architecture rules
  Makefile
```
