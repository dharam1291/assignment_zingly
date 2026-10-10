# Atlantica Airways: Voice AI for Flight Disruption

**Solution design** · Zingly Voice Platform · Dharmendra Singh · v1.0 · October 2026

## 1. Summary

**Problem.** When weather cancels flights, calls jump 20x within minutes. Callers queue and repeat their booking reference, and every call loads a reservation system with strict rate limits.

**Solution.** A Zingly voice agent identifies the caller, explains their options, then either **rebooks them** (confirmed by SMS) or **hands them to a Genesys agent** who already has the full context. If every agent is busy, it books a callback. Twilio, Genesys and the reservation system (PSS) stay as they are, and if the bot is down the call goes to the human queue.

## 2. Architecture

![High-level architecture](./diagrams/high-level-architecture.webp)
*Figure 1: High-level architecture. Twilio → Genesys → bot or human.*

**How a call flows** (step numbers refer to Figure 1):

1. The caller dials the hotline. **Twilio** owns the number and passes the call to **Genesys** (steps 1–2).
2. A Genesys inbound flow decides **bot or human** using the A/B traffic percentage between the legacy IVR and Zingly, and calls Zingly's gateway to create a conversation (step 3).
3. Zingly creates a **LiveKit room** and returns the room ID. Genesys joins by SIP and the **voice agent worker** joins too, so both are participants in one room.
4. The worker handles speech and streams to the STT/TTS vendor. Welcome and consent audio is **pre-rendered and cached**, so it plays with no TTS call.
5. Transcripts go to the **AI-routing layer** (welcome, consent, disambiguation, case management, routing), which calls the separate **Auth service** when a request needs verification (step 5).
6. A **supervisor agent** picks a **domain agent**: Rebooking, Flight Status or FAQ (step 7). Domain agents reach the LLMs only through the **AI gateway**, using EU-region OpenAI and Anthropic deployments.
7. Every tool call passes the **Policy engine** (guardrails, resilience, rate limiting), then the **MCP server** to Atlantica's APIs, databases and knowledge base (step 8).
8. When the bot finishes or escalates, it returns `conversation_status=AGENT_HANDOVER` with category, subcategory and summary, and Genesys routes to a dedicated human agent.

**Why this shape.** Genesys in front gives A/B rollout, queues, callbacks and the human fallback for free. LiveKit rooms make the bot a real participant, so a human can join the same room and turn-taking, barge-in and vendor swaps come from the framework. Layered agents mean a new use case, such as baggage, is just a new domain agent. The AI gateway handles model routing, failover and PII redaction, and the MCP server is one standard door to Atlantica systems.

## 3. Voice pipeline

**Where Zingly sits relative to Twilio:** behind Genesys, which is behind Twilio. Twilio is the carrier only. Zingly receives the call from Genesys over SIP, into a LiveKit room, and every stage streams.

**Barge-in is handled in the voice agent worker.** At least 200 ms of caller speech plus a speech-to-text partial stops the audio, trims the bot's turn to the words actually heard, and tells the router. The AI disclosure and itinerary read-back cannot be interrupted.

**LLM hops are controlled by turn path**, so a caller can say anything:

| Turn path | Example | What decides | LLM calls before audio |
|---|---|---|---|
| Greeting, yes/no, keypad | "Hi" · "yes" | A fast path of exact-match rules on the transcript. No model. | **0** |
| Normal turn, same topic | "Move me to the 14:05" | The domain agent already running understands, confirms the topic, picks the tool and replies in one streamed call | **1** |
| First turn or topic change | "Where is my bag?" | One small classifier (domain, intent, confidence, "clarify?"), then the new domain agent | **1 small + 1** |
| Ambiguous or multi-step | "Change two flights and a hotel" | The supervisor plans with an LLM while a filler phrase plays | **2–3** |

**How "Hi" is handled without an LLM.** A fast path sits in front of the model. It normalises the transcript (lower-case, punctuation and filler removed) and compares it to short lists of greetings, acknowledgements, yes/no words and keypad digits. It fires only when the **whole utterance** matches, so "Hi, my flight was cancelled" goes on to the agent. Yes and no are read against the **pending question** the session already holds (consent, or "shall I book the 14:05?"), so they are never guessed. The welcome has already played at call start, so the reply to "Hi" is a cached phrase such as "How can I help with your flight today?". Anything the rules do not match goes to the LLM, so a miss costs one call, not a wrong answer.

**How we know the caller stayed on topic.** We do not assume it; we check on every turn at no extra cost. The domain agent runs on every turn anyway, and its output begins with a small decision field: `stay`, `switch:<domain>` or `clarify`. Speech starts only after that field, so nothing off-topic is spoken. If the caller changes topic ("Where is my bag?" during a rebooking), the field says `switch:baggage`, the small classifier confirms the new domain, and session state (identity level, booking, pending choice) carries over so the first task can resume. A side question such as an FAQ goes to the FAQ agent and then returns to the open task. On `clarify` the bot asks one short question. So staying on topic costs no extra call, and a topic change costs one small one.

## 4. Caller identification and fraud

**Verify on demand.** Nothing is asked until a request needs it. Genesys passes the caller-ID match as a free hint, and the **Auth service** checks the rest during the call, so flight status and FAQ never need a check. Authenticating every call upfront in Genesys was rejected: it adds friction for everyone, booking references are awkward on a keypad, and the bot can already do it in conversation.

![Caller identification](./diagrams/identification.svg)
*Figure 2: Identity is a level. The Auth service issues it, never the model.*

| Level | How it is reached                                                                                          | What it unlocks |
|---|------------------------------------------------------------------------------------------------------------|---|
| **Unknown** | Nothing or decline to authenticate                                                                         | Public flight status and FAQ |
| **Likely** | The caller's number matches a booking on a cancelled flight                                                | A masked summary. **No changes.** |
| **Verified** | Spoken booking reference plus surname, read back for confirmation                                          | Rebooking within the involuntary re-accommodation policy |
| **Strongly verified** | Verified, plus approval in the Atlantica app (OIDC login, matching two-digit code) or an SMS one-time code | Higher-risk actions: split bookings, minors, refunds |

**Failure path.** After three failed attempts self-service locks for one hour. The caller still gets public information or a person, and the agent is told the caller was not verified. The bot never confirms that a booking reference exists.

**Who can rebook by voice?** Only a Verified caller, within policy, for the passengers on that booking

## 5. Protecting the reservation system

The PSS (the airline's reservation system) accepts about **50 requests per second**, yet in a storm thousands of callers ask the same things. So the design keeps a copy per flight, asks the PSS once for many callers, and queues the rest by priority.

![Reservation protection](./diagrams/reservation-protection.svg)
*Figure 3: Prepare early, keep a copy, ask once, queue by priority.*

**Worked example.** Flight AT123, London to Boston, is cancelled and 180 passengers are affected.

1. **Prepare early.** At 09:00 Atlantica's disruption feed reports the cancellation. A worker pulls the passenger list (1 PSS request), finds alternatives for London–Boston economy and business (a few requests), and stores them in Zingly's own encrypted **saved copy**. This runs once, at low priority, before most callers dial. It is not a PSS replica.
2. **Answer from the saved copy.** At 09:10 hundreds of callers ask "Is my flight cancelled? What are my options?". Each is answered in under 50 ms with **0 PSS requests**.
3. **Ask once.** Options stay fresh for only 20–30 s, because seats sell out. If an entry expires and 50 callers ask in the same second, the first request goes to the PSS and the other 49 wait for the same answer: **1 request instead of 50**, and the saved copy is refilled.
4. **Priority lanes.** Requests that cannot be shared (each caller's own booking lookup and each rebooking) pass through four lanes that split the 50 per second. If a lane stays full, the PSS is not called and the caller hears a fallback.

**When a lane is full, what the caller hears**

| Lane | Share of 50/s | Waits up to | If still full, the caller hears |
|---|---|---|---|
| **P0** Book or hold a seat | 40% | 3 s | "I've noted your choice of the 14:05 to Boston. We're confirming it now, and you'll get a text within 30 minutes." (**deferred commit**, needs business sign-off) |
| **P1** Find the caller's booking | 30% | 1.5 s | "I can see AT123 to Boston was cancelled. This is as of 14:02, and I'll check again before I change anything." |
| **P2** Refresh options | 20% | 0.5 s | "The next flights I can see are 14:05 and 19:40. Availability changes quickly, so I'll check before I book." |
| **P3** Flight status | 10% | 0 s | "AT123 to Boston is cancelled, as of 14:02." |

**Under the hood**
- **Lanes:** each lane is a token bucket that refills at its share. A parent limit, set a little below 50, caps the total, and the counters live in Redis so every Zingly instance shares them. Idle lanes lend spare capacity to busier, higher lanes.
- **Ask once:** the Redis command `SET key NX` (set only if the key does not exist) is atomic, so only **one** of the 50 requests wins. That request calls the PSS, writes the fresh answer to the saved copy and releases the key. The other 49 wait a moment and read that answer. The key has a short expiry, so a failed first request never blocks anyone.

**Why it works.** Take 6 new calls per second in a storm (illustrative). This is what one call costs the PSS:

| The caller needs | Without protection | With protection |
|---|---|---|
| Flight status | 1 | 0 (saved copy) |
| Find their booking | 1 | 1 |
| Alternatives (asked twice) | 2 | 0 (saved copy) |
| Re-check, hold and confirm (only the 4 in 10 who rebook) | 3 | 1.2 (3 × 0.4) |
| **PSS requests per call** | **7** | **2.2** |
| **At 6 calls per second** | **42 per second**, close to the 50 limit before any retries | **13 per second**, about 4x headroom |

**Never kept:** holds and commits. A booking always re-checks the PSS live.

**At 20x.** Genesys makes a **capacity check** on Zingly before routing each call, which reads active sessions, vendor headroom and reservation-system health. A predictive autoscaler adds voice workers when a disruption event arrives, before the calls do, and speech and LLM vendors have reserved capacity. Above capacity the call overflows to the human queue with a callback offer, so no caller gets a busy tone.

## 6. Handover, screen-pop and callback

The bot returns `AGENT_HANDOVER` with **category, subcategory and summary**, **who the caller is and how they were verified**, the booking and disruption, and **every attempted action with its result** (for example "rebook to AT127 failed: reservation timeout, booking unchanged"). The Genesys flow reads these attributes, and sensitive detail is fetched by a Data Action under OAuth. On a **short wait** the call goes to a skill queue and the agent's screen-pop shows who, why and what was tried. On a **long wait or when all agents are busy** the flow offers a **callback** that keeps the caller's place, with the same attributes and screen-pop.

![Handover and callback](./diagrams/handover-callback.svg)
*Figure 4: Genesys owns the queue, the wait time and the callback.*

## 7. Degraded modes

| Failure | What the system does | What the caller hears |
|---|---|---|
| **LLM latency spike** (first token > 800 ms) | Hedge to a secondary model at 600 ms, then **deterministic mode**: templates, LLM only extracts answers | Same task, more scripted. No dead air. |
| **LLM outage** | Deterministic mode with grammar-based slots | "Say or key in option 1 or 2." |
| **Speech-to-text outage** | Secondary STT within 2 s, then keypad (DTMF) mode | "Please use your keypad." |
| **Text-to-speech outage** | Secondary TTS, then cached phrases | A different voice, same flow |
| **Reservation system brownout** | Lanes tighten, saved copy labelled "as of", commits become deferred commits | "I've recorded your choice of the 14:05. You'll get a text within 30 minutes." |
| **Reservation system down** | Information only, changes paused, handover with exact state | Accurate status and a callback offer |
| **Zingly unavailable or full** | Genesys error path sends the call to the human queue or a callback | A brief pause, then a person. **Never a dropped call.** |

## 8. Integration and security

| Interface | Auth | Semantics |
|---|---|---|
| Genesys → Zingly gateway (create conversation, capacity check) | OAuth 2.0 client credentials, 5-minute tokens, WAF | Idempotent on call ID |
| Genesys ↔ LiveKit room | SIP over TLS with SRTP, IP allow-list | Caller and agent join one room |
| Zingly → Atlantica (via MCP) | mTLS, per-tenant vault credentials | Budgeted reads, idempotent writes |
| Atlantica → Zingly (events); Zingly → Genesys (callback) | Signed webhook; OAuth client credentials | At-least-once; honour `Retry-After` on 429 |
| Extra check (Strongly verified) | Atlantica app login (**OIDC**) approves a push. Atlantica returns a signed token, expiry ≤ 120 s. | Verified against Atlantica's keys |

**Retries and idempotency:** the rebooking key is `hash(tenant, booking, from-flight, to-flight)` and excludes the call ID, so a dropped call that dials back cannot rebook twice. A timed-out write is never blindly retried: read the booking first, then retry under the same key. A failed commit releases the hold.

**Data protection**
- **Residency:** the whole platform, including the OpenAI and Anthropic deployments, runs in the EU. As Zingly is a US vendor, a DPA with Standard Contractual Clauses and a transfer-impact assessment are still needed.
- **PII** is tokenised before the model and restored at speech time. No payment or health data reaches it, with no retention and no training. Data is encrypted in transit and at rest with per-tenant keys. Redacted transcripts are kept 30 days, handoff context 24 hours, and no audio is stored.
- **Model safety:** flight times and entitlements come from tools and approved wording, never the model. Tools are allow-listed per identity level and every call is logged.

**Compliance.** **GDPR/UK GDPR** is the primary frame (contract performance, data minimisation, DPIA before go-live).